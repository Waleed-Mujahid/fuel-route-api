"""Import the OPIS fuel-price CSV, geocoded entirely offline.

The CSV has no coordinates, only address/city/state text. Each row is
geocoded in two tiers, most precise first:

1. **Exit interchange** — if the address embeds a highway *and* exit
   number (e.g. "I-44, EXIT 283 & US-69") and that (state, highway,
   exit) triple is in `data/highway_exits.csv` (real OSM
   motorway_junction coordinates, built offline by
   `fetch_highway_exits`), the station is placed at that interchange.
2. **City centroid** — otherwise, joins against a vendored US city
   gazetteer on `(CITY, STATE)`, as before.

See data/README.md for where the gazetteer, its overrides file, and
the exit lookup come from.
"""

import csv
import json
import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fuelroute.models import FuelStation
from fuelroute.services.highways import parse_exit, parse_highway

# States/territories the assessment's routing is scoped to; the CSV also
# contains Canadian provinces (AB, BC, ON, QC...) which are out of scope.
US_STATE_CODES = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA',
    'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT',
    'VA', 'WA', 'WV', 'WI', 'WY', 'DC',
}

PRICE_QUANTUM = Decimal('0.0001')


def load_gazetteer(path: Path) -> dict[tuple[str, str], tuple[float, float]]:
    """Build a (CITY, STATE) -> (lat, lng) lookup from the vendored gazetteer."""
    gazetteer = {}
    with path.open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            key = (row['CITY'].strip().upper(), row['STATE_CODE'].strip().upper())
            gazetteer[key] = (float(row['LATITUDE']), float(row['LONGITUDE']))
    return gazetteer


def load_overrides(path: Path) -> dict[str, tuple[float, float]]:
    """Load the committed fixups for city/state pairs the gazetteer misses."""
    with path.open(encoding='utf-8') as f:
        raw = json.load(f)
    return {key: (entry['lat'], entry['lng']) for key, entry in raw.items()}


def load_highway_exits(path: Path) -> dict[tuple[str, str, str], tuple[float, float]]:
    """Build a (STATE, HIGHWAY, EXIT) -> (lat, lng) lookup from fetch_highway_exits' output.

    Returns an empty dict (never raises) if the file doesn't exist yet
    — exit-level precision is a bonus tier, not a hard requirement, so
    a fresh checkout that hasn't run `fetch_highway_exits` still
    imports fine via the city gazetteer alone.
    """
    if not path.exists():
        return {}
    lookup = {}
    with path.open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if not row['exit'].strip():
                continue  # sentinel row: this (state, highway) was queried and found nothing
            key = (
                row['state'].strip().upper(),
                row['highway'].strip().upper(),
                row['exit'].strip().upper(),
            )
            lookup[key] = (float(row['latitude']), float(row['longitude']))
    return lookup


def geocode_via_nominatim(city: str, state: str) -> tuple[float, float] | None:
    """Best-effort live geocode for a city/state pair not covered offline.

    Only reached with --geocode-fallback, and only for rows the vendored
    data doesn't already resolve — on the shipped dataset that's zero
    rows, so this stays off the hot path by default.
    """
    import requests

    response = requests.get(
        f'{settings.NOMINATIM_BASE_URL}/search',
        params={'q': f'{city}, {state}, USA', 'format': 'json', 'limit': 1},
        headers={'User-Agent': settings.NOMINATIM_USER_AGENT},
        timeout=settings.NOMINATIM_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        return None
    return float(results[0]['lat']), float(results[0]['lon'])


class Command(BaseCommand):
    help = (
        'Import the OPIS fuel-price CSV, geocoding stations offline: exit interchange when '
        'available, city gazetteer centroid otherwise.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv-path',
            default=str(Path(settings.BASE_DIR) / 'data' / 'fuel-prices.csv'),
        )
        parser.add_argument(
            '--cities-path',
            default=str(Path(settings.BASE_DIR) / 'data' / 'us_cities.csv'),
        )
        parser.add_argument(
            '--overrides-path',
            default=str(Path(settings.BASE_DIR) / 'data' / 'geocode_overrides.json'),
        )
        parser.add_argument(
            '--exits-path',
            default=str(Path(settings.BASE_DIR) / 'data' / 'highway_exits.csv'),
            help='Output of fetch_highway_exits; exit-level precision tier.',
        )
        parser.add_argument(
            '--geocode-fallback',
            action='store_true',
            help='Call Nominatim for any city/state pair the offline data misses.',
        )

    def handle(self, *args, **options):
        csv_path = Path(options['csv_path'])
        if not csv_path.exists():
            raise CommandError(f'CSV not found: {csv_path}')

        gazetteer = load_gazetteer(Path(options['cities_path']))
        overrides = load_overrides(Path(options['overrides_path']))
        exits = load_highway_exits(Path(options['exits_path']))
        self.stdout.write(
            f'Loaded {len(gazetteer)} gazetteer entries, {len(overrides)} overrides, '
            f'{len(exits)} exit interchanges.'
        )

        stations = []
        dropped_non_us = 0
        unresolved = set()
        fallback_cache: dict[tuple[str, str], tuple[float, float] | None] = {}
        # opis_id -> index into `stations` of the cheapest row kept for that
        # truckstop so far. The source CSV repeats the same physical
        # truckstop under one opis_id with several price quotes (and
        # sometimes a slightly different name string) — every duplicate
        # observed shares one address/city/state/geocode, so this keeps
        # exactly one row per truckstop, at its lowest listed price, rather
        # than relying on the optimizer to collapse duplicates that happen
        # to land on the same route mile marker.
        kept_index_by_opis_id: dict[int, int] = {}
        duplicate_rows_merged = 0

        with csv_path.open(newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                state = row['State'].strip().upper()
                if state not in US_STATE_CODES:
                    dropped_non_us += 1
                    continue

                city = row['City'].strip()
                address = row['Address'].strip()
                highway = parse_highway(address)
                exit_ref = parse_exit(address)

                coords = exits.get((state, highway, exit_ref)) if highway and exit_ref else None
                precision = 'exit'

                if coords is None:
                    key = (city.upper(), state)
                    coords = gazetteer.get(key) or overrides.get(f'{key[0]}|{key[1]}')
                    precision = 'city'

                    if coords is None and options['geocode_fallback']:
                        if key not in fallback_cache:
                            fallback_cache[key] = geocode_via_nominatim(city, state)
                            time.sleep(1.1)  # respect Nominatim's ~1 req/sec policy
                        coords = fallback_cache[key]

                    if coords is None:
                        unresolved.add(key)
                        continue

                lat, lng = coords
                price = Decimal(row['Retail Price']).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)
                opis_id = int(row['OPIS Truckstop ID'])

                station = FuelStation(
                    opis_id=opis_id,
                    name=row['Truckstop Name'].strip(),
                    address=address,
                    city=city,
                    state=state,
                    rack_id=row['Rack ID'].strip(),
                    price_per_gallon=price,
                    latitude=lat,
                    longitude=lng,
                    highway=highway,
                    geocode_precision=precision,
                )

                existing_index = kept_index_by_opis_id.get(opis_id)
                if existing_index is None:
                    kept_index_by_opis_id[opis_id] = len(stations)
                    stations.append(station)
                else:
                    duplicate_rows_merged += 1
                    if price < stations[existing_index].price_per_gallon:
                        stations[existing_index] = station

        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(stations, batch_size=1000)

        precision_counts = {'exit': 0, 'city': 0}
        for s in stations:
            precision_counts[s.geocode_precision] += 1

        self.stdout.write(self.style.SUCCESS(f'Imported {len(stations)} stations.'))
        self.stdout.write(
            f'Precision: {precision_counts["exit"]} at exit interchanges, '
            f'{precision_counts["city"]} at city centroids '
            f'({precision_counts["exit"] / len(stations):.1%} exit-level).'
        )
        self.stdout.write(f'Dropped {dropped_non_us} non-US rows.')
        if duplicate_rows_merged:
            self.stdout.write(
                f'Merged {duplicate_rows_merged} duplicate rows sharing an opis_id with an '
                f'already-kept truckstop (kept the cheapest listed price for each).'
            )
        if unresolved:
            self.stdout.write(self.style.WARNING(
                f'{len(unresolved)} city/state pairs could not be geocoded: '
                f'{sorted(unresolved)[:10]}{"..." if len(unresolved) > 10 else ""}'
            ))
        else:
            self.stdout.write(self.style.SUCCESS('All rows geocoded, 0 unresolved.'))

"""Import the OPIS fuel-price CSV, geocoded entirely offline.

The CSV has no coordinates, only city/state text, so this command joins
each row against a vendored US city gazetteer instead of geocoding
live. See data/README.md for where the gazetteer and its overrides
file come from.
"""

import csv
import json
import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from fuelroute.models import FuelStation
from fuelroute.services.highways import parse_highway

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
    help = 'Import the OPIS fuel-price CSV, geocoding stations offline via the US city gazetteer.'

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
        self.stdout.write(f'Loaded {len(gazetteer)} gazetteer entries, {len(overrides)} overrides.')

        stations = []
        dropped_non_us = 0
        unresolved = set()
        fallback_cache: dict[tuple[str, str], tuple[float, float] | None] = {}

        with csv_path.open(newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                state = row['State'].strip().upper()
                if state not in US_STATE_CODES:
                    dropped_non_us += 1
                    continue

                city = row['City'].strip()
                key = (city.upper(), state)
                coords = gazetteer.get(key) or overrides.get(f'{key[0]}|{key[1]}')

                if coords is None and options['geocode_fallback']:
                    if key not in fallback_cache:
                        fallback_cache[key] = geocode_via_nominatim(city, state)
                        time.sleep(1.1)  # respect Nominatim's ~1 req/sec policy
                    coords = fallback_cache[key]

                if coords is None:
                    unresolved.add(key)
                    continue

                lat, lng = coords
                address = row['Address'].strip()
                price = Decimal(row['Retail Price']).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)

                stations.append(FuelStation(
                    opis_id=int(row['OPIS Truckstop ID']),
                    name=row['Truckstop Name'].strip(),
                    address=address,
                    city=city,
                    state=state,
                    rack_id=row['Rack ID'].strip(),
                    price_per_gallon=price,
                    latitude=lat,
                    longitude=lng,
                    highway=parse_highway(address),
                ))

        FuelStation.objects.all().delete()
        FuelStation.objects.bulk_create(stations, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(f'Imported {len(stations)} stations.'))
        self.stdout.write(f'Dropped {dropped_non_us} non-US rows.')
        if unresolved:
            self.stdout.write(self.style.WARNING(
                f'{len(unresolved)} city/state pairs could not be geocoded: '
                f'{sorted(unresolved)[:10]}{"..." if len(unresolved) > 10 else ""}'
            ))
        else:
            self.stdout.write(self.style.SUCCESS('All rows geocoded, 0 unresolved.'))

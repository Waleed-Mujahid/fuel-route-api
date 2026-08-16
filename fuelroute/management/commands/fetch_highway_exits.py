"""Build data/highway_exits.csv: real (highway, exit) -> coordinates.

Offline, one-time, vendored-output step — the counterpart to the city
gazetteer, but keyed on highway+exit instead of city, so
`import_fuel_prices` can place a station at its actual interchange
instead of its city's centroid whenever the address embeds an exit.

For every (state, highway) pair actually referenced in the supplied
CSV, queries the Overpass API (OpenStreetMap) for that highway's
`motorway_junction` nodes within the state — nodes that are vertices of
the specific way tagged with that highway's `ref`, so the (state,
highway) scoping is exact, not a name guess. Two carriageways of a
divided highway each carry their own junction node for the same exit;
those are averaged into one coordinate per (state, highway, exit).

Coverage is necessarily uneven: Interstates and US-numbered highways
are tagged in OSM with a standardized `ref` (e.g. "I 44"), so they
resolve reliably. State routes (SR/SH/ST) are tagged inconsistently
across states (some carry no "SR" prefix at all in OSM) and mostly
return zero matches — those rows just fall back to the city gazetteer
in `import_fuel_prices`, same as before this command existed. That
fallback is the point: this is a precision upgrade for the rows it can
resolve, never a hard requirement for the rows it can't.
"""

import csv
import re
import time
from collections import defaultdict
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from fuelroute.management.commands.import_fuel_prices import US_STATE_CODES
from fuelroute.services.highways import parse_exit, parse_highway

_REF_SPLIT = re.compile(r'^([A-Z]+)(\d+)$')

_WAY_FILTER = '["highway"~"^(motorway|trunk|motorway_link|trunk_link)$"]'

_MAX_ATTEMPTS = 2
_BACKOFF_BASE_SECONDS = 5


def find_needed_combos(csv_path: Path) -> set[tuple[str, str]]:
    """Return every (state, normalized_highway) pair worth an Overpass query.

    Only rows whose address has *both* a parseable highway and exit are
    worth it — a highway ref with no exit number has nothing to look
    up against.
    """
    combos = set()
    with csv_path.open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            state = row['State'].strip().upper()
            if state not in US_STATE_CODES:
                continue
            address = row['Address'].strip()
            highway = parse_highway(address)
            if highway and parse_exit(address):
                combos.add((state, highway))
    return combos


def _ref_regex(highway: str) -> str | None:
    """Build an Overpass regex matching `highway`'s ref among a way's
    (possibly semicolon-packed) `ref` tag, or None if `highway` doesn't
    split into a letter prefix + number (nothing to query).

    Deliberately uses a literal space/hyphen character class rather
    than `\\s`/`\\d` shorthands -- Overpass's regex engine (E-RE) treats
    those as literal characters, not classes, and silently matches
    nothing.
    """
    match = _REF_SPLIT.match(highway)
    if not match:
        return None
    prefix, number = match.groups()
    return rf'(^|;) *{prefix}[ -]*{number} *($|;)'


def _run_query(session: requests.Session, query: str, log=lambda msg: None) -> list[dict]:
    """POST one Overpass query, retrying on rate-limit/server errors.

    Overpass's public instance has no documented hard rate limit like
    Nominatim's, but does return 429/504 under load; backing off and
    retrying is the polite, reliable way to run several hundred
    sequential queries against it.
    """
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        response = session.post(
            settings.OVERPASS_BASE_URL,
            data={'data': query},
            headers={'User-Agent': settings.OVERPASS_USER_AGENT},
            timeout=settings.OVERPASS_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            return response.json().get('elements', [])
        if response.status_code in (429, 504) and attempt < _MAX_ATTEMPTS:
            wait = _BACKOFF_BASE_SECONDS * attempt
            log(
                f'  got {response.status_code}, backing off {wait}s '
                f'(attempt {attempt}/{_MAX_ATTEMPTS})'
            )
            time.sleep(wait)
            continue
        response.raise_for_status()
    return []


def fetch_combo_exits(
    session: requests.Session, state: str, highway: str, log=lambda msg: None
) -> dict[str, tuple[float, float]]:
    """Return {exit_ref: (lat, lng)} for one (state, highway) pair.

    Empty when the highway doesn't split into prefix+number, or when
    OSM has no ref-tagged junction nodes for it in this state (the
    expected outcome for most non-Interstate/US refs).
    """
    ref_regex = _ref_regex(highway)
    if ref_regex is None:
        return {}

    # The query's own [timeout:N] budget is kept below the HTTP client
    # timeout so Overpass gives up and replies with a partial/error
    # response before the socket itself would time out.
    query_timeout = max(10, int(settings.OVERPASS_TIMEOUT_SECONDS) - 10)
    query = f'''
[out:json][timeout:{query_timeout}];
area["ISO3166-2"="US-{state}"]["admin_level"="4"]->.a;
way(area.a){_WAY_FILTER}["ref"~"{ref_regex}"];
node(w)["highway"="motorway_junction"]["ref"];
out body;
'''
    elements = _run_query(session, query, log=log)

    by_exit: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for element in elements:
        ref = element.get('tags', {}).get('ref', '')
        exit_ref = re.sub(r'[\s-]+', '', ref.strip().upper())
        if exit_ref and 'lat' in element and 'lon' in element:
            by_exit[exit_ref].append((element['lat'], element['lon']))

    return {
        exit_ref: (
            sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points),
        )
        for exit_ref, points in by_exit.items()
    }


class Command(BaseCommand):
    help = (
        'Build data/highway_exits.csv from OpenStreetMap via Overpass: real '
        '(state, highway, exit) -> coordinates, for every combo referenced in the CSV.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv-path',
            default=str(Path(settings.BASE_DIR) / 'data' / 'fuel-prices.csv'),
        )
        parser.add_argument(
            '--out-path',
            default=str(Path(settings.BASE_DIR) / 'data' / 'highway_exits.csv'),
        )
        parser.add_argument(
            '--sleep', type=float, default=1.5,
            help='Delay in seconds between Overpass requests.',
        )
        parser.add_argument(
            '--resume', action='store_true',
            help='Skip (state, highway) combos already present in --out-path.',
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help='Only process the first N combos (for testing).',
        )

    def handle(self, *args, **options):
        csv_path = Path(options['csv_path'])
        out_path = Path(options['out_path'])
        if not csv_path.exists():
            raise CommandError(f'CSV not found: {csv_path}')

        combos = sorted(find_needed_combos(csv_path))
        self.stdout.write(f'{len(combos)} (state, highway) combos need an exit lookup.')

        rows: list[tuple] = []  # (state, highway, exit, lat, lng); lat/lng blank for sentinel rows
        done_combos: set[tuple[str, str]] = set()
        if options['resume'] and out_path.exists():
            with out_path.open(newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    rows.append((
                        row['state'], row['highway'], row['exit'],
                        row['latitude'], row['longitude'],
                    ))
                    done_combos.add((row['state'], row['highway']))
            self.stdout.write(f'Resuming: {len(done_combos)} combos already fetched.')

        remaining = [c for c in combos if c not in done_combos]
        if options['limit'] is not None:
            remaining = remaining[:options['limit']]

        session = requests.Session()
        found_combos = 0
        empty_combos = 0
        failed_combos = 0
        for i, (state, highway) in enumerate(remaining, start=1):
            try:
                exits = fetch_combo_exits(session, state, highway, log=self.stdout.write)
            except requests.RequestException as exc:
                self.stdout.write(self.style.WARNING(
                    f'[{i}/{len(remaining)}] {state} {highway}: request failed ({exc}), '
                    f'skipping (will retry on next --resume).'
                ))
                failed_combos += 1
                continue

            if exits:
                found_combos += 1
                for exit_ref, (lat, lng) in exits.items():
                    rows.append((state, highway, exit_ref, lat, lng))
            else:
                # A genuine "OSM has nothing" result -- write a sentinel row
                # (blank exit/coords) so --resume treats this combo as done
                # rather than re-querying it every run. load_highway_exits
                # skips sentinel rows when building the import lookup.
                empty_combos += 1
                rows.append((state, highway, '', '', ''))

            self.stdout.write(f'[{i}/{len(remaining)}] {state} {highway}: {len(exits)} exits')

            with out_path.open('w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['state', 'highway', 'exit', 'latitude', 'longitude'])
                writer.writerows(rows)

            if i < len(remaining):
                time.sleep(options['sleep'])

        self.stdout.write(self.style.SUCCESS(
            f'Wrote {len(rows)} exit coordinates to {out_path} '
            f'({found_combos} combos resolved, {empty_combos} empty).'
        ))

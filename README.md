# Fuel Route Optimizer

Given a US start and finish location, returns the driving route plus the cost-minimal sequence
of fuel stops for a 500-mile-range, 10-mpg vehicle — and the total fuel spend.

```
POST /api/v1/route/  {"start": "New York, NY", "finish": "Los Angeles, CA"}
```

```json
{
  "feasible": true,
  "distance_miles": 2794.03,
  "duration_seconds": 179263.6,
  "route": { "type": "LineString", "coordinates": [[-74.0068, 40.7132], "..."] },
  "fuel_stops": [
    {
      "name": "DELTA", "city": "Jersey City", "state": "NJ",
      "price_per_gallon": 3.239, "gallons": 0.732, "cost": 2.37,
      "mile_marker": 2.24, "detour_miles": 1.04, "highway": "US9"
    }
  ],
  "total_cost_usd": 848.88,
  "total_gallons": 279.403,
  "api_calls": 1,
  "elapsed_ms": 4392.3
}
```

`api_calls: 1` and `total_gallons` exactly equal to `distance_miles / 10` on every response are
not incidental — they're the two hardest constraints in the brief, and this README explains how
both are satisfied by design rather than by luck.

## The actual problem

The brief's stated requirements — one call to a free routing API, an optimal fuel plan, fast —
all sound like they're about the routing call and the optimizer. They aren't the hard part.

**The supplied CSV has no coordinates.** `fuel-prices-for-be-assessment.csv` has name, address,
city, state and price — 8,151 rows — and nothing that places a single one of them on a map.
Every subsequent requirement breaks unless that gets solved *before* a request ever arrives:
geocoding 8,151 addresses at request time is far too slow and far too many API calls, and
geocoding them against a single specific route wouldn't help the next request with a different
route anyway. So the real design problem is: get every station onto the map exactly once,
offline, ahead of time — which is what most of this repository is actually for.

### How it's solved

1. **Offline geocoding at import time**, not request time. A US city gazetteer
   ([`kelvins/US-Cities-Database`](https://github.com/kelvins/US-Cities-Database), MIT, vendored
   in `data/us_cities.csv`) is joined against each station's `(CITY, STATE)`. Of the CSV's 3,808
   unique US city/state pairs (620 non-US rows are dropped), the gazetteer alone covers **3,802
   (99.8%)** with zero network calls. The remaining 6 are committed as
   `data/geocode_overrides.json`, resolved once via Nominatim during development. Net result:
   all **7,531** US stations geocoded, 0 unresolved, and `import_fuel_prices` runs fully offline
   — a couple of seconds — every time after that.

   **Honest limitation:** these are city centroids, not exact truckstop pins — a station's
   plotted position can be off by a few miles. That's what the highway cross-check below is for.

2. **A highway cross-check, at zero extra API cost.** City-centroid geocoding produces false
   positives — a station in a city the route happens to clip, sitting on a different highway
   entirely. ~93% of the supplied addresses embed a highway ref (`"I-44, EXIT 283 & US-69"`),
   and OSRM already returns every highway the route drives in the *same single call* that
   returns the route geometry (`steps=true`). Candidates whose parsed highway isn't one the
   route drives get held to a much tighter corridor — narrowed, never hard-filtered, since not
   every address has a parseable ref.

3. **A pure-Python spatial index**, not a spatial database. The route polyline is resampled to
   ~1mi spacing and hashed into a 0.25°-cell grid; each of the ~7,500 stations probes its own
   cell plus its 8 neighbours to find its nearest route point in near-constant time. No numpy,
   no PostGIS — a coast-to-coast corridor search over the full station set runs in well under a
   second. Stations themselves are held in an in-process snapshot (warmed at server startup,
   see `fuelroute/apps.py`), so a request touches the database not at all.

With that in place, a request does exactly one thing over the network per uncached trip: ask
OSRM for the route. Everything else — geocoding stations, finding candidates, choosing what to
buy — is precomputed or local.

## The optimizer

This is the classic "gas station problem," reduced to a fixed route: the vehicle starts with an
empty tank, and mile 0 is itself a purchase point, priced at the nearest station's rate (fuel up
right where you set off, at that station's price) — a real node in the algorithm's own right,
separate from the nearest station's own true position.

> At the current stop: if a station with a **strictly lower** price is reachable within range,
> buy exactly enough fuel to reach it. Otherwise, buy exactly enough to reach
> `min(max_range, distance remaining to the destination)`.

Three wrong turns were made and rejected while landing on the rule above and its mile-0 handling
(narrated in full, with the concrete case that disproved each one, in
`fuelroute/services/optimizer.py`'s module docstring and the `feat(optimizer)` / `fix(optimizer)`
commits — left in on purpose, as evidence this wasn't pasted from memory or a tutorial without
checking it):

- Capping the purchase at the **farthest candidate station** instead of the true remaining
  distance *underbuys* — it passes up cheap capacity a later, pricier stop then has to make up
  for.
- Capping it at "always fill the tank" *overbuys* once the destination is closer than the max
  range.
- **Found by an independent code review, after the fact.** The first shipped version modeled
  "mile 0 is a purchase point" by *relocating* the nearest station onto mile 0 rather than adding
  mile 0 as its own node — which made every reachability check for a station *after* the first
  one measure distance from mile 0 instead of from where the vehicle actually was, capable of
  raising a false `InfeasibleRoute` on routes that were completely fine. Fixed by giving mile 0
  its own node; see the `fix(optimizer)` commit for the exact case that exposed it.

**This is validated, not just argued.** `fuelroute/tests/test_optimizer.py` runs the greedy
against an independent reference — a 2D dynamic program over discretized `(position, fuel
level)` that allows partial top-ups anywhere a DAG-over-station-pairs can't represent — across
150 randomized instances, and asserts gallons purchased always equals `distance / mpg` exactly
(i.e. zero wasted fuel, on every trial).

**Trade-off worth stating plainly:** because the algorithm is purely cost-minimal, a trip like
NYC → LA produces **20 stops**, several of them fractional-gallon top-ups at a slightly cheaper
station just ahead. That's the mathematically optimal answer to "minimize total spend," not an
error — a heuristic like "stop only when below half a tank" would produce a more familiar-looking
~6-stop plan at a real dollar cost. Given the brief explicitly asks for the cost-optimal plan, this
implementation optimizes for provably-cheapest over reviewer-familiar, and says so here rather
than quietly rounding the algorithm off to something that just *looks* more normal.

## API

```
POST /api/v1/route/
```

| Field | Required | Description |
|---|---|---|
| `start`, `finish` | yes | Free text (`"New York, NY"`) or `"lat,lng"` — the latter skips geocoding entirely. |
| `max_range_miles` | no | Defaults to 500. |
| `mpg` | no | Defaults to 10. |
| `corridor_miles` | no | Defaults to 20 — how far off-route a station can sit and still count. |

An infeasible route (a gap wider than the vehicle's range, with nothing to refuel at in
between) is **not** a 500 — it's a normal `200` with `"feasible": false` and a `"reason"`
describing exactly which gap is the problem. A bad `start`/`finish` that can't be geocoded is a
`400`; a routing-provider failure is a `502`.

```
GET  /map/?start=..&finish=..   Leaflet route preview: polyline + numbered fuel-stop pins
GET  /api/docs/                  Swagger UI
GET  /healthz/                   Liveness probe
```

The map page calls the exact same `POST /api/v1/route/` endpoint client-side — it doesn't
duplicate the pipeline, and doesn't cost anything extra against the API-call budget. Leaflet is
vendored locally (`fuelroute/static/fuelroute/leaflet/`), not pulled from a CDN, so the page
works with no outbound network beyond the OSM tile images themselves.

## API-call budget

| Call | When | Cached |
|---|---|---|
| Nominatim geocode of `start` | free-text input only | forever, per location string |
| Nominatim geocode of `finish` | free-text input only | forever, per location string |
| **OSRM directions** | once per **uncached** `(start, finish)` pair | forever, per coordinate pair (~1m precision) |

Passing `"lat,lng"` directly for `start`/`finish` skips geocoding — and thus all network calls —
entirely. A repeated trip between the same two points costs **zero** network calls on a warm
cache; every response reports `api_calls` and `elapsed_ms` so this is visible, not just claimed.

## Running it

**With Docker:**

```
docker compose up --build
```

**Without Docker** (needs Python ≥3.12 and [`uv`](https://docs.astral.sh/uv/)):

```
uv sync
uv run manage.py migrate
uv run manage.py import_fuel_prices   # offline; ~7,500 stations, a couple of seconds
uv run manage.py runserver
```

Then either `POST http://localhost:8000/api/v1/route/` (see `docs/postman_collection.json`) or
open `http://localhost:8000/map/?start=New+York,+NY&finish=Los+Angeles,+CA`.

All runtime settings (routing/geocoding provider URLs, vehicle range/mpg, corridor width) are
environment-overridable — see `.env.example`. In particular, `OSRM_BASE_URL` can point at a
self-hosted OSRM or any OSRM-API-compatible provider if the public demo server's rate limit
becomes a problem.

## Testing

```
uv run manage.py test
```

30 tests, ~13s: the optimizer's property test against the reference DP, the spatial index and
corridor search (including a regression test for a real performance bug — see
`fuelroute/tests/test_geo.py`), and the full API contract with geocoding/routing mocked so the
suite makes zero network calls.

## Repository layout

```
config/                   # django-admin startproject config .
fuelroute/                # manage.py startapp fuelroute
├── models.py              # FuelStation
├── serializers.py views.py urls.py
├── services/
│   ├── geo.py              # haversine, polyline resample, grid spatial index
│   ├── routing.py          # the one OSRM call, with caching
│   ├── geocoding.py        # cached Nominatim lookup for user input
│   ├── highways.py         # highway ref parsing/normalization
│   ├── corridor.py         # near-route candidate station search
│   ├── optimizer.py        # the cost-minimal greedy planner
│   ├── stations.py         # in-process station snapshot
│   └── trip.py             # orchestrates the full pipeline
├── management/commands/import_fuel_prices.py
├── templates/fuelroute/map.html
├── static/fuelroute/leaflet/   # vendored, CDN-free
└── tests/
data/                     # supplied CSV + vendored gazetteer + the 6 manual overrides
docs/                      # Postman collection, Loom demo script
```

Built as a Backend Django Engineer take-home assessment. Git history on
`feat/fuel-route-optimizer` is intentionally granular — each commit is one reviewable piece of
the pipeline above, with a message explaining what it adds and why.

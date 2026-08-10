# Loom demo script (~5 min)

Screen: Postman on one side, `/map/` open in a browser tab on the other.

## 1. The problem, in one sentence (30s)

"Given a US start and finish, return the route plus the cheapest way to buy fuel along it,
calling the routing API as few times as possible. The dataset given for prices has no
coordinates at all — just name, address, city, state, price — so the real problem is getting
7,500+ stations onto a map before a request ever comes in, offline, once."

## 2. Offline import (30s)

Terminal:

```
uv run manage.py import_fuel_prices
```

Point out: runs in ~2 seconds, zero network calls, imports all 7,531 US stations. Mention the
gazetteer join (99.8% coverage) + the 6 committed manual overrides for the rest.

## 3. Postman: the main request (90s)

Run **"Route: NYC -> LA"** from the collection. While it loads:

- "One call to OSRM for the whole trip — the response reports `api_calls: 1` so that's not just
  a claim."
- Response lands. Point at `total_cost_usd`, `total_gallons` (equal to `distance_miles / 10`
  exactly — no wasted fuel), and the `fuel_stops` array.
- Mention the stop count (~20) is the actual cost-optimal answer, not a bug — explain briefly
  (see README "Trade-off worth stating plainly").

## 4. Postman: the edge cases (60s)

Run in quick succession:

- **Direct `lat,lng` input** — skips geocoding entirely, zero Nominatim calls.
- **Infeasible route** (`max_range_miles: 10`) — still a `200`, `feasible: false`, with a
  `reason` naming the exact gap. Not a 500.
- **Unresolvable location** — a clean `400`.

"Every failure mode returns something structured and correct, not a stack trace."

## 5. Repeat the same request — the cache (30s)

Re-run the NYC -> LA request. Point at `elapsed_ms` dropping and `api_calls: 0` — the same
route between the same two points never asks OSRM twice.

## 6. The map (45s)

Switch to `/map/?start=New+York,+NY&finish=Los+Angeles,+CA`. Polyline + numbered pins load from
the identical endpoint just demoed in Postman — same pipeline, same one OSRM call, just a
different renderer. Click a pin or two to show the popup (name, price, gallons, cost).

## 7. Optimizer correctness (30s)

`uv run manage.py test fuelroute.tests.test_optimizer` — the property test running live: the
greedy checked against an independent reference solver across 150 randomized trip instances.
"This is the part I didn't want to just trust from memory — verified against a solver that
computes the actual optimum, not just checked by eye."

## 8. Wrap (15s)

"README has the full design writeup — the geocoding problem, the highway cross-check, and the
two wrong turns the optimizer took before landing on the rule it uses now. Code's on
`feat/fuel-route-optimizer`, one commit per piece of the pipeline."

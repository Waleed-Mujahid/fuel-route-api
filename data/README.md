# Data

- `fuel-prices.csv` — the OPIS truckstop price list supplied with the assessment.
  Name, address, city, state and retail price only; no coordinates.
- `highway_exits.csv` — real `(state, highway, exit) -> lat/lng` coordinates, built by
  `manage.py fetch_highway_exits` from the Overpass API (OpenStreetMap): for every
  `(state, highway)` pair actually referenced in `fuel-prices.csv`, every `motorway_junction`
  node belonging to that specific highway within that state. `import_fuel_prices` uses this as
  its most-precise geocoding tier — a station whose address embeds a highway *and* exit number
  (e.g. `"I-44, EXIT 283 & US-69"`) is placed at that real interchange instead of its city's
  centroid. Committed so a fresh checkout never has to re-run the fetch; regenerate with
  `manage.py fetch_highway_exits --resume` (safe to re-run — it's idempotent and skips
  `(state, highway)` pairs already in the file) if `fuel-prices.csv` changes. As shipped: all
  462 `(state, highway)` pairs the CSV references have been queried; 354 resolved to real data
  (16,547 exit coordinates) and 108 came back genuinely empty from OSM. Net effect on the imported
  dataset: **2,890 of 6,626 stations (43.6%) geocode to a real interchange**; the rest fall
  through to the city tier below. Coverage is necessarily uneven: Interstates and
  US-numbered highways are tagged in OSM with a standardized `ref` and resolve reliably; state
  routes (SR/SH/ST) are tagged inconsistently per state and mostly don't resolve. (Station counts
  are post-dedup — `import_fuel_prices` merges the 905 rows in `fuel-prices.csv` that repeat an
  `opis_id` for the same truckstop at a different price, keeping the cheapest; see README.md.)
- `us_cities.csv` — US city → lat/lon gazetteer, vendored from
  [kelvins/US-Cities-Database](https://github.com/kelvins/US-Cities-Database) (MIT licensed).
  The fallback geocoding tier: used to place any station the exit tier above doesn't resolve,
  by joining `fuel-prices.csv` offline on `(CITY, STATE)`. Covers 99.8% of stations that reach
  this tier with zero network calls.
- `geocode_overrides.json` — the handful of city/state pairs in `fuel-prices.csv` that the
  gazetteer doesn't cover, geocoded once via Nominatim and committed so the import stays
  offline and reproducible. Regenerate by re-running the lookup for any new miss reported by
  `import_fuel_prices`.

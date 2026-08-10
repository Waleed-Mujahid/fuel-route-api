# Data

- `fuel-prices.csv` — the OPIS truckstop price list supplied with the assessment.
  Name, address, city, state and retail price only; no coordinates.
- `us_cities.csv` — US city → lat/lon gazetteer, vendored from
  [kelvins/US-Cities-Database](https://github.com/kelvins/US-Cities-Database) (MIT licensed).
  Used to geocode `fuel-prices.csv` offline by joining on `(CITY, STATE)`, so the import
  command makes zero network calls for 99.8% of stations.
- `geocode_overrides.json` — the handful of city/state pairs in `fuel-prices.csv` that the
  gazetteer doesn't cover, geocoded once via Nominatim and committed so the import stays
  offline and reproducible. Regenerate by re-running the lookup for any new miss reported by
  `import_fuel_prices`.

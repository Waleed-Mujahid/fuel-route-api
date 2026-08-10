Leaflet 1.9.4 (https://leafletjs.com/), vendored so `/map/` renders with
zero CDN requests — a page reload never costs the OSRM/Nominatim call
budget, and works with no outbound network access at all beyond the
map tiles themselves.

Files as published in the `leaflet` npm package's `dist/`, unmodified.
BSD-2-Clause, (c) 2010-2023 Volodymyr Agafonkin, (c) 2010-2011 CloudMade.

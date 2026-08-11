Leaflet 1.9.4 (https://leafletjs.com/), vendored so the map library
itself makes zero CDN requests and works with no outbound network
access beyond the map tiles themselves. Planning a route from `/map/`
still calls the same `POST /api/v1/route/` endpoint the JSON API does,
so a cold cache still spends the usual Nominatim/OSRM calls — only a
repeat request for the same route/locations is free.

Files as published in the `leaflet` npm package's `dist/`, unmodified.
BSD-2-Clause, (c) 2010-2023 Volodymyr Agafonkin, (c) 2010-2011 CloudMade.

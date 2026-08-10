"""Routing client — the one call to a routing API the whole request makes.

Talks to any OSRM-API-compatible server: the free public OSRM demo
server by default, or a self-hosted OSRM / OpenRouteService's OSRM-
compatible endpoint by pointing OSRM_BASE_URL at it (see .env.example).
A single request with steps=true returns the route geometry, distance,
duration and every step's highway ref in one round trip.
"""

import hashlib
from dataclasses import dataclass, field

import requests
from django.conf import settings
from django.core.cache import cache

from fuelroute.services.highways import parse_route_highways

METERS_PER_MILE = 1609.344

# Cache key precision for routes: 5 decimal degrees is ~1 metre, so this
# only merges requests that are effectively the same two points, never
# genuinely different ones.
_COORD_CACHE_DECIMALS = 5


class RoutingError(Exception):
    """Raised when a route can't be produced or the provider call fails."""


@dataclass
class Route:
    distance_miles: float
    duration_seconds: float
    coordinates: list[tuple[float, float]]  # (lng, lat), GeoJSON order
    highways: set[str] = field(default_factory=set)


class OSRMClient:
    """Thin client for OSRM's ``/route/v1`` endpoint."""

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or settings.OSRM_BASE_URL).rstrip('/')
        self.timeout = timeout if timeout is not None else settings.OSRM_TIMEOUT_SECONDS

    def get_route(self, start: tuple[float, float], finish: tuple[float, float]) -> Route:
        """Fetch the driving route between two (lat, lng) points.

        Raises RoutingError if the two points can't be connected by road
        or the HTTP request itself fails.
        """
        start_lat, start_lng = start
        finish_lat, finish_lng = finish
        url = (
            f'{self.base_url}/route/v1/driving/'
            f'{start_lng},{start_lat};{finish_lng},{finish_lat}'
        )

        try:
            response = requests.get(
                url,
                params={'overview': 'full', 'geometries': 'geojson', 'steps': 'true'},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise RoutingError(f'OSRM request failed: {exc}') from exc

        if data.get('code') != 'Ok' or not data.get('routes'):
            detail = data.get('message', data.get('code'))
            raise RoutingError(f'OSRM could not find a route: {detail}')

        return self._parse(data['routes'][0])

    @staticmethod
    def _parse(osrm_route: dict) -> Route:
        refs = [
            step.get('ref', '')
            for leg in osrm_route['legs']
            for step in leg['steps']
        ]
        return Route(
            distance_miles=osrm_route['distance'] / METERS_PER_MILE,
            duration_seconds=osrm_route['duration'],
            coordinates=[tuple(pt) for pt in osrm_route['geometry']['coordinates']],
            highways=parse_route_highways(refs),
        )


def get_route(start: tuple[float, float], finish: tuple[float, float]) -> Route:
    """Fetch a route using the default OSRM client built from settings."""
    return OSRMClient().get_route(start, finish)


def _route_cache_key(start: tuple[float, float], finish: tuple[float, float]) -> str:
    d = _COORD_CACHE_DECIMALS
    raw = f'{start[0]:.{d}f},{start[1]:.{d}f}->{finish[0]:.{d}f},{finish[1]:.{d}f}'
    return f'osrm_route:{hashlib.sha1(raw.encode()).hexdigest()}'


def get_cached_route(
    start: tuple[float, float], finish: tuple[float, float]
) -> tuple[Route, bool]:
    """Fetch a route, caching it forever by rounded (start, finish) coordinates.

    Returns (route, was_cached) so a caller can report whether this
    request actually made a network call to the routing provider — the
    same route between the same two points never needs asking OSRM
    twice, and the "one call" figure the API reports should reflect
    that honestly rather than always claiming 1.
    """
    key = _route_cache_key(start, finish)
    cached = cache.get(key)
    if cached is not None:
        return cached, True

    route = get_route(start, finish)
    cache.set(key, route, timeout=None)
    return route, False

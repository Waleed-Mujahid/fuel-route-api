"""Geocode free-text US locations for the API's start/finish inputs.

Uses Nominatim (OpenStreetMap), which requires a custom User-Agent per
its usage policy. Results are cached indefinitely — a location string
only ever needs to be resolved once — and an explicit "lat,lng" input
skips geocoding, and the network, entirely.
"""

import hashlib
import re

import requests
from django.conf import settings
from django.core.cache import cache

_LAT_LNG_PATTERN = re.compile(r'^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$')


class GeocodingError(Exception):
    """Raised when a location string can't be resolved to coordinates."""


def geocode(location: str) -> tuple[float, float]:
    """Resolve a location string to (lat, lng).

    Accepts either free text ("New York, NY") or an explicit "lat,lng"
    pair. Free-text results are cached forever under a normalized key,
    so a repeated location costs no network call on a warm cache.
    """
    direct = _LAT_LNG_PATTERN.match(location)
    if direct:
        latitude, longitude = float(direct.group(1)), float(direct.group(2))
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise GeocodingError(f'Invalid coordinates: {location!r}')
        return latitude, longitude

    normalized = location.strip().lower()
    cache_key = f'geocode:{hashlib.sha1(normalized.encode()).hexdigest()}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = requests.get(
            f'{settings.NOMINATIM_BASE_URL}/search',
            params={'q': location, 'format': 'json', 'limit': 1, 'countrycodes': 'us'},
            headers={'User-Agent': settings.NOMINATIM_USER_AGENT},
            timeout=settings.NOMINATIM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        results = response.json()
        if not results:
            raise GeocodingError(f'No match found for {location!r}')
        coords = (float(results[0]['lat']), float(results[0]['lon']))
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise GeocodingError(f'Nominatim request failed for {location!r}: {exc}') from exc

    cache.set(cache_key, coords, timeout=None)
    return coords

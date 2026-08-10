"""Pure-Python geo utilities: distance, route resampling and a spatial index.

No numpy/scipy/PostGIS — the point counts here (a few thousand route
samples, a few thousand stations) are small enough that plain Python
comfortably fits the sub-100ms budget the corridor search needs.
"""

import math
from collections import defaultdict
from typing import NamedTuple

EARTH_RADIUS_MILES = 3958.7613

# Cell size for the route spatial index, in degrees (~17 miles at mid
# latitudes). Coarse enough that a station only needs to probe its own
# cell plus its 8 neighbours to find the nearest route point.
GRID_CELL_DEGREES = 0.25


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points, in statute miles."""
    lat1_r, lng1_r, lat2_r, lng2_r = (math.radians(v) for v in (lat1, lng1, lat2, lng2))
    dlat = lat2_r - lat1_r
    dlng = lng2_r - lng1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


class RoutePoint(NamedTuple):
    lat: float
    lng: float
    mile: float  # cumulative distance along the route from its start


def resample_route(
    coordinates: list[tuple[float, float]], spacing_miles: float = 1.0
) -> list[RoutePoint]:
    """Resample a route polyline to roughly `spacing_miles` between points.

    `coordinates` is a sequence of (lng, lat) pairs in GeoJSON/OSRM order.
    Cumulative mileage is computed from the real segment-by-segment
    distance, not from the resampled points, so it stays accurate even at
    a coarse spacing. The first and last input points are always kept
    exactly.
    """
    if not coordinates:
        return []

    first_lng, first_lat = coordinates[0]
    points = [RoutePoint(lat=first_lat, lng=first_lng, mile=0.0)]
    cumulative = 0.0
    prev_lat, prev_lng = first_lat, first_lng

    for lng, lat in coordinates[1:]:
        cumulative += haversine_miles(prev_lat, prev_lng, lat, lng)
        prev_lat, prev_lng = lat, lng
        if cumulative - points[-1].mile >= spacing_miles:
            points.append(RoutePoint(lat=lat, lng=lng, mile=cumulative))

    if points[-1].mile != cumulative:
        points.append(RoutePoint(lat=prev_lat, lng=prev_lng, mile=cumulative))

    return points


class RouteIndex:
    """Grid-hash spatial index over resampled route points.

    Supports finding the route point nearest an arbitrary (lat, lng) in
    near-constant time, which is what the corridor search needs to place
    thousands of stations against a route without a spatial database.
    """

    def __init__(self, points: list[RoutePoint]):
        self._points = points
        self._cells: dict[tuple[int, int], list[RoutePoint]] = defaultdict(list)
        for point in points:
            self._cells[self._cell_key(point.lat, point.lng)].append(point)

    @staticmethod
    def _cell_key(lat: float, lng: float) -> tuple[int, int]:
        return (math.floor(lat / GRID_CELL_DEGREES), math.floor(lng / GRID_CELL_DEGREES))

    def nearest(self, lat: float, lng: float) -> RoutePoint | None:
        """Return the route point nearest to (lat, lng), or None for an empty index."""
        if not self._points:
            return None

        cell_lat, cell_lng = self._cell_key(lat, lng)
        candidates = [
            point
            for d_lat in (-1, 0, 1)
            for d_lng in (-1, 0, 1)
            for point in self._cells.get((cell_lat + d_lat, cell_lng + d_lng), [])
        ]
        # A station far from every route point (empty 3x3 block) falls
        # back to a brute-force scan; rare in practice since the corridor
        # search discards distant candidates before they ever reach here.
        if not candidates:
            candidates = self._points

        return min(candidates, key=lambda p: haversine_miles(lat, lng, p.lat, p.lng))

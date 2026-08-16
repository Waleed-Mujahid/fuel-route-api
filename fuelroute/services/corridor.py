"""Find candidate fuel stations near a route.

Combines the route's resampled spatial index (fuelroute.services.geo)
with the highway cross-check (fuelroute.services.highways): a station
survives if it's within the corridor of the route, where the corridor
narrows for stations whose parsed highway doesn't match anything the
route actually drives — those are more likely a city-centroid false
positive than a genuine nearby stop, but they're never hard-filtered.
"""

from dataclasses import dataclass

from django.conf import settings

from fuelroute.services.geo import RouteIndex, haversine_miles, resample_route
from fuelroute.services.routing import Route
from fuelroute.services.stations import StationSnapshot, get_snapshot

# How much tighter the corridor is for a station whose parsed highway
# doesn't match any highway the route drives. Still eligible, just held
# to a much shorter leash than a matched or unparseable one.
MISMATCH_CORRIDOR_FACTOR = 0.25


@dataclass
class Candidate:
    station: StationSnapshot
    mile_marker: float  # distance along the route from its start
    detour_miles: float  # distance from the station to the route
    highway_match: bool | None  # True/False if checkable, None if unparseable


def find_candidates(route: Route, corridor_miles: float | None = None) -> list[Candidate]:
    """Return every station within the corridor of `route`.

    Ordered by mile_marker (the order they're encountered driving from
    start to finish), which is what the optimizer needs.
    """
    corridor_miles = corridor_miles if corridor_miles is not None else settings.CORRIDOR_MILES

    route_points = resample_route(route.coordinates)
    index = RouteIndex(route_points)

    candidates = []
    for station in get_snapshot():
        nearest = index.nearest(
            station.latitude, station.longitude, search_radius_miles=corridor_miles
        )
        if nearest is None:
            continue

        highway_match = station.highway in route.highways if station.highway else None
        threshold = (
            corridor_miles
            if highway_match is not False
            else corridor_miles * MISMATCH_CORRIDOR_FACTOR
        )

        detour = haversine_miles(station.latitude, station.longitude, nearest.lat, nearest.lng)
        if detour > threshold:
            continue

        candidates.append(Candidate(
            station=station,
            mile_marker=nearest.mile,
            detour_miles=detour,
            highway_match=highway_match,
        ))

    candidates.sort(key=lambda c: c.mile_marker)
    return candidates

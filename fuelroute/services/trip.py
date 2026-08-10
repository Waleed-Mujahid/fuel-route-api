"""Orchestrate a full start-to-finish trip plan.

Wires together geocoding, routing, the corridor search and the
optimizer into a single call, so the JSON API and the map page (which
need identical results for identical inputs) share one pipeline
instead of duplicating it.
"""

import time
from dataclasses import dataclass

from django.conf import settings

from fuelroute.services.corridor import Candidate, find_candidates
from fuelroute.services.geocoding import geocode
from fuelroute.services.optimizer import InfeasibleRoute, Plan, plan_fuel_stops
from fuelroute.services.routing import Route, get_route


@dataclass
class TripResult:
    start_coords: tuple[float, float]
    finish_coords: tuple[float, float]
    route: Route
    candidates: list[Candidate]
    plan: Plan | None
    infeasible_reason: str | None
    elapsed_ms: float
    api_calls: int


def plan_trip(
    start: str,
    finish: str,
    max_range_miles: float | None = None,
    mpg: float | None = None,
    corridor_miles: float | None = None,
) -> TripResult:
    """Geocode, route and plan fuel stops for a trip from `start` to `finish`.

    An infeasible route (a gap too wide for the vehicle's range) is not
    an error here: it's recorded on `infeasible_reason` and `plan` is
    left `None`, so the caller can return a normal, structured response
    instead of a 500.
    """
    if max_range_miles is None:
        max_range_miles = settings.VEHICLE_MAX_RANGE_MILES
    if mpg is None:
        mpg = settings.VEHICLE_MPG

    started = time.monotonic()
    api_calls = 0

    start_coords = geocode(start)
    finish_coords = geocode(finish)

    route = get_route(start_coords, finish_coords)
    api_calls += 1

    candidates = find_candidates(route, corridor_miles=corridor_miles)
    stations = [(c.mile_marker, c.station.price_per_gallon) for c in candidates]

    plan: Plan | None = None
    infeasible_reason: str | None = None
    try:
        plan = plan_fuel_stops(stations, route.distance_miles, max_range_miles, mpg)
    except InfeasibleRoute as exc:
        infeasible_reason = str(exc)

    elapsed_ms = (time.monotonic() - started) * 1000

    return TripResult(
        start_coords=start_coords,
        finish_coords=finish_coords,
        route=route,
        candidates=candidates,
        plan=plan,
        infeasible_reason=infeasible_reason,
        elapsed_ms=elapsed_ms,
        api_calls=api_calls,
    )

"""Optimal greedy fuel-purchase planner.

Given fuel prices at points along a fixed route and a maximum tank
range, chooses how much fuel to buy at each stop to minimize total
spend. This is the classic "gas station problem" reduced to a bounded
route: the vehicle starts with an empty tank, and the station nearest
the route's start is treated as sitting at the origin itself — you
fuel up right where you set off, at that station's price — so a trip
is only infeasible if a gap between consecutive candidates (including
from the origin and to the destination) exceeds the vehicle's range.

The rule, applied at each stop in order of preference:

  1. If a station with a STRICTLY LOWER price is reachable within
     range, buy exactly enough fuel to reach the nearest one.
  2. Otherwise, fill up as much as is ever useful: enough to reach
     min(max_range_miles, distance remaining to the destination) —
     capacity, or the finish line, whichever comes first.

Rule 2 is the one easy to get subtly wrong. Capping it at the farthest
*candidate station* rather than at the true remaining distance
underbuys: it passes up cheap capacity that a later, pricier stop
would otherwise have to make up for. Capping it at a flat "always fill
the tank" overbuys once the destination is closer than the max range.
Both were tried and rejected while building this (see git history) —
capping at min(range, remaining distance) is what a property test
against an exact reference solver confirmed is correct. A virtual
destination node, appended here at the route's final mile and priced
at +infinity, makes the finish line participate in both rules: it's
never "the nearest cheaper station," so rule 2's remaining-distance
cap is what actually gets the last leg right, with no special case.

Validated with a property test (fuelroute/tests/test_optimizer.py)
against an independent dynamic-programming reference across hundreds
of randomized instances.
"""

import math
from dataclasses import dataclass


@dataclass
class _Node:
    effective_mile: float  # position used for range math
    true_mile: float  # real position, used for reporting
    price: float
    station_index: int


@dataclass
class FuelStop:
    """A station the plan actually buys fuel at."""

    station_index: int  # index into the `stations` list passed to plan_fuel_stops
    mile_marker: float
    price_per_gallon: float
    gallons: float
    cost: float


@dataclass
class Plan:
    stops: list[FuelStop]
    total_cost: float
    total_gallons: float


class InfeasibleRoute(Exception):
    """Raised when no combination of stops can complete the route within range."""


def plan_fuel_stops(
    stations: list[tuple[float, float]],
    distance_miles: float,
    max_range_miles: float,
    mpg: float,
) -> Plan:
    """Choose the cost-minimal fuel stops for a route of `distance_miles`.

    `stations` is a list of (mile_marker, price_per_gallon) pairs, one
    per candidate station, in any order and with duplicate positions
    allowed (the cheapest at any shared position wins).

    Raises InfeasibleRoute if no station is found at all, if the
    nearest one to the start is farther than `max_range_miles` (so the
    origin fill-up assumption can't apply), or if any later gap between
    reachable stations exceeds `max_range_miles`.
    """
    if distance_miles <= 0:
        return Plan(stops=[], total_cost=0.0, total_gallons=0.0)

    by_mile: dict[float, tuple[float, int]] = {}
    for index, (mile, price) in enumerate(stations):
        if 0 <= mile <= distance_miles and (mile not in by_mile or price < by_mile[mile][0]):
            by_mile[mile] = (price, index)

    if not by_mile:
        raise InfeasibleRoute(f'No candidate stations found along a {distance_miles:.1f}mi route.')

    ordered = sorted(by_mile.items())
    start_mile = ordered[0][0]
    if start_mile > max_range_miles:
        raise InfeasibleRoute(
            f'Nearest station to the start is {start_mile:.1f}mi away, '
            f'beyond the {max_range_miles:.0f}mi max range.'
        )

    nodes = [
        _Node(
            effective_mile=0.0 if i == 0 else mile,
            true_mile=mile,
            price=price,
            station_index=index,
        )
        for i, (mile, (price, index)) in enumerate(ordered)
    ]
    nodes.append(_Node(distance_miles, distance_miles, math.inf, -1))

    stops: list[FuelStop] = []
    leftover_miles = 0.0

    for i in range(len(nodes) - 1):
        node = nodes[i]

        reachable = []
        for later in nodes[i + 1:]:
            if later.effective_mile - node.effective_mile > max_range_miles:
                break
            reachable.append(later)

        if not reachable:
            next_mile = nodes[i + 1].effective_mile
            gap = next_mile - node.effective_mile
            raise InfeasibleRoute(
                f'No station within {max_range_miles:.0f}mi range between mile '
                f'{node.effective_mile:.1f} and mile {next_mile:.1f} (gap {gap:.1f}mi).'
            )

        cheaper = [n for n in reachable if n.price < node.price]
        if cheaper:
            target_distance = cheaper[0].effective_mile - node.effective_mile
        else:
            remaining_distance = distance_miles - node.effective_mile
            target_distance = min(max_range_miles, remaining_distance)

        fill = max(target_distance - leftover_miles, 0.0)
        if fill > 1e-9:
            gallons = fill / mpg
            stops.append(FuelStop(
                station_index=node.station_index,
                mile_marker=node.true_mile,
                price_per_gallon=node.price,
                gallons=gallons,
                cost=gallons * node.price,
            ))
            leftover_miles += fill

        leftover_miles -= nodes[i + 1].effective_mile - node.effective_mile

    return Plan(
        stops=stops,
        total_cost=sum(s.cost for s in stops),
        total_gallons=sum(s.gallons for s in stops),
    )

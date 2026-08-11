"""Tests for the greedy fuel-purchase planner.

The property test is the important one: it checks the greedy against
an independent reference (a 2D dynamic program over discretized
position x fuel-level) across hundreds of randomized instances, rather
than trusting the greedy rule by inspection. Two earlier, subtly wrong
versions of the rule (see optimizer.py's module docstring) both looked
reasonable and both failed exactly this test, which is why it's here
rather than just a handful of example-based cases.
"""

import random

from django.test import SimpleTestCase

from fuelroute.services.optimizer import InfeasibleRoute, plan_fuel_stops


def _discretized_reference(
    stations: list[tuple[float, float]],
    distance: float,
    max_range: float,
    mpg: float,
    step: float = 0.2,
) -> float | None:
    """Minimum cost to cover `distance` via a discretized DP, or None if infeasible.

    dp[fuel_idx] tracks the cheapest cost to be at the current position
    with that much fuel (in `step`-mile units), rolled forward one
    position-step at a time. Unlike a DAG over station-to-station edges,
    this lets a purchase at one station be "spent" partly reaching an
    intermediate point and partly blended with a later purchase, which
    is what makes it a genuine reference rather than a second guess.
    """
    by_mile: dict[float, float] = {}
    for mile, price in stations:
        if 0 <= mile <= distance and (mile not in by_mile or price < by_mile[mile]):
            by_mile[mile] = price
    if not by_mile:
        return None

    ordered = sorted(by_mile.items())
    if ordered[0][0] > max_range:
        return None

    n_pos = int(round(distance / step)) + 1
    n_fuel = int(round(max_range / step)) + 1

    # Mile 0 is a purchase point too, priced like the nearest station (the
    # vehicle starts empty and buys "at the origin" -- see optimizer.py's
    # docstring), *in addition to* that station's own true position, not
    # instead of it. Registering only mile 0 (an earlier version of this
    # function did that) hides exactly the bug it exists to catch: it
    # never lets the DP refuel again at the real station's own location.
    price_at: dict[int, float] = {0: ordered[0][1]}
    for mile, price in ordered:
        idx = int(round(mile / step))
        if idx not in price_at or price < price_at[idx]:
            price_at[idx] = price

    inf = float('inf')
    dp = [inf] * n_fuel
    dp[0] = 0.0

    for pos_idx in range(n_pos):
        price = price_at.get(pos_idx)
        if price is not None:
            new_dp = dp[:]
            best_f0_cost = inf
            for f in range(n_fuel):
                candidate = dp[f] - (f * step / mpg) * price
                best_f0_cost = min(best_f0_cost, candidate)
                total = best_f0_cost + (f * step / mpg) * price
                new_dp[f] = min(new_dp[f], total)
            dp = new_dp

        if pos_idx == n_pos - 1:
            break
        next_dp = [inf] * n_fuel
        for f in range(1, n_fuel):
            next_dp[f - 1] = min(next_dp[f - 1], dp[f])
        dp = next_dp

    best = min(dp)
    return best if best != inf else None


class OptimizerExampleTests(SimpleTestCase):
    def test_empty_route_has_no_stops(self):
        plan = plan_fuel_stops([], 0, 500, 10)
        self.assertEqual(plan.stops, [])
        self.assertEqual(plan.total_cost, 0.0)

    def test_no_stations_is_infeasible(self):
        with self.assertRaises(InfeasibleRoute):
            plan_fuel_stops([], 300, 500, 10)

    def test_gap_beyond_range_is_infeasible(self):
        # Nothing between mile 0 and mile 600 with a 500mi range.
        with self.assertRaises(InfeasibleRoute):
            plan_fuel_stops([(0, 3.0), (600, 3.0)], 600, 500, 10)

    def test_start_beyond_range_of_nearest_station_is_infeasible(self):
        with self.assertRaises(InfeasibleRoute):
            plan_fuel_stops([(600, 3.0)], 600, 500, 10)

    def test_single_station_within_range_buys_exactly_enough(self):
        plan = plan_fuel_stops([(0, 3.0)], 300, 500, 10)
        self.assertEqual(len(plan.stops), 1)
        self.assertAlmostEqual(plan.stops[0].gallons, 30.0)
        self.assertAlmostEqual(plan.total_cost, 90.0)

    def test_prefers_reaching_a_strictly_cheaper_station(self):
        # Cheaper station 100mi ahead, well within range: buy just enough to reach it.
        plan = plan_fuel_stops([(0, 4.0), (100, 2.0)], 200, 500, 10)
        first, second = plan.stops
        self.assertAlmostEqual(first.gallons, 10.0)  # 100mi / 10mpg
        self.assertAlmostEqual(second.gallons, 10.0)  # remaining 100mi

    def test_does_not_overbuy_past_the_destination(self):
        # No cheaper station ahead and the destination is closer than max range:
        # must buy exactly enough to finish, not a full tank's worth.
        plan = plan_fuel_stops([(0, 3.0)], 120, 500, 10)
        self.assertAlmostEqual(plan.stops[0].gallons, 12.0)

    def test_gallons_purchased_always_equals_distance_over_mpg(self):
        # No wasted fuel: every gallon bought is a gallon the trip needed.
        plan = plan_fuel_stops([(0, 3.5), (150, 3.0), (400, 3.2)], 480, 500, 10)
        self.assertAlmostEqual(plan.total_gallons, 48.0)

    def test_does_not_cap_purchase_at_the_farthest_candidate_station(self):
        """Regression case from the design process (see optimizer.py docstring).

        Stations at mile 0 ($2.00), mile 400 ($2.50) and mile 500 ($4.00),
        900mi trip, 500mi range. Capping the "no cheaper station ahead"
        purchase at the farthest *candidate* station (mile 500, only
        100mi from the mile-0 stop) rather than at the true remaining
        distance (900mi) would strand a full tank's reach unused at the
        cheap mile-0 stop and force a third, pricier purchase at the
        $4.00 station. Capping at remaining distance instead buys enough
        at mile 0 to reach mile 500 outright, then tops up once more at
        the $2.50 stop -- two purchases, $200.00 total, and the $4.00
        station is never touched.
        """
        stations = [(0, 2.0), (400, 2.5), (500, 4.0)]
        plan = plan_fuel_stops(stations, 900, 500, 10)
        self.assertEqual(len(plan.stops), 2)
        self.assertAlmostEqual(plan.total_cost, 200.0, places=2)
        self.assertAlmostEqual(plan.total_gallons, 90.0, places=6)

    def test_reachability_after_the_first_stop_uses_its_real_position(self):
        """Regression: a real, previously-shipped bug, found by external review.

        The nearest station to the start (mile 450) is itself well within
        range of the origin. The *next* station is only 150mi further, at
        mile 600 -- trivially reachable from mile 450 on a 500mi-range
        vehicle. An earlier version of this function measured that second
        station's distance from the origin (mile 0) instead of from where
        the vehicle actually was after the first stop, saw 600mi > 500mi,
        and raised InfeasibleRoute on a route that was completely fine.
        Verified against the discretized reference below, which agrees the
        true optimal cost is $260.00 (60gal at $3.00 from mile 0 covering
        the first two legs, 40gal at $2.00 for the last 400mi).
        """
        stations = [(450, 3.0), (600, 2.0)]
        plan = plan_fuel_stops(stations, 1000, 500, 10)
        self.assertAlmostEqual(plan.total_cost, 260.0, places=2)
        self.assertAlmostEqual(plan.total_gallons, 100.0, places=6)
        ref_cost = _discretized_reference(stations, 1000, 500, 10, step=0.5)
        self.assertAlmostEqual(ref_cost, 260.0, delta=1.0)

    def test_merges_a_split_purchase_at_the_same_station_into_one_stop(self):
        """The mile-0 origin purchase and the real first station's own
        decision can land on the same station; the response should read as
        one combined stop, not a suspicious-looking duplicate."""
        stations = [(450, 3.0), (600, 2.0)]
        plan = plan_fuel_stops(stations, 1000, 500, 10)
        station_indexes = [stop.station_index for stop in plan.stops]
        self.assertEqual(len(station_indexes), len(set(station_indexes)))


class OptimizerPropertyTests(SimpleTestCase):
    """Randomized cross-check against an independent reference solver."""

    def test_matches_discretized_reference_across_random_instances(self):
        rng = random.Random(7)
        trials = 150
        step = 0.2
        feasible_checked = 0

        for trial in range(trials):
            distance = rng.uniform(20, 250)
            n_stations = rng.randint(0, 8)
            stations = [
                (round(rng.uniform(0, distance), 1), round(rng.uniform(2.5, 5.0), 2))
                for _ in range(n_stations)
            ]
            max_range = rng.choice([80, 100, 150, 200])
            mpg = 10.0

            ref_cost = _discretized_reference(stations, distance, max_range, mpg, step=step)

            try:
                plan = plan_fuel_stops(stations, distance, max_range, mpg)
                greedy_cost = plan.total_cost
                greedy_feasible = True
            except InfeasibleRoute:
                greedy_cost = None
                greedy_feasible = False

            ref_feasible = ref_cost is not None
            self.assertEqual(
                ref_feasible,
                greedy_feasible,
                msg=f'trial {trial}: feasibility mismatch, distance={distance} '
                f'max_range={max_range} stations={stations}',
            )
            if not ref_feasible:
                continue

            feasible_checked += 1
            # The greedy must never claim a cost below the true optimum (that
            # would mean it produced an invalid plan), and should track it
            # closely -- the only slack allowed is the reference's own
            # discretization error at step=0.2mi.
            self.assertGreaterEqual(
                greedy_cost,
                ref_cost - 0.05,
                msg=f'trial {trial}: greedy beat the reference (bug) '
                f'ref={ref_cost:.4f} greedy={greedy_cost:.4f}',
            )
            self.assertLessEqual(
                greedy_cost,
                ref_cost + 0.3,
                msg=f'trial {trial}: greedy worse than reference by more than '
                f'discretization slack, ref={ref_cost:.4f} greedy={greedy_cost:.4f}',
            )
            self.assertAlmostEqual(plan.total_gallons, distance / mpg, places=6)

        self.assertGreater(feasible_checked, trials // 2)

"""Tests for haversine distance, route resampling and the grid-hash spatial index."""

from django.test import SimpleTestCase

from fuelroute.services.geo import RouteIndex, RoutePoint, haversine_miles, resample_route


class HaversineTests(SimpleTestCase):
    def test_same_point_is_zero(self):
        self.assertAlmostEqual(haversine_miles(40.0, -100.0, 40.0, -100.0), 0.0)

    def test_known_distance_nyc_to_la(self):
        # Great-circle NYC -> LA is ~2,446mi; driving distance (what OSRM
        # returns) is considerably longer, so this only checks the
        # geometry primitive, not anything route-related.
        nyc = (40.7128, -74.0060)
        la = (34.0522, -118.2437)
        distance = haversine_miles(*nyc, *la)
        self.assertAlmostEqual(distance, 2446, delta=5)


class ResampleRouteTests(SimpleTestCase):
    def test_empty_input_returns_empty(self):
        self.assertEqual(resample_route([]), [])

    def test_keeps_first_and_last_point_exactly(self):
        coordinates = [(-100.0, 40.0), (-99.5, 40.0), (-99.0, 40.0)]
        points = resample_route(coordinates, spacing_miles=1.0)
        self.assertEqual((points[0].lat, points[0].lng), (40.0, -100.0))
        self.assertEqual((points[-1].lat, points[-1].lng), (40.0, -99.0))
        self.assertEqual(points[0].mile, 0.0)

    def test_cumulative_mileage_is_monotonic(self):
        coordinates = [(-100.0 + 0.01 * i, 40.0) for i in range(50)]
        points = resample_route(coordinates, spacing_miles=1.0)
        miles = [p.mile for p in points]
        self.assertEqual(miles, sorted(miles))


class RouteIndexTests(SimpleTestCase):
    def test_finds_nearest_point_in_same_cell(self):
        points = [
            RoutePoint(lat=40.0, lng=-100.0, mile=0.0),
            RoutePoint(lat=40.05, lng=-100.0, mile=3.4),
        ]
        index = RouteIndex(points)
        nearest = index.nearest(40.04, -100.0)
        self.assertIsNotNone(nearest)
        self.assertEqual(nearest.mile, 3.4)

    def test_returns_none_for_a_point_nowhere_near_any_route_sample(self):
        # Regression test: nearest() must return None for a query point whose
        # 3x3 grid block is empty, not silently fall back to a brute-force
        # scan of every route point. That fallback was a real perf bug --
        # a coast-to-coast corridor search regressed from ~0.2s to ~20s
        # because most of the ~7.5k nationwide stations sit outside any
        # single route's grid cells entirely.
        points = [RoutePoint(lat=40.0, lng=-100.0, mile=0.0)]
        index = RouteIndex(points)
        self.assertIsNone(index.nearest(10.0, 10.0))

    def test_empty_index_returns_none(self):
        index = RouteIndex([])
        self.assertIsNone(index.nearest(40.0, -100.0))

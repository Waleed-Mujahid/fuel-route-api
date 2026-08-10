"""Tests for the corridor search: which stations count as "near the route"."""

from django.test import TestCase

from fuelroute.models import FuelStation
from fuelroute.services import stations as stations_service
from fuelroute.services.corridor import find_candidates
from fuelroute.services.routing import Route

# A straight route along latitude 40N, from -100.0 to -95.0 longitude
# (~265mi at this latitude), sampled finely enough that resampling has
# real points to index against.
_ROUTE_COORDINATES = [(-100.0 + 0.01 * i, 40.0) for i in range(501)]


def _make_route(highways=frozenset()) -> Route:
    return Route(
        distance_miles=265.0,
        duration_seconds=15000.0,
        coordinates=_ROUTE_COORDINATES,
        highways=set(highways),
    )


def _make_station(lat, lng, price='3.00', highway='', name='Test Stop'):
    return FuelStation.objects.create(
        opis_id=1,
        name=name,
        address='123 Main St',
        city='Testville',
        state='TX',
        rack_id='',
        price_per_gallon=price,
        latitude=lat,
        longitude=lng,
        highway=highway,
    )


class FindCandidatesTests(TestCase):
    def setUp(self):
        stations_service.clear_snapshot()
        self.addCleanup(stations_service.clear_snapshot)

    def test_station_on_the_route_is_found(self):
        _make_station(lat=40.0, lng=-97.5)
        candidates = find_candidates(_make_route(), corridor_miles=20)
        self.assertEqual(len(candidates), 1)
        self.assertLess(candidates[0].detour_miles, 1)

    def test_station_far_from_the_route_is_excluded(self):
        _make_station(lat=45.0, lng=-97.5)  # ~345mi north of the route
        candidates = find_candidates(_make_route(), corridor_miles=20)
        self.assertEqual(candidates, [])

    def test_candidates_are_ordered_by_mile_marker(self):
        _make_station(lat=40.0, lng=-96.0, name='Second')
        _make_station(lat=40.0, lng=-99.0, name='First')
        candidates = find_candidates(_make_route(), corridor_miles=20)
        self.assertEqual([c.station.name for c in candidates], ['First', 'Second'])

    def test_highway_mismatch_narrows_the_corridor_but_does_not_exclude(self):
        # ~10mi off the route: inside the normal 20mi corridor, but outside
        # the 0.25x-tightened corridor a highway mismatch gets held to.
        lat_offset = 10 / 69.0  # ~10mi of latitude
        _make_station(lat=40.0 + lat_offset, lng=-97.5, highway='I95')
        candidates = find_candidates(_make_route(highways={'I80'}), corridor_miles=20)
        self.assertEqual(candidates, [])

    def test_highway_match_gets_the_full_corridor(self):
        lat_offset = 10 / 69.0
        _make_station(lat=40.0 + lat_offset, lng=-97.5, highway='I80')
        candidates = find_candidates(_make_route(highways={'I80'}), corridor_miles=20)
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0].highway_match)

    def test_unparseable_highway_is_never_hard_filtered(self):
        lat_offset = 5 / 69.0
        _make_station(lat=40.0 + lat_offset, lng=-97.5, highway='')
        candidates = find_candidates(_make_route(highways={'I80'}), corridor_miles=20)
        self.assertEqual(len(candidates), 1)
        self.assertIsNone(candidates[0].highway_match)

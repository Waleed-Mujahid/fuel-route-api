"""API contract tests for POST /api/v1/route/.

Geocoding and routing are mocked at the fuelroute.services.trip module
boundary (where trip.py imported them into its own namespace), so the
suite makes zero network calls -- CI never touches Nominatim or OSRM.
Only the corridor search and optimizer run for real, against
FuelStation rows created in the test database.
"""

from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from fuelroute.models import FuelStation
from fuelroute.services import stations as stations_service
from fuelroute.services.geocoding import GeocodingError
from fuelroute.services.routing import Route, RoutingError

_START = (40.0, -100.0)
_FINISH = (40.0, -95.0)
_ROUTE_COORDINATES = [(-100.0 + 0.01 * i, 40.0) for i in range(501)]


def _fake_route(distance_miles=265.0) -> Route:
    return Route(
        distance_miles=distance_miles,
        duration_seconds=15000.0,
        coordinates=_ROUTE_COORDINATES,
        highways=set(),
    )


class RouteViewTests(APITestCase):
    def setUp(self):
        stations_service.clear_snapshot()
        self.addCleanup(stations_service.clear_snapshot)

    def _post(self, payload):
        return self.client.post('/api/v1/route/', payload, format='json')

    @patch('fuelroute.services.trip.get_cached_route')
    @patch('fuelroute.services.trip.geocode')
    def test_feasible_route_returns_full_plan(self, mock_geocode, mock_get_route):
        FuelStation.objects.create(
            opis_id=1, name='Cheap Gas', address='123 Main St', city='Testville',
            state='TX', rack_id='', price_per_gallon='3.00',
            latitude=40.0, longitude=-97.5, highway='',
        )
        mock_geocode.side_effect = [_START, _FINISH]
        mock_get_route.return_value = (_fake_route(), False)

        response = self._post({'start': 'A, TX', 'finish': 'B, TX'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertTrue(body['feasible'])
        self.assertEqual(body['api_calls'], 1)
        self.assertEqual(len(body['fuel_stops']), 1)
        self.assertGreater(body['total_cost_usd'], 0)
        self.assertAlmostEqual(body['total_gallons'], 26.5, places=1)
        self.assertEqual(body['route']['type'], 'LineString')

    @patch('fuelroute.services.trip.get_cached_route')
    @patch('fuelroute.services.trip.geocode')
    def test_cached_route_reports_zero_api_calls(self, mock_geocode, mock_get_route):
        FuelStation.objects.create(
            opis_id=1, name='Cheap Gas', address='123 Main St', city='Testville',
            state='TX', rack_id='', price_per_gallon='3.00',
            latitude=40.0, longitude=-97.5, highway='',
        )
        mock_geocode.side_effect = [_START, _FINISH]
        mock_get_route.return_value = (_fake_route(), True)

        response = self._post({'start': 'A, TX', 'finish': 'B, TX'})

        self.assertEqual(response.json()['api_calls'], 0)

    @patch('fuelroute.services.trip.get_cached_route')
    @patch('fuelroute.services.trip.geocode')
    def test_no_stations_near_route_is_feasible_false_not_500(self, mock_geocode, mock_get_route):
        mock_geocode.side_effect = [_START, _FINISH]
        mock_get_route.return_value = (_fake_route(), False)

        response = self._post({'start': 'A, TX', 'finish': 'B, TX'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertFalse(body['feasible'])
        self.assertIn('reason', body)
        self.assertEqual(body['fuel_stops'], [])

    @patch('fuelroute.services.trip.geocode')
    def test_unresolvable_location_returns_400(self, mock_geocode):
        mock_geocode.side_effect = GeocodingError("No match found for 'nowhereville'")

        response = self._post({'start': 'nowhereville', 'finish': 'B, TX'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.json())

    def test_missing_required_field_returns_400(self):
        response = self._post({'start': 'A, TX'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        body = response.json()
        self.assertIn('detail', body)
        self.assertIsInstance(body['detail'], str)
        self.assertIn('finish', body['detail'])

    @patch('fuelroute.services.trip.get_cached_route')
    @patch('fuelroute.services.trip.geocode')
    def test_routing_provider_failure_returns_502(self, mock_geocode, mock_get_route):
        mock_geocode.side_effect = [_START, _FINISH]
        mock_get_route.side_effect = RoutingError('OSRM could not find a route: NoRoute')

        response = self._post({'start': 'A, TX', 'finish': 'B, TX'})

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

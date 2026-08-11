from django.http import JsonResponse
from django.shortcuts import render
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from fuelroute.serializers import (
    ErrorResponseSerializer,
    RouteRequestSerializer,
    RouteResponseSerializer,
)
from fuelroute.services.geocoding import GeocodingError
from fuelroute.services.routing import RoutingError
from fuelroute.services.trip import TripResult, plan_trip


def healthz(request):
    """Liveness probe used by Docker/CI; touches no database or network."""
    return JsonResponse({'status': 'ok'})


def map_view(request):
    """Leaflet route preview page.

    Renders a static shell; the page itself calls POST /api/v1/route/
    client-side, so an optional ?start=&finish= only pre-fills and
    auto-submits the form rather than the server planning anything.
    """
    context = {
        'start': request.GET.get('start', ''),
        'finish': request.GET.get('finish', ''),
    }
    return render(request, 'fuelroute/map.html', context)


def _serialize_trip(result: TripResult) -> dict:
    """Build the JSON response body from a completed trip plan."""
    start_lat, start_lng = result.start_coords
    finish_lat, finish_lng = result.finish_coords

    body = {
        'feasible': result.plan is not None,
        'start': {'lat': start_lat, 'lng': start_lng},
        'finish': {'lat': finish_lat, 'lng': finish_lng},
        'distance_miles': round(result.route.distance_miles, 2),
        'duration_seconds': round(result.route.duration_seconds, 1),
        'route': {
            'type': 'LineString',
            'coordinates': [list(pt) for pt in result.route.coordinates],
        },
        'fuel_stops': [],
        'total_cost_usd': 0.0,
        'total_gallons': 0.0,
        'api_calls': result.api_calls,
        'elapsed_ms': round(result.elapsed_ms, 1),
    }

    if result.infeasible_reason is not None:
        body['reason'] = result.infeasible_reason
        return body

    plan = result.plan
    body['fuel_stops'] = [
        {
            'name': candidate.station.name,
            'address': candidate.station.address,
            'city': candidate.station.city,
            'state': candidate.station.state,
            'lat': candidate.station.latitude,
            'lng': candidate.station.longitude,
            'mile_marker': round(stop.mile_marker, 2),
            'detour_miles': round(candidate.detour_miles, 2),
            'highway': candidate.station.highway,
            'price_per_gallon': stop.price_per_gallon,
            'gallons': round(stop.gallons, 3),
            'cost': round(stop.cost, 2),
        }
        for stop, candidate in (
            (stop, result.candidates[stop.station_index]) for stop in plan.stops
        )
    ]
    body['total_cost_usd'] = round(plan.total_cost, 2)
    body['total_gallons'] = round(plan.total_gallons, 3)
    return body


class RouteView(APIView):
    """POST a US start/finish, get back the route and the cost-optimal fuel stops."""

    @extend_schema(
        request=RouteRequestSerializer,
        responses={
            200: RouteResponseSerializer,
            400: ErrorResponseSerializer,
            502: ErrorResponseSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        params = RouteRequestSerializer(data=request.data)
        if not params.is_valid():
            detail = '; '.join(
                f'{field}: {" ".join(str(e) for e in errors)}'
                for field, errors in params.errors.items()
            )
            return Response({'detail': detail}, status=status.HTTP_400_BAD_REQUEST)
        data = params.validated_data

        try:
            result = plan_trip(
                start=data['start'],
                finish=data['finish'],
                max_range_miles=data.get('max_range_miles'),
                mpg=data.get('mpg'),
                corridor_miles=data.get('corridor_miles'),
            )
        except GeocodingError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RoutingError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(_serialize_trip(result))

"""Request/response shapes for the route API, and drf-spectacular's schema source."""

from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(help_text='US location, e.g. "New York, NY" or "40.71,-74.00"')
    finish = serializers.CharField(help_text='US location, e.g. "Los Angeles, CA"')
    max_range_miles = serializers.FloatField(required=False, min_value=1)
    mpg = serializers.FloatField(required=False, min_value=0.1)
    corridor_miles = serializers.FloatField(required=False, min_value=0.1)


class LatLngSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()


class FuelStopSerializer(serializers.Serializer):
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    mile_marker = serializers.FloatField()
    detour_miles = serializers.FloatField()
    highway = serializers.CharField(allow_blank=True)
    price_per_gallon = serializers.FloatField()
    gallons = serializers.FloatField()
    cost = serializers.FloatField()


class RouteGeometrySerializer(serializers.Serializer):
    type = serializers.CharField(default='LineString')
    coordinates = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2)
    )


class RouteResponseSerializer(serializers.Serializer):
    feasible = serializers.BooleanField()
    reason = serializers.CharField(required=False)
    start = LatLngSerializer()
    finish = LatLngSerializer()
    distance_miles = serializers.FloatField()
    duration_seconds = serializers.FloatField()
    route = RouteGeometrySerializer()
    fuel_stops = FuelStopSerializer(many=True)
    total_cost_usd = serializers.FloatField()
    total_gallons = serializers.FloatField()
    api_calls = serializers.IntegerField()
    elapsed_ms = serializers.FloatField()

from django.contrib import admin

from fuelroute.models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'state', 'price_per_gallon', 'highway', 'geocode_precision')
    list_filter = ('state', 'highway', 'geocode_precision')
    search_fields = ('name', 'city', 'address')

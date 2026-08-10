from django.contrib import admin

from fuelroute.models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'state', 'price_per_gallon', 'highway')
    list_filter = ('state', 'highway')
    search_fields = ('name', 'city', 'address')

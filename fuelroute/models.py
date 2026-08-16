from django.db import models


class FuelStation(models.Model):
    """A truckstop from the OPIS price list, geocoded to a city centroid.

    ``opis_id`` is not unique in the *source* CSV (568 IDs repeat, most
    with a different price quote for the same truckstop) -- see
    ``import_fuel_prices``, which merges those into a single row per
    ``opis_id`` at the cheapest listed price before import, so within
    this table it's a duplicate-free identifier in practice. Still not
    used as the primary key, since that's a property of the import step,
    not a guarantee of the field itself.
    """

    opis_id = models.IntegerField(db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    rack_id = models.CharField(max_length=20, blank=True)
    price_per_gallon = models.DecimalField(max_digits=6, decimal_places=4)

    latitude = models.FloatField()
    longitude = models.FloatField()

    # Highway ref parsed from `address` at import time (e.g. "I 80"), or
    # blank when the address doesn't embed one. Precomputing this avoids
    # re-parsing on every request.
    highway = models.CharField(max_length=20, blank=True, db_index=True)

    # How `latitude`/`longitude` were resolved: 'exit' when the address's
    # highway+exit matched a real motorway_junction coordinate (see
    # data/highway_exits.csv), 'city' when it fell back to the city
    # gazetteer centroid. Surfaced through the API so precision is
    # verifiable per station, not just claimed in aggregate.
    GEOCODE_PRECISION_CHOICES = [
        ('exit', 'Exit interchange (Overpass/OSM)'),
        ('city', 'City centroid (gazetteer)'),
    ]
    geocode_precision = models.CharField(
        max_length=10, choices=GEOCODE_PRECISION_CHOICES, default='city',
    )

    class Meta:
        indexes = [
            models.Index(fields=['latitude', 'longitude']),
        ]

    def __str__(self):
        return f'{self.name} ({self.city}, {self.state})'

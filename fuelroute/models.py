from django.db import models


class FuelStation(models.Model):
    """A truckstop from the OPIS price list, geocoded to a city centroid.

    ``opis_id`` is not unique in the source data (597 IDs repeat with a
    different price), so it is stored but not used as a primary key.
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

    class Meta:
        indexes = [
            models.Index(fields=['latitude', 'longitude']),
        ]

    def __str__(self):
        return f'{self.name} ({self.city}, {self.state})'

import sys

from django.apps import AppConfig
from django.db.utils import DatabaseError


class FuelrouteConfig(AppConfig):
    name = 'fuelroute'

    def ready(self):
        """Warm the in-process station snapshot before the first request.

        Only when actually serving (`runserver`) — other management
        commands (migrate, import_fuel_prices, test) run before the
        table necessarily has data, or want a clean cache themselves.
        A missing/empty table is swallowed rather than crashing
        startup: the snapshot just loads lazily on first use instead.
        """
        if len(sys.argv) < 2 or sys.argv[1] != 'runserver':
            return

        from fuelroute.services.stations import get_snapshot

        try:
            get_snapshot()
        except DatabaseError:
            pass

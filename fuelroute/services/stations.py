"""In-process snapshot of all fuel stations.

Loaded once per process and reused across requests, so the corridor
search touches no database I/O per request — only ~7.5k small rows,
comfortably cheap to hold in memory.
"""

from dataclasses import dataclass

from fuelroute.models import FuelStation

_snapshot: list['StationSnapshot'] | None = None


@dataclass(frozen=True)
class StationSnapshot:
    id: int
    name: str
    address: str
    city: str
    state: str
    price_per_gallon: float
    latitude: float
    longitude: float
    highway: str


def get_snapshot() -> list[StationSnapshot]:
    """Return the cached in-process list of all stations, loading it on first use."""
    global _snapshot
    if _snapshot is None:
        _snapshot = [
            StationSnapshot(
                id=station.id,
                name=station.name,
                address=station.address,
                city=station.city,
                state=station.state,
                price_per_gallon=float(station.price_per_gallon),
                latitude=station.latitude,
                longitude=station.longitude,
                highway=station.highway,
            )
            for station in FuelStation.objects.all()
        ]
    return _snapshot


def clear_snapshot() -> None:
    """Drop the cached snapshot so the next call reloads from the database.

    Needed after re-importing station data, and between test cases.
    """
    global _snapshot
    _snapshot = None

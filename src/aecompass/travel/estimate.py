"""Travel time from a starting point to each A&E.

v1 is a **rough estimate from straight-line distance**, not a routed journey. It exists so the
recommender has something reasonable to add to the wait, and it sits behind one small interface
(`TravelTime`) so that v2 can swap in real public-transport routing without touching anything else.

    minutes = fixed overhead (walking, waiting)
            + straight-line km x detour factor / average speed
            + a penalty when the trip crosses the harbour or the Lantau link

Trips that need the Cheung Chau ferry are **not offered at all**: St John Hospital is only suggested to
someone already on Cheung Chau, and nobody on Cheung Chau is sent off the island. A ferry has a timetable
and does not run all night, and this model knows neither.

The numbers in `Params` are first guesses, not fitted values. `evals/reports/travel_spot_checks.md`
records how far they are from a real journey planner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aecompass.ref.hospitals import distance_km

Point = tuple[float, float]  # (latitude, longitude)

# Which side of the water each A&E is on. Everything not listed is in Kowloon or the New Territories.
HOSPITAL_REGION = {
    "Pamela Youde Nethersole Eastern Hospital": "hk_island",
    "Ruttonjee Hospital": "hk_island",
    "Queen Mary Hospital": "hk_island",
    "North Lantau Hospital": "lantau",
    "St John Hospital": "cheung_chau",
}
MAINLAND = "kowloon_nt"


def region_of(point: Point) -> str:
    """Very rough region from bounding boxes. Good enough to decide whether a trip crosses water.

    Known gaps: Lamma, Peng Chau and other small islands are not handled.
    """
    lat, lon = point
    if 22.19 <= lat <= 22.225 and 114.01 <= lon <= 114.045:
        return "cheung_chau"
    if lat < 22.34 and lon < 114.07:
        return "lantau"
    if lat < 22.2925 and 114.11 <= lon <= 114.262:
        return "hk_island"
    return MAINLAND


@dataclass(frozen=True)
class Params:
    overhead_min: float = 10.0  # walking at both ends plus waiting for the first vehicle
    detour_factor: float = 1.4  # roads and rail lines are longer than the straight line
    speed_kmh: float = 20.0  # average door-to-door public-transport speed once moving
    harbour_min: float = 10.0  # Hong Kong Island <-> Kowloon / New Territories
    lantau_min: float = 10.0  # Lantau <-> anywhere else (one road and rail link)
    spread: float = 0.25  # the range shown is +/- this share of the estimate
    scale: float = 1.0  # multiplies the whole estimate; used to test how much results depend on it


@dataclass(frozen=True)
class TravelEstimate:
    minutes: float
    low: float
    high: float
    method: str


class TravelTime(Protocol):
    """Anything that can say how long a trip takes. The recommender only knows about this."""

    def estimate(self, origin: Point, hospital: str, depart: datetime | None = None) -> TravelEstimate | None:
        """None means "this trip is not offered"."""
        ...


class DistanceTravelTime:
    """The v1 estimate. Ignores time of day: `depart` is accepted so routed versions can use it."""

    method = "straight-line estimate (approximate)"

    def __init__(self, hospitals: dict[str, Point], params: Params = Params()):
        self.hospitals = hospitals
        self.params = params

    def _crossing_min(self, a: str, b: str) -> float:
        if a == b:
            return 0.0
        p, regions = self.params, {a, b}
        if "lantau" in regions:
            return p.lantau_min + (p.harbour_min if "hk_island" in regions else 0.0)
        return p.harbour_min  # hk_island <-> kowloon_nt

    def estimate(self, origin: Point, hospital: str, depart: datetime | None = None) -> TravelEstimate | None:
        p = self.params
        start, end = region_of(origin), HOSPITAL_REGION.get(hospital, MAINLAND)
        if start != end and "cheung_chau" in (start, end):
            return None  # ferry-only trip: not offered
        km = distance_km(origin, self.hospitals[hospital])
        minutes = p.overhead_min + km * p.detour_factor / p.speed_kmh * 60 + self._crossing_min(start, end)
        minutes *= p.scale
        return TravelEstimate(minutes, minutes * (1 - p.spread), minutes * (1 + p.spread), self.method)

    def to_all(self, origin: Point, depart: datetime | None = None) -> dict[str, TravelEstimate]:
        trips = {name: self.estimate(origin, name, depart) for name in self.hospitals}
        return {name: trip for name, trip in trips.items() if trip is not None}

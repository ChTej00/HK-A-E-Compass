"""Travel time from a starting point to each A&E.

v1 is a **rough estimate from straight-line distance**, not a routed journey. It exists so the
recommender has something reasonable to add to the wait, and it sits behind one small interface
(`TravelTime`) so that v2 can swap in real public-transport routing without touching anything else.

    minutes = base (walking, waiting) + coefficient x square root of the straight-line km
            + a penalty when the trip crosses the harbour

Why a square root: longer trips use faster transport (rail, expressway buses), so time grows more slowly
than distance. A first version assumed one constant speed and was 25 to 70 minutes too slow on trips over
15 km (see DECISIONS.md D20).

Trips that need the Cheung Chau ferry are **not offered at all**: St John Hospital is only suggested to
someone already on Cheung Chau, and nobody on Cheung Chau is sent off the island. A ferry has a timetable
and does not run all night, and this model knows neither.

The three numbers in `Params` were fitted to 10 journey-planner trips and then checked on 10 different
trips; `evals/reports/travel_spot_checks.md` has both.
"""

from __future__ import annotations

import math
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
    base_min: float = 8.0  # walking at both ends plus waiting for the first vehicle
    sqrt_km_min: float = 9.8  # minutes per square-root kilometre of straight-line distance
    harbour_min: float = 8.0  # Hong Kong Island <-> Kowloon / New Territories / Lantau
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
        return self.params.harbour_min if "hk_island" in {a, b} else 0.0

    def estimate(self, origin: Point, hospital: str, depart: datetime | None = None) -> TravelEstimate | None:
        p = self.params
        start, end = region_of(origin), HOSPITAL_REGION.get(hospital, MAINLAND)
        if start != end and "cheung_chau" in (start, end):
            return None  # ferry-only trip: not offered
        km = distance_km(origin, self.hospitals[hospital])
        minutes = p.base_min + p.sqrt_km_min * math.sqrt(km) + self._crossing_min(start, end)
        minutes *= p.scale
        return TravelEstimate(minutes, minutes * (1 - p.spread), minutes * (1 + p.spread), self.method)

    def to_all(self, origin: Point, depart: datetime | None = None) -> dict[str, TravelEstimate]:
        trips = {name: self.estimate(origin, name, depart) for name in self.hospitals}
        return {name: trip for name, trip in trips.items() if trip is not None}

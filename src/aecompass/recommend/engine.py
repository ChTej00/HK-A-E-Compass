"""The recommender: total time to be seen = travel time + predicted wait when you arrive.

The forecaster gives the wait 1, 2 and 3 hours from now. A trip rarely takes exactly an hour, so the
wait at the arrival time is read off a straight line between the known points:

    now (the published value)  ->  +1h forecast  ->  +2h forecast  ->  +3h forecast

The uncertainty band is zero right now (the current value is known) and grows with the square root of
time over the first hour, the way the error of a wandering series usually grows. That shape is an
assumption; `evals/reports/regret.md` reports how often the band actually contained the truth.

Everything here is a pure function of its inputs: no network, no clock, no model loading. The live app
and the hindsight evaluation call the same code.

The waits are the Hospital Authority's published estimates, and this ranks options. It never says
whether someone needs care.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

HORIZON_MIN = np.array([0.0, 60.0, 120.0, 180.0])
CLOSE_CALL_MIN = 15.0  # options within this many minutes of the best are "about as good"


def wait_at_arrival(travel_min, now, pred, lo, hi):
    """Predicted wait, and its band, `travel_min` minutes from now.

    `pred`, `lo`, `hi` hold the +1h, +2h, +3h values on their last axis; `now` is the current value.
    Works on single numbers or on arrays of any matching shape. Trips longer than 3 hours use +3h.
    """
    travel = np.clip(np.asarray(travel_min, dtype="float64"), 0, HORIZON_MIN[-1])
    now = np.asarray(now, dtype="float64")
    pred, lo, hi = (np.asarray(a, dtype="float64") for a in (pred, lo, hi))

    def along(values_at_hours, start):
        points = np.concatenate([np.broadcast_to(start, values_at_hours.shape[:-1])[..., None], values_at_hours], axis=-1)
        segment = np.clip(np.floor(travel / 60).astype(int), 0, 2)
        left = np.take_along_axis(points, segment[..., None], axis=-1)[..., 0]
        right = np.take_along_axis(points, segment[..., None] + 1, axis=-1)[..., 0]
        return left, right, travel / 60 - segment

    left, right, share = along(pred, now)
    point = left + (right - left) * share
    out = [point]
    for bound in (lo, hi):
        left, right, share = along(bound - pred, np.zeros_like(now))  # distance of the bound from the forecast
        first_hour = travel < 60
        weight = np.where(first_hour, np.sqrt(np.clip(travel / 60, 0, 1)), share)
        offset = np.where(first_hour, right * weight, left + (right - left) * weight)
        out.append(np.clip(point + offset, 0, None))
    return tuple(out)


@dataclass(frozen=True)
class Forecast:
    """One hospital's outlook: the published wait now and the forecasts 1, 2 and 3 hours ahead (minutes)."""

    now: float
    pred: tuple[float, float, float]
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]


@dataclass(frozen=True)
class Option:
    hospital: str
    travel_min: float
    wait_min: float
    wait_low: float
    wait_high: float
    total_min: float
    total_low: float
    total_high: float
    travel_method: str


def recommend(forecasts: Mapping[str, Forecast], travel: Mapping[str, object]) -> list[Option]:
    """Every hospital that has both a forecast and a travel estimate, soonest total first.

    `travel` maps hospital -> TravelEstimate (minutes, low, high, method).
    """
    options = []
    for hospital, f in forecasts.items():
        trip = travel.get(hospital)
        if trip is None or np.isnan(f.now):
            continue
        wait, low, high = (float(v) for v in wait_at_arrival(trip.minutes, f.now, f.pred, f.lo, f.hi))
        options.append(Option(hospital, trip.minutes, wait, low, high,
                              trip.minutes + wait, trip.low + low, trip.high + high, trip.method))
    return sorted(options, key=lambda o: o.total_min)


def about_as_good(options: list[Option], within_min: float = CLOSE_CALL_MIN) -> list[Option]:
    """The best option plus any others whose total is within `within_min` of it."""
    return [o for o in options if o.total_min - options[0].total_min <= within_min] if options else []

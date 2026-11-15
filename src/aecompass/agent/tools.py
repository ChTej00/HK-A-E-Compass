"""The tools the AI model can call, and the code that runs them.

A "tool" is a function we describe to the model (name, purpose, inputs). The model cannot run anything
itself: it replies "please call `recommend` with place='Mong Kok'", our code runs the real function, and
we send the result back for the model to put into words. So every number in an answer comes from here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd

from aecompass.collect import archive
from aecompass.forecast.dataset import TARGETS, load_clean
from aecompass.forecast.serve import Models, forecast_latest, load_models
from aecompass.geo.geocode import geocode
from aecompass.recommend.engine import Forecast, about_as_good, recommend
from aecompass.ref import holidays, hospitals
from aecompass.travel.estimate import DistanceTravelTime

NON_URGENT, URGENT = "t45_p50_min", "t3_p50_min"
CAVEAT = (
    "Waits are the Hospital Authority's published estimates (median, minutes), not measured waits. "
    "Forecast ranges are 80% intervals. Travel times are rough straight-line estimates."
)

# What the model is told about each tool. `strict` makes the API guarantee the inputs match the schema.
TOOL_SPECS = [
    {
        "name": "recommend",
        "description": (
            "Rank public A&E departments for a NON-urgent patient starting from a place in Hong Kong, by "
            "estimated travel time plus the forecast wait at the arrival time. Returns the top options with "
            "ranges. Use this whenever the user wants to know where to go or which A&E is quickest."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "place": {
                    "type": "string",
                    "description": "A Hong Kong building, estate, station or address, as the user gave it.",
                }
            },
            "required": ["place"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_current_waits",
        "description": (
            "The latest published waiting times at every public A&E, for non-urgent (triage IV & V) and "
            "urgent (triage III) patients."
        ),
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "forecast_wait",
        "description": "The published wait now and the forecast 1, 2 and 3 hours ahead, with ranges, for one A&E.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "hospital": {"type": "string", "description": "Hospital name or part of it, e.g. 'Queen Mary'."}
            },
            "required": ["hospital"],
            "additionalProperties": False,
        },
    },
]


@dataclass
class Toolbox:
    """Holds the data the tools need, loaded once."""

    clean: pd.DataFrame
    models: Models
    coords: dict[str, tuple[float, float]]
    holiday_map: dict
    _cache: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Toolbox":
        return cls(load_clean(), load_models(), hospitals.load(), holidays.load())

    def _forecasts(self, target: str) -> tuple[pd.Timestamp, dict[str, Forecast]]:
        if target not in self._cache:
            self._cache[target] = forecast_latest(self.clean, self.models, target, self.holiday_map)
        return self._cache[target]

    def _stamp(self, as_of: pd.Timestamp) -> dict:
        age = (archive.now_hkt() - as_of.to_pydatetime()).total_seconds() / 60
        out = {"data_time_hkt": f"{as_of:%a %d %b %Y %H:%M}", "data_age_minutes": round(age), "note": CAVEAT}
        if age > 45:
            out["warning"] = "This data is old. Tell the user the waits may have changed."
        return out

    def recommend(self, place: str) -> dict:
        matches = geocode(place)
        if not matches:
            raise ValueError(
                f"Could not find a place called {place!r}. Ask the user for a building, estate or station name."
            )
        start = matches[0]
        as_of, forecasts = self._forecasts(NON_URGENT)
        options = recommend(forecasts, DistanceTravelTime(self.coords).to_all(start.point))
        close = about_as_good(options)
        r = lambda v: round(float(v))
        return {
            "start_matched_to": f"{start.matched_name} ({start.district})",
            **self._stamp(as_of),
            "options_soonest_first": [
                {
                    "hospital": o.hospital,
                    "travel_min": r(o.travel_min),
                    "wait_on_arrival_min": r(o.wait_min),
                    "wait_range_min": [r(o.wait_low), r(o.wait_high)],
                    "total_min": r(o.total_min),
                    "total_range_min": [r(o.total_low), r(o.total_high)],
                }
                for o in options[:5]
            ],
            "too_close_to_call": [o.hospital for o in close] if len(close) > 1 else [],
        }

    def get_current_waits(self) -> dict:
        as_of, non_urgent = self._forecasts(NON_URGENT)
        _, urgent = self._forecasts(URGENT)
        return {
            **self._stamp(as_of),
            "waits_min": {
                name: {
                    "non_urgent_triage_4_5": round(f.now),
                    "urgent_triage_3": round(urgent[name].now) if name in urgent else None,
                }
                for name, f in sorted(non_urgent.items())
            },
        }

    def forecast_wait(self, hospital: str) -> dict:
        as_of, forecasts = self._forecasts(NON_URGENT)
        found = [name for name in forecasts if hospital.lower().replace(".", "") in name.lower()]
        if len(found) != 1:
            raise ValueError(
                f"{hospital!r} matched {len(found)} hospitals. Valid names: {', '.join(sorted(forecasts))}."
            )
        f = forecasts[found[0]]
        return {
            "hospital": found[0],
            "category": TARGETS[NON_URGENT],
            **self._stamp(as_of),
            "now_min": round(f.now),
            "forecast": [
                {"hours_ahead": h, "wait_min": round(f.pred[h - 1]), "range_min": [round(f.lo[h - 1]), round(f.hi[h - 1])]}
                for h in (1, 2, 3)
            ],
        }

    def run(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Run one tool call. Returns (text for the model, is_error). Errors go back as text, not exceptions,
        so the model can tell the user what went wrong."""
        handlers = {
            "recommend": self.recommend,
            "get_current_waits": self.get_current_waits,
            "forecast_wait": self.forecast_wait,
        }
        try:
            return json.dumps(handlers[name](**arguments), ensure_ascii=False), False
        except Exception as error:  # noqa: BLE001 - any failure must reach the model as an error result
            return f"Error: {error}", True

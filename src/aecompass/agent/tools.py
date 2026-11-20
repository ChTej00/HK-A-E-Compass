"""The tools the AI model can call, and the code that runs them.

A "tool" is a function we describe to the model (name, purpose, inputs). The model cannot run anything
itself: it replies "please call `recommend` with place='Mong Kok'", our code runs the real function, and
we send the result back for the model to put into words. So every number in an answer comes from here.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import pandas as pd

from aecompass.collect import archive
from aecompass.forecast.dataset import TARGETS, load_clean
from aecompass.forecast.serve import Models, forecast_latest, load_models
from aecompass.geo.geocode import geocode
from aecompass.kb.search import EmbeddingSearch, KeywordSearch, load_chunks
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
        "name": "search_triage_guidance",
        "description": (
            "Search official Hong Kong Government and Hospital Authority press releases about how A&E works: "
            "triage categories and their waiting-time targets, the A&E fee, who is exempt, refunds, fee waivers, "
            "and where people can go other than A&E (clinics, family doctors). Returns passages with their "
            "source. Use this for any question about rules, fees or how the system works. It contains no "
            "live waiting times and no medical advice."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look up, in English, as a short question or keywords.",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
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


OLD_FEES_WARNING = (
    "Published before the A&E fee change of 1 January 2026. Any fee or refund amount in this passage is "
    "out of date. Do not give it as the current amount."
)


@dataclass
class Toolbox:
    """Holds the data the tools need, loaded once."""

    clean: pd.DataFrame
    models: Models
    coords: dict[str, tuple[float, float]]
    holiday_map: dict
    searcher: object = None  # anything with .search(query, k); see kb/search.py
    _cache: dict = field(default_factory=dict)

    @classmethod
    def load(cls, with_search: bool = True) -> "Toolbox":
        """`with_search=False` skips the guidance search, which only the chat uses (the hosted demo has none)."""
        searcher = None
        if with_search:
            chunks = load_chunks()
            embed_model = os.environ.get("AECOMPASS_EMBED_MODEL")
            # Embedding search alone beat both keyword and hybrid search on the retrieval eval (retrieval.md).
            searcher = EmbeddingSearch(chunks, embed_model) if embed_model else KeywordSearch(chunks)
        return cls(load_clean(), load_models(), hospitals.load(), holidays.load(), searcher)

    def search_triage_guidance(self, query: str) -> dict:
        hits = self.searcher.search(query, 4)
        if not hits:
            return {"passages": [], "note": "Nothing relevant was found in the official sources. Say you do not "
                                            "have official information on this; do not answer from memory."}
        # A&E fees changed on 1 Jan 2026. Older sources are still right about triage, but any fee or refund
        # they mention is out of date, so they are listed last and labelled.
        hits = sorted(hits, key=lambda h: h.source.old_fees)  # stable: keeps the search order within each group
        passages = []
        for h in hits:
            passage = {"source_title": h.source.title, "publisher": h.source.publisher, "published": h.source.date,
                       "url": h.source.url, "text": h.text}
            if h.source.old_fees:
                passage["warning"] = OLD_FEES_WARNING
            passages.append(passage)
        return {
            "passages": passages,
            "note": "Answer only from these passages. Name the source title and give its URL for each fact you "
                    "use. If the passages do not answer the question, say so. Rules and fees can change after "
                    "the publication date. For any fee or refund amount, use only passages without a warning.",
        }

    def _forecasts(self, target: str) -> tuple[pd.Timestamp, dict[str, Forecast]]:
        # Read the cache once: the web server may swap in a new one (reload) while a request is running.
        cache = self._cache
        if target not in cache:
            cache[target] = forecast_latest(self.clean, self.models, target, self.holiday_map)
        return cache[target]

    def reload(self, clean: pd.DataFrame) -> None:
        """Use newer published waits. Forecasts are recomputed on the next request."""
        self.clean, self._cache = clean, {}

    def data_time(self) -> pd.Timestamp:
        return self._forecasts(NON_URGENT)[0]

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
            "start_point": [round(start.lat, 5), round(start.lon, 5)],
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

    def board(self) -> dict:
        """Every A&E: published waits now and the forecast for the next three hours. For the web page, not the model."""
        as_of, non_urgent = self._forecasts(NON_URGENT)
        _, urgent = self._forecasts(URGENT)
        rows = []
        for name, f in sorted(non_urgent.items()):
            lat, lon = self.coords.get(name, (None, None))
            rows.append({
                "hospital": name,
                "lat": lat,
                "lon": lon,
                "urgent_triage_3_now_min": round(urgent[name].now) if name in urgent else None,
                "now_min": round(f.now),
                "forecast": [
                    {"hours_ahead": h, "wait_min": round(f.pred[h - 1]), "range_min": [round(f.lo[h - 1]), round(f.hi[h - 1])]}
                    for h in (1, 2, 3)
                ],
            })
        return {**self._stamp(as_of), "hospitals": rows, "no_current_wait": sorted(set(self.coords) - set(non_urgent))}

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
            "search_triage_guidance": self.search_triage_guidance,
        }
        try:
            return json.dumps(handlers[name](**arguments), ensure_ascii=False), False
        except Exception as error:  # noqa: BLE001 - any failure must reach the model as an error result
            return f"Error: {error}", True

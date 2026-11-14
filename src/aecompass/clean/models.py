"""Pydantic models for the A&E feed: what HA publishes (raw) and what we keep (clean).

Unit rule: **everything is stored in minutes.** HA publishes triage III in minutes and triage IV/V in
hours ("2.5 hours"). Mixing those is the easiest mistake to make in this project, so the conversion
happens exactly once, here, and every column name ends in `_min`.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..collect.archive import HKT, TS_FORMAT

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(minute|minutes|hour|hours)\s*$", re.IGNORECASE)
MULTI_RESUS_TEXT = "Managing multiple resuscitation cases"
UPDATE_TIME_FORMAT = "%d/%m/%Y %I:%M%p"  # e.g. "13/11/2026 10:45PM"
MAX_PLAUSIBLE_MIN = 48 * 60


def parse_duration_min(text: str | None) -> float | None:
    """'24 minutes' -> 24.0, '2.5 hours' -> 150.0, '1 hour' -> 60.0. Anything else -> None."""
    if not isinstance(text, str):
        return None
    m = _DURATION.match(text)
    if not m:
        return None
    value = float(m.group(1))
    minutes = value * 60 if m.group(2).lower().startswith("hour") else value
    return minutes if 0 <= minutes <= MAX_PLAUSIBLE_MIN else None


def parse_flag(text: str | None) -> bool | None:
    """'Y' -> True, 'N' -> False, 'N/A' or anything else -> None (unknown)."""
    return {"Y": True, "N": False}.get((text or "").strip().upper())


class RawHospital(BaseModel):
    """One hospital's entry exactly as published. A missing field is an error: the feed has changed."""

    model_config = ConfigDict(extra="allow")  # a new field should not break collection, only be noticed

    hospName: str
    t1wt: str
    manageT1case: str
    t2wt: str
    manageT2case: str
    t3p50: str
    t3p95: str
    t45p50: str
    t45p95: str


class RawSnapshot(BaseModel):
    waitTime: list[RawHospital] = Field(min_length=1)
    updateTime: str


class CleanRow(BaseModel):
    """One hospital at one point in time. All waits in minutes; None means 'not a usable number'."""

    observed_at: datetime  # the archive's 15-minute slot: when this value became visible to us
    update_time: datetime  # HA's own "last updated" stamp (normally 15 minutes earlier)
    hospital: str
    t3_p50_min: float | None  # triage III (urgent): half of waiting patients seen within this
    t3_p95_min: float | None  # triage III: 95% seen within this
    t45_p50_min: float | None  # triage IV & V (semi-/non-urgent): half seen within this
    t45_p95_min: float | None
    multi_resus: bool  # HA shows "Managing multiple resuscitation cases" instead of triage I/II text
    managing_t1: bool | None  # manageT1case flag; None when HA publishes "N/A"
    managing_t2: bool | None


def clean_snapshot(ts: str, body: str) -> list[CleanRow]:
    """Validate one raw snapshot and return one clean row per hospital."""
    snap = RawSnapshot.model_validate_json(body)
    observed_at = datetime.strptime(ts, TS_FORMAT).replace(tzinfo=HKT)
    update_time = datetime.strptime(snap.updateTime.strip(), UPDATE_TIME_FORMAT).replace(tzinfo=HKT)
    return [
        CleanRow(
            observed_at=observed_at,
            update_time=update_time,
            hospital=h.hospName.strip(),
            t3_p50_min=parse_duration_min(h.t3p50),
            t3_p95_min=parse_duration_min(h.t3p95),
            t45_p50_min=parse_duration_min(h.t45p50),
            t45_p95_min=parse_duration_min(h.t45p95),
            multi_resus=MULTI_RESUS_TEXT.lower() in (h.t1wt + " " + h.t2wt).lower(),
            managing_t1=parse_flag(h.manageT1case),
            managing_t2=parse_flag(h.manageT2case),
        )
        for h in snap.waitTime
    ]

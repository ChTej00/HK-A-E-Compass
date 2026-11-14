import json

import pytest
from pydantic import ValidationError

from aecompass.clean.models import clean_snapshot, parse_duration_min, parse_flag


def hospital(**overrides):
    base = {
        "hospName": "Queen Mary Hospital",
        "t1wt": "0 minute", "manageT1case": "N",
        "t2wt": "less than 15 minutes", "manageT2case": "Y",
        "t3p50": "32 minutes", "t3p95": "58 minutes",
        "t45p50": "2.5 hours", "t45p95": "6 hours",
    }
    return base | overrides


def snapshot(*hospitals, update_time="13/11/2026 10:45PM"):
    return json.dumps({"waitTime": list(hospitals) or [hospital()], "updateTime": update_time})


@pytest.mark.parametrize(
    "text,expected",
    [
        ("24 minutes", 24), ("1 minute", 1), ("0 minute", 0),
        ("2.5 hours", 150), ("1 hour", 60), ("4 hour", 240), ("0.5 hours", 30),
        ("N/A", None), ("", None), (None, None), ("Around 2 hours", None), ("9999 hours", None),
    ],
)
def test_parse_duration_converts_everything_to_minutes(text, expected):
    assert parse_duration_min(text) == expected


def test_parse_flag():
    assert parse_flag("Y") is True and parse_flag("N") is False and parse_flag("N/A") is None


def test_clean_snapshot_units_and_times():
    (row,) = clean_snapshot("20261113-2300", snapshot())
    assert row.hospital == "Queen Mary Hospital"
    assert row.t3_p50_min == 32 and row.t45_p50_min == 150 and row.t45_p95_min == 360
    assert row.observed_at.isoformat() == "2026-11-13T23:00:00+08:00"
    assert row.update_time.isoformat() == "2026-11-13T22:45:00+08:00"
    assert row.multi_resus is False and row.managing_t1 is False and row.managing_t2 is True


def test_midnight_and_noon_parse_correctly():
    (a,) = clean_snapshot("20261114-0015", snapshot(update_time="14/11/2026 12:00AM"))
    (b,) = clean_snapshot("20261114-1215", snapshot(update_time="14/11/2026 12:00PM"))
    assert a.update_time.hour == 0 and b.update_time.hour == 12


def test_multiple_resuscitation_cases_is_flagged_not_dropped():
    h = hospital(
        t1wt="Managing multiple resuscitation cases", t2wt="Managing multiple resuscitation cases",
        manageT1case="N/A", manageT2case="N/A",
    )
    (row,) = clean_snapshot("20261113-2300", snapshot(h))
    assert row.multi_resus is True and row.managing_t1 is None
    assert row.t45_p50_min == 150  # the non-urgent wait is still published and kept


def test_unparseable_wait_becomes_none_not_a_wrong_number():
    (row,) = clean_snapshot("20261113-2300", snapshot(hospital(t45p50="N/A")))
    assert row.t45_p50_min is None and row.t3_p50_min == 32


def test_missing_field_is_rejected():
    broken = hospital()
    del broken["t45p50"]
    with pytest.raises(ValidationError):
        clean_snapshot("20261113-2300", snapshot(broken))

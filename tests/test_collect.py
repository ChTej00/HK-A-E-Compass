from datetime import date, datetime

from aecompass.collect import aed, archive
from aecompass.collect.store import RawStore

GOOD = '{"waitTime":[{"hospName":"Queen Mary Hospital","t45p50":"3 hours"}],"updateTime":"14/11/2026 5:15AM"}'


def test_slots_cover_a_full_day():
    slots = archive.slots_for_day(date(2026, 11, 14))
    assert len(slots) == 96
    assert slots[0] == "20261114-0000" and slots[-1] == "20261114-2345"


def test_slots_stop_at_until():
    until = datetime(2026, 11, 14, 5, 20, tzinfo=archive.HKT)
    assert archive.slots_for_day(date(2026, 11, 14), until=until)[-1] == "20261114-0515"


def test_store_ignores_duplicates(tmp_path):
    store = RawStore(tmp_path, "aed_raw")
    assert store.append("20261114-0530", GOOD) is True
    assert store.append("20261114-0530", GOOD) is False
    assert len(store.path("2026-11").read_text(encoding="utf-8").splitlines()) == 1


def test_store_resumes_from_disk_and_splits_by_month(tmp_path):
    first = RawStore(tmp_path, "aed_raw")
    first.append("20261031-2345", GOOD)
    first.append("20261101-0000", GOOD)
    second = RawStore(tmp_path, "aed_raw")  # a fresh process
    assert second.has("20261031-2345") and second.has("20261101-0000")
    assert not second.has("20261101-0015")
    assert second.latest_ts() == "20261101-0000"


def test_store_repairs_half_written_line(tmp_path):
    store = RawStore(tmp_path, "aed_raw")
    store.append("20261114-0500", GOOD)
    with store.path("2026-11").open("a", encoding="utf-8") as f:
        f.write('{"ts": "20261114-0515", "body": "{\\"waitTi')  # killed mid-write
    again = RawStore(tmp_path, "aed_raw")
    assert not again.has("20261114-0515")
    assert again.append("20261114-0515", GOOD) is True
    assert RawStore(tmp_path, "aed_raw").existing("2026-11") == {"20261114-0500", "20261114-0515"}


def test_looks_valid_rejects_error_pages():
    assert aed.looks_valid(GOOD)
    assert not aed.looks_valid("<html>Service unavailable</html>")
    assert not aed.looks_valid('{"message": "NOT FOUND"}')
    assert not aed.looks_valid('{"waitTime": []}')


def test_months_between_crosses_year_end():
    assert aed.months_between(date(2025, 11, 20), date(2026, 2, 3)) == ["2025-11", "2025-12", "2026-01", "2026-02"]

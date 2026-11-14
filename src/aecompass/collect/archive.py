"""Client for the data.gov.hk Historical Archive API.

data.gov.hk saves a copy of selected open-data files every time they change. For the A&E waiting-time
file that means one snapshot every 15 minutes. Two endpoints matter:

- get-file: download the snapshot for one exact timestamp (works for today too; 404 if it doesn't exist)
- list-file-versions: which timestamps exist between two dates. Found to be incomplete, so not relied on.

Timestamps are Hong Kong time, formatted "YYYYMMDD-HHMM", e.g. "20261114-0530".
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

BASE = "https://api.data.gov.hk/v1/historical-archive"
AED_URL = "https://www.ha.org.hk/opendata/aed/aedwtdata2-en.json"
HKT = ZoneInfo("Asia/Hong_Kong")
TS_FORMAT = "%Y%m%d-%H%M"

# The numeric feed (minutes / hours as numbers) starts here. Earlier snapshots use coarse text.
FIRST_NUMERIC_DAY = date(2025, 10, 14)


def now_hkt() -> datetime:
    return datetime.now(HKT)


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, TS_FORMAT).replace(tzinfo=HKT)


def slots_for_day(day: date, until: datetime | None = None) -> list[str]:
    """All 15-minute timestamps of `day`, optionally stopping at `until` (inclusive)."""
    start = datetime(day.year, day.month, day.day, tzinfo=HKT)
    out = []
    for i in range(96):
        t = start + timedelta(minutes=15 * i)
        if until is not None and t > until:
            break
        out.append(t.strftime(TS_FORMAT))
    return out


def _get(client: httpx.Client, path: str, params: dict, attempts: int = 5) -> httpx.Response:
    """GET with retries on network errors, rate limits and server errors."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            r = client.get(f"{BASE}/{path}", params=params)
            if r.status_code < 500 and r.status_code != 429:
                return r
            last = httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
        except httpx.TransportError as e:
            last = e
        time.sleep(2**i)
    raise RuntimeError(f"archive API failed after {attempts} attempts: {path} {params}") from last


def list_versions(client: httpx.Client, url: str, day: date) -> list[str]:
    """Snapshot timestamps the archive *lists* for one past day. The API rejects today and future dates.

    For diagnostics only. The listing can be empty for days whose files exist, so the collector does not
    rely on it; it requests every slot with get_file instead.
    """
    d = day.strftime("%Y%m%d")
    r = _get(client, "list-file-versions", {"url": url, "start": d, "end": d})
    r.raise_for_status()
    return r.json()["timestamps"]


def get_file(client: httpx.Client, url: str, ts: str) -> str | None:
    """Raw text of one snapshot, or None if the archive has no snapshot at that timestamp."""
    r = _get(client, "get-file", {"url": url, "time": ts})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.text


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=30,
        follow_redirects=True,  # get-file answers with a redirect to the stored copy
        headers={"User-Agent": "aecompass-collector"},
    )

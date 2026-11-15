"""Hong Kong public holidays from the government's 1823 calendar.

    python -m aecompass.ref.holidays      # download and cache to data/ref/holidays.json
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import httpx

URL = "https://www.1823.gov.hk/common/ical/en.json"
CACHE = Path("data/ref/holidays.json")


def fetch(cache: Path = CACHE) -> Path:
    r = httpx.get(URL, timeout=30, follow_redirects=True)
    r.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(r.content)
    return cache


def load(cache: Path = CACHE) -> dict[date, str]:
    """{date: holiday name}. The file starts with a byte-order mark, hence 'utf-8-sig'."""
    if not cache.exists():
        fetch(cache)
    data = json.loads(cache.read_text(encoding="utf-8-sig"))
    out = {}
    for event in data["vcalendar"][0]["vevent"]:
        day = datetime.strptime(event["dtstart"][0], "%Y%m%d").date()
        out[day] = event["summary"]
    return out


if __name__ == "__main__":
    fetch()
    days = load()
    print(f"{len(days)} holidays, {min(days)} to {max(days)}")

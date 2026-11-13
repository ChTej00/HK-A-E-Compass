"""Collect A&E waiting-time snapshots from the data.gov.hk archive.

The same command does the one-off history download and the hourly top-up, because it is *idempotent*:
running it twice gives the same result as running it once. It only fetches snapshots it doesn't have.

    python -m aecompass.collect.aed --start 2025-10-14        # full history, resumable
    python -m aecompass.collect.aed --days-back 3             # hourly top-up, heals recent gaps
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import httpx

from . import archive
from .store import RawStore

DEFAULT_ROOT = Path("data/raw/aed")
PREFIX = "aed_raw"


def looks_valid(body: str) -> bool:
    """Reject error pages and truncated downloads before they reach storage."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and isinstance(data.get("waitTime"), list) and len(data["waitTime"]) > 0


def wanted_timestamps(client: httpx.Client, day: date, today: date) -> list[str]:
    """Past days: ask the archive what exists. Today: the listing isn't available yet, so try every slot so far."""
    if day < today:
        return archive.list_versions(client, archive.AED_URL, day)
    return archive.slots_for_day(day, until=archive.now_hkt())


def collect(start: date, end: date, store: RawStore, workers: int = 4, verbose: bool = True) -> dict:
    today = archive.now_hkt().date()
    end = min(end, today)
    totals = {"stored": 0, "already_had": 0, "not_in_archive": 0, "invalid": 0}

    with archive.make_client() as client, ThreadPoolExecutor(max_workers=workers) as pool:

        def fetch(ts: str) -> tuple[str, str | None]:
            return ts, archive.get_file(client, archive.AED_URL, ts)

        day = start
        while day <= end:
            wanted = wanted_timestamps(client, day, today)
            missing = [ts for ts in wanted if not store.has(ts)]
            totals["already_had"] += len(wanted) - len(missing)
            stored = 0
            for ts, body in pool.map(fetch, missing):
                if body is None:
                    totals["not_in_archive"] += 1
                elif not looks_valid(body):
                    totals["invalid"] += 1
                elif store.append(ts, body):
                    stored += 1
            totals["stored"] += stored
            if verbose and (stored or day == end):
                print(f"{day}  stored {stored:3d}  (had {len(wanted) - len(missing)})", flush=True)
            day += timedelta(days=1)
    return totals


def months_between(start: date, end: date) -> list[str]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(f"{d.year}-{d.month:02d}")
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=date.fromisoformat, help="first day, YYYY-MM-DD")
    p.add_argument("--end", type=date.fromisoformat, help="last day, YYYY-MM-DD (default: today)")
    p.add_argument("--days-back", type=int, help="alternative to --start: begin this many days before today")
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--workers", type=int, default=4, help="parallel downloads; keep small to be polite")
    p.add_argument("--print-months", action="store_true", help="only print the months the range touches")
    args = p.parse_args(argv)

    today = archive.now_hkt().date()
    end = args.end or today
    if args.days_back is not None:
        start = today - timedelta(days=args.days_back)
    elif args.start:
        start = args.start
    else:
        p.error("give --start or --days-back")
    start = max(start, archive.FIRST_NUMERIC_DAY)

    if args.print_months:
        print(" ".join(months_between(start, end)))
        return 0

    totals = collect(start, end, RawStore(args.root, PREFIX), workers=args.workers)
    print(json.dumps(totals))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Fail loudly if the newest A&E snapshot is too old.

A scheduled job that "succeeds" while collecting nothing is the worst failure, because nobody notices.
This check exits with code 1 when data is stale, which makes the GitHub Actions run fail and open an issue.

    python -m aecompass.collect.freshness --max-age-hours 3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import aed, archive
from .store import RawStore


def age_hours(store: RawStore) -> float | None:
    latest = store.latest_ts()
    if latest is None:
        return None
    return (archive.now_hkt() - archive.parse_ts(latest)).total_seconds() / 3600


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", type=Path, default=aed.DEFAULT_ROOT)
    p.add_argument("--max-age-hours", type=float, default=3.0)
    args = p.parse_args(argv)

    store = RawStore(args.root, aed.PREFIX)
    age = age_hours(store)
    if age is None:
        print("STALE: no A&E snapshots stored at all")
        return 1
    print(f"newest A&E snapshot: {store.latest_ts()} HKT ({age:.1f}h old)")
    if age > args.max_age_hours:
        print(f"STALE: older than {args.max_age_hours}h")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

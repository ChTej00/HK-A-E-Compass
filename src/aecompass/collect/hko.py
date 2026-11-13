"""Collect Hong Kong Observatory current weather and active warnings.

Unlike the A&E file, HKO's API is not kept in the data.gov.hk archive, so a missed run is lost for good.
That is acceptable: past temperature and rain come from Open-Meteo (see DECISIONS.md D5), and this
collector mainly exists to build up a history of *warnings* (rainstorm, typhoon, hot/cold weather).

    python -m aecompass.collect.hko
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from . import archive
from .store import RawStore

HKO_API = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php"
DEFAULT_ROOT = Path("data/raw/hko")
PREFIX = "hko_raw"


def collect(store: RawStore) -> bool:
    """Store one snapshot for the current hour. Returns False if this hour is already stored."""
    ts = archive.now_hkt().replace(minute=0).strftime(archive.TS_FORMAT)
    if store.has(ts):
        return False
    with httpx.Client(timeout=30, headers={"User-Agent": "aecompass-collector"}) as client:
        body = {}
        for data_type in ("rhrread", "warnsum"):
            r = client.get(HKO_API, params={"dataType": data_type, "lang": "en"})
            r.raise_for_status()
            body[data_type] = r.json()
    return store.append(ts, json.dumps(body, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = p.parse_args(argv)
    stored = collect(RawStore(args.root, PREFIX))
    print("stored" if stored else "already had this hour")
    return 0


if __name__ == "__main__":
    sys.exit(main())

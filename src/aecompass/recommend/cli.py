"""Where would a non-urgent patient probably be seen soonest, starting from a given place?

    python -m aecompass.recommend.cli "Tuen Mun Town Hall"
    python -m aecompass.recommend.cli "Langham Place" --refresh     # fetch the newest waits first

Needs the clean table (`python -m aecompass.clean.build`) and trained models
(`python -m aecompass.forecast.train`).
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta

import pandas as pd

from aecompass.clean import build
from aecompass.collect import aed, archive
from aecompass.collect.store import RawStore
from aecompass.forecast.dataset import load_clean
from aecompass.forecast.serve import forecast_latest, load_models
from aecompass.geo.geocode import geocode
from aecompass.recommend.engine import about_as_good, recommend
from aecompass.ref import holidays, hospitals
from aecompass.travel.estimate import DistanceTravelTime

TARGET = "t45_p50_min"
STALE_AFTER = pd.Timedelta(minutes=45)
DISCLAIMER = """\
This is not medical advice and not an official Hospital Authority service.
For non-life-threatening situations only. In an emergency, call 999 now.
Waits are the Hospital Authority's published estimates for semi-urgent and non-urgent patients, plus a
forecast of how they will change. Travel times are rough straight-line estimates. Sicker patients are
always seen first, so your own wait may differ."""


def refresh() -> None:
    """Download the last two days of snapshots and rebuild the clean table (the quality report is left alone)."""
    today = archive.now_hkt().date()
    aed.collect(today - timedelta(days=1), today, RawStore(aed.DEFAULT_ROOT, aed.PREFIX), verbose=False)
    df, _ = build.tidy(build.load_raw(build.RAW_ROOT)[0])
    df.to_parquet(build.CLEAN_PATH, index=False)


def fmt(minutes: float) -> str:
    hours, mins = divmod(int(round(minutes)), 60)
    return f"{hours}h {mins:02d}m" if hours else f"{mins}m"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("place", help="a Hong Kong building, estate or address")
    parser.add_argument("--refresh", action="store_true", help="fetch the newest published waits first")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args(argv)

    places = geocode(args.place)
    if not places:
        print(f"Could not find {args.place!r}. Try a building or estate name.")
        return 1
    place = places[0]
    if args.refresh:
        refresh()

    as_of, forecasts = forecast_latest(load_clean(), load_models(), TARGET, holidays.load())
    travel = DistanceTravelTime(hospitals.load()).to_all(place.point)
    options = recommend(forecasts, travel)

    print(DISCLAIMER, end="\n\n")
    print(f"Starting from: {place.matched_name} ({place.district})")
    print(f"Published waits as of {as_of:%a %d %b %Y %H:%M} Hong Kong time")
    age = archive.now_hkt() - as_of.to_pydatetime()
    if age > STALE_AFTER:
        print(f"WARNING: these waits are {age.total_seconds() / 3600:.1f} hours old. Run again with --refresh.")
    print()
    print(f"{'A&E':<42}{'Travel':>8}{'Wait on arrival (likely range)':>34}{'Total (range)':>26}")
    for o in options[: args.top]:
        wait = f"{fmt(o.wait_min)} ({fmt(o.wait_low)} to {fmt(o.wait_high)})"
        total = f"{fmt(o.total_min)} ({fmt(o.total_low)} to {fmt(o.total_high)})"
        print(f"{o.hospital:<42}{'~' + fmt(o.travel_min):>8}{wait:>34}{total:>26}")
    close = about_as_good(options)
    if len(close) > 1:
        print(f"\nThe top {len(close)} are within 15 minutes of each other: too close to call.")
    missing = sorted(set(travel) - set(forecasts))
    if missing:
        print(f"\nNo current published wait for: {', '.join(missing)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Load the clean table as a "panel": one row per 15-minute slot, one column per hospital.

The panel is put on a complete 15-minute grid. A slot the archive doesn't have stays NaN. We never fill
gaps with invented values: a row with a missing input or a missing answer is simply left out of scoring.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

CLEAN_PATH = Path("data/clean/aed_waits.parquet")
STEP = pd.Timedelta(minutes=15)
STEPS_PER_HOUR = 4
STEPS_PER_WEEK = 7 * 24 * STEPS_PER_HOUR

TARGETS = {
    "t45_p50_min": "Triage IV & V (semi-/non-urgent), median wait",
    "t3_p50_min": "Triage III (urgent), median wait",
}
HORIZONS_H = (1, 2, 3)


def load_clean(path: Path = CLEAN_PATH) -> pd.DataFrame:
    return pd.read_parquet(path)


def to_panel(df: pd.DataFrame, column: str, drop_stale: bool = True) -> pd.DataFrame:
    """Wide table of one column: index = every 15-minute slot in the period, columns = hospitals.

    Stale rows (the feed repeated an old update instead of refreshing, about 1% of slots) are blanked by
    default. Kept in, they would be free correct answers for persistence: "no change" is always right
    when the feed is frozen.
    """
    if drop_stale and "stale" in df.columns:
        df = df[~df["stale"]]
    wide = df.pivot(index="observed_at", columns="hospital", values=column)
    full_grid = pd.date_range(wide.index.min(), wide.index.max(), freq=STEP)
    wide = wide.reindex(full_grid)
    wide.index.name = "observed_at"
    wide.columns = wide.columns.astype(str)
    return wide.astype("float64")

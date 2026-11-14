"""The three baselines every model must be compared against.

A forecast is made at an "origin" time t for a "target" time t + h (h = 1, 2 or 3 hours).

1. persistence      the wait at t + h equals the wait showing now, at t
2. seasonal naive   the wait at t + h equals the wait at the same clock time one week earlier
3. historical mean  the average wait for that hospital, weekday and hour, learned from training data only

None of them looks at anything after t. The seasonal value is 7 days minus h in the past, and the
historical mean is fitted only on data before the test block starts.
"""

from __future__ import annotations

import pandas as pd

from .dataset import STEPS_PER_HOUR, STEPS_PER_WEEK
from .splits import Fold

BASELINES = ("persistence", "seasonal_naive", "historical_mean")


def historical_mean_table(train: pd.DataFrame) -> pd.DataFrame:
    """Mean wait per (weekday, hour) for each hospital. Index: (weekday, hour); columns: hospitals."""
    return train.groupby([train.index.day_of_week, train.index.hour]).mean()


def fold_predictions(panel: pd.DataFrame, fold: Fold, horizon_h: int) -> pd.DataFrame:
    """Long table for one fold and horizon: origin, hospital, actual, and one column per baseline.

    Only rows where the actual value and all three baselines exist are kept, so every baseline is
    scored on exactly the same rows.
    """
    k = horizon_h * STEPS_PER_HOUR
    origins = panel.index[(panel.index >= fold.test_start) & (panel.index < fold.test_end)]

    actual = panel.shift(-k).loc[origins]  # value at t + h, stored at row t
    persistence = panel.loc[origins]
    seasonal = panel.shift(STEPS_PER_WEEK - k).loc[origins]  # value at t + h - 7 days

    table = historical_mean_table(panel.loc[panel.index < fold.test_start])
    target_times = origins + pd.Timedelta(hours=horizon_h)
    keys = pd.MultiIndex.from_arrays([target_times.day_of_week, target_times.hour])
    historical = table.reindex(keys).set_axis(origins)

    parts = {"actual": actual, "persistence": persistence, "seasonal_naive": seasonal, "historical_mean": historical}
    long = pd.concat({name: frame.stack(future_stack=True) for name, frame in parts.items()}, axis=1)
    long.index.names = ["origin", "hospital"]
    long = long.dropna().reset_index()
    long["fold"] = fold.number
    long["horizon_h"] = horizon_h
    return long

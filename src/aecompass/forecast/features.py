"""Feature table for the forecasting model.

One row = one forecast: made at `origin` (time t) for one hospital, about the wait at t + h.

**The leakage rule:** every feature is computed only from values at or before t. In this file that
means every `.shift(n)` on a value series has n >= 0 (a positive shift looks into the past), with one
deliberate exception: `y`, the answer, which is the value at t + h and is never used as a feature.
Calendar features describe the *target* time, which is known in advance. `tests/test_features.py`
checks the rule by changing the future and asserting no feature moves.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .dataset import STEPS_PER_HOUR, STEPS_PER_WEEK, to_panel

STEPS_PER_DAY = 24 * STEPS_PER_HOUR
OTHER_SERIES = ["t3_p50_min", "t3_p95_min", "t45_p50_min", "t45_p95_min"]
WEATHER_FEATURES = ["temp_c", "rain_mm", "rain_3h_mm", "humidity_pct"]
CATEGORICAL = ["hospital"]
# Optional feature groups, switched on per model variant (see evals/run_feature_experiment.py).
STEP_FEATURES = ["slots_at_level", "last_step_size", "slots_since_step_up", "slots_since_step_down", "changes_3h"]
NEIGHBOUR_FEATURES = [
    "nearest_now", "nearest_change_1h", "neighbours_mean_now", "neighbours_change_1h", "now_vs_neighbours",
]
RUN_CAP = 96  # "how long has it been like this" is capped at one day


def _broadcast(series: pd.Series, like: pd.DataFrame) -> pd.DataFrame:
    """Repeat one per-time-slot series across all hospital columns."""
    return pd.DataFrame(
        np.repeat(series.to_numpy(dtype="float64")[:, None], like.shape[1], axis=1),
        index=like.index, columns=like.columns,
    )


def _mean_of(frames: list[pd.DataFrame], min_count: int) -> pd.DataFrame:
    """Cell-by-cell mean across several same-shaped tables, ignoring gaps; NaN if fewer than min_count exist."""
    stacked = np.stack([frame.to_numpy() for frame in frames])
    present = ~np.isnan(stacked)
    count = present.sum(axis=0)
    total = np.where(present, stacked, 0.0).sum(axis=0)
    mean = np.where(count >= min_count, total / np.maximum(count, 1), np.nan)
    return pd.DataFrame(mean, index=frames[0].index, columns=frames[0].columns)


def _slots_since(event: pd.DataFrame) -> pd.DataFrame:
    """For each cell, how many slots ago `event` was last True (0 = now). NaN before the first event."""
    position = pd.DataFrame(
        np.repeat(np.arange(len(event), dtype="float64")[:, None], event.shape[1], axis=1),
        index=event.index, columns=event.columns,
    )
    last = position.where(event).ffill()  # ffill carries the past forward, never the future back
    return (position - last).clip(upper=RUN_CAP)


def step_features(p: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """The published wait holds a level, then jumps. Describe where we are in that pattern."""
    diff = p - p.shift(1)
    known = diff.notna()
    moved = known & (diff != 0)
    out = {
        # a gap in the data restarts the count, because we cannot know what happened inside it
        "slots_at_level": _slots_since(moved | ~known),
        "last_step_size": diff.where(moved).ffill(limit=RUN_CAP),
        "slots_since_step_up": _slots_since(known & (diff > 0)),
        "slots_since_step_down": _slots_since(known & (diff < 0)),
        "changes_3h": moved.astype("float64").rolling(12, min_periods=6).sum(),
    }
    for name in out:
        out[name] = out[name].where(p.notna())
    return out


def neighbour_features(p: pd.DataFrame, neighbours: dict[str, list[str]]) -> dict[str, pd.DataFrame]:
    """What the closest other A&Es are showing right now (spill-over between nearby hospitals)."""
    change = p - p.shift(4)
    nearest_now, nearest_change, mean_now, mean_change = {}, {}, {}, {}
    for hospital in p.columns:
        near = [n for n in neighbours.get(hospital, []) if n in p.columns]
        if not near:
            continue
        nearest_now[hospital] = p[near[0]]
        nearest_change[hospital] = change[near[0]]
        mean_now[hospital] = p[near].mean(axis=1)
        mean_change[hospital] = change[near].mean(axis=1)
    frame = lambda cols: pd.DataFrame(cols, index=p.index).reindex(columns=p.columns)
    return {
        "nearest_now": frame(nearest_now),
        "nearest_change_1h": frame(nearest_change),
        "neighbours_mean_now": frame(mean_now),
        "neighbours_change_1h": frame(mean_change),
        "now_vs_neighbours": p - frame(mean_now),
    }


def build_features(
    df: pd.DataFrame,
    target: str,
    horizon_h: int,
    weather: pd.DataFrame | None = None,
    holidays: dict[date, str] | None = None,
    neighbours: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """Long table: origin, hospital, y (answer), y_now, and feature columns.

    Rows are kept only where the current value and the answer both exist. Other features may be NaN;
    LightGBM handles missing values natively.
    """
    k = horizon_h * STEPS_PER_HOUR
    p = to_panel(df, target)
    f: dict[str, pd.DataFrame] = {}

    # --- what the target series is doing right now and recently (all shifts look backwards)
    f["y_now"] = p
    for name, steps in [("15m", 1), ("30m", 2), ("1h", 4), ("2h", 8), ("3h", 12), ("6h", 24), ("24h", 96)]:
        f[f"change_{name}"] = p - p.shift(steps)
    f["mean_3h"] = p.rolling(12, min_periods=6).mean()
    f["mean_24h"] = p.rolling(STEPS_PER_DAY, min_periods=48).mean()
    f["std_3h"] = p.rolling(12, min_periods=6).std()
    f["now_vs_mean_24h"] = p - f["mean_24h"]

    # --- what happened at the target's clock time on earlier days (t + h - 1 day, - 7 days, ...)
    f["target_time_yesterday"] = p.shift(STEPS_PER_DAY - k)
    weeks = [p.shift(STEPS_PER_WEEK * w - k) for w in (1, 2, 3, 4)]
    f["target_time_last_week"] = weeks[0]
    f["target_time_mean_4w"] = _mean_of(weeks, min_count=2)
    f["now_vs_usual_now"] = p - _mean_of([p.shift(STEPS_PER_WEEK * w) for w in (1, 2, 3, 4)], min_count=2)
    # how the wait moved over the same h hours one day and one week ago
    f["move_same_window_yesterday"] = p.shift(STEPS_PER_DAY - k) - p.shift(STEPS_PER_DAY)
    f["move_same_window_last_week"] = p.shift(STEPS_PER_WEEK - k) - p.shift(STEPS_PER_WEEK)

    # --- the hospital's other published numbers, now
    for col in OTHER_SERIES:
        if col != target:
            f[f"{col}_now"] = to_panel(df, col)
    for flag in ("multi_resus", "managing_t1", "managing_t2"):
        f[flag] = to_panel(df, flag)

    # --- the rest of the city, now
    city = p.mean(axis=1)
    f["city_mean_now"] = _broadcast(city, p)
    f["city_change_1h"] = _broadcast(city - city.shift(4), p)
    f["now_vs_city"] = p.sub(city, axis=0)

    # --- optional groups: the step pattern of the series, and the nearest other hospitals
    f.update(step_features(p))
    if neighbours is not None:
        f.update(neighbour_features(p, neighbours))

    # --- calendar of the target time (known in advance)
    target_time = p.index + pd.Timedelta(hours=horizon_h)
    hour = pd.Series(target_time.hour + target_time.minute / 60, index=p.index)
    f["target_hour"] = _broadcast(hour, p)
    f["target_hour_sin"] = _broadcast(np.sin(2 * np.pi * hour / 24), p)
    f["target_hour_cos"] = _broadcast(np.cos(2 * np.pi * hour / 24), p)
    f["target_weekday"] = _broadcast(pd.Series(target_time.day_of_week, index=p.index), p)
    holiday_dates = set(holidays or {})
    is_holiday = pd.Series([d in holiday_dates for d in target_time.date], index=p.index, dtype="float64")
    f["target_is_holiday"] = _broadcast(is_holiday, p)

    # --- weather at the origin hour
    if weather is not None:
        w = weather.assign(rain_3h_mm=weather["rain_mm"].rolling(3, min_periods=1).sum())
        at_origin = w.reindex(p.index.floor("h"))
        for col in WEATHER_FEATURES:
            f[col] = _broadcast(pd.Series(at_origin[col].to_numpy(), index=p.index), p)

    f["y"] = p.shift(-k)  # the answer: the only look into the future, and never a feature

    long = pd.concat({name: frame.stack(future_stack=True) for name, frame in f.items()}, axis=1)
    long.index.names = ["origin", "hospital"]
    long = long.dropna(subset=["y", "y_now"]).reset_index()
    long["hospital"] = long["hospital"].astype("category")
    return long


def feature_columns(
    table: pd.DataFrame, use_weather: bool = True, use_steps: bool = True, use_neighbours: bool = True
) -> list[str]:
    drop = {"origin", "y"}
    drop |= set() if use_weather else set(WEATHER_FEATURES)
    drop |= set() if use_steps else set(STEP_FEATURES)
    drop |= set() if use_neighbours else set(NEIGHBOUR_FEATURES)
    return [c for c in table.columns if c not in drop]

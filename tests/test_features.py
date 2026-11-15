import numpy as np
import pandas as pd

from aecompass.forecast.features import (
    NEIGHBOUR_FEATURES, STEP_FEATURES, build_features, feature_columns, step_features,
)
from aecompass.forecast.model import apply_interval, conformal_offsets

TZ = "Asia/Hong_Kong"
COLS = ["t3_p50_min", "t3_p95_min", "t45_p50_min", "t45_p95_min"]
NEIGHBOURS = {"A": ["B", "C"], "B": ["C", "A"], "C": ["A", "B"]}


def make_clean(days: int = 40, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=days * 96, freq="15min", tz=TZ)
    frames = []
    for hospital in ("A", "B", "C"):
        frame = pd.DataFrame({"observed_at": idx, "hospital": hospital})
        for col in COLS:
            frame[col] = rng.integers(0, 12, len(idx)) * 30.0
        frame["multi_resus"] = rng.random(len(idx)) < 0.05
        frame["managing_t1"] = rng.random(len(idx)) < 0.1
        frame["managing_t2"] = rng.random(len(idx)) < 0.2
        frame["stale"] = False
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def make_weather(days: int = 40) -> pd.DataFrame:
    idx = pd.date_range("2026-01-05", periods=days * 24, freq="h", tz=TZ)
    rng = np.random.default_rng(1)
    return pd.DataFrame(
        {"temp_c": rng.normal(20, 3, len(idx)), "rain_mm": rng.random(len(idx)), "humidity_pct": 70.0}, index=idx
    )


def test_no_feature_changes_when_the_future_changes():
    """The leakage test: scramble everything after a cut-off; features at or before it must not move."""
    clean, weather = make_clean(), make_weather()
    cut = pd.Timestamp("2026-02-05 12:00", tz=TZ)
    tampered = clean.copy()
    later = tampered["observed_at"] > cut
    for col in COLS:
        tampered.loc[later, col] = tampered.loc[later, col] + 9999.0
    tampered.loc[later, "multi_resus"] = True
    weather_tampered = weather.copy()
    weather_tampered.loc[weather_tampered.index > cut] += 50.0

    for target in ("t45_p50_min", "t3_p50_min"):
        for h in (1, 3):
            a = build_features(clean, target, h, weather=weather, neighbours=NEIGHBOURS)
            b = build_features(tampered, target, h, weather=weather_tampered, neighbours=NEIGHBOURS)
            feats = [c for c in feature_columns(a) if c != "hospital"]
            assert {"slots_at_level", "nearest_now"} <= set(feats)
            a = a[a["origin"] <= cut].set_index(["origin", "hospital"])[feats]
            b = b[b["origin"] <= cut].set_index(["origin", "hospital"])[feats]
            b = b.loc[a.index]
            for col in feats:
                assert np.allclose(a[col].to_numpy(), b[col].to_numpy(), equal_nan=True), (target, h, col)


def test_y_is_the_value_h_hours_after_the_origin():
    clean = make_clean()
    table = build_features(clean, "t45_p50_min", 2)
    truth = clean.set_index(["observed_at", "hospital"])["t45_p50_min"]
    sample = table.sample(200, random_state=0)
    for row in sample.itertuples():
        assert row.y == truth[(row.origin + pd.Timedelta(hours=2), row.hospital)]
        assert row.y_now == truth[(row.origin, row.hospital)]
    assert "y" not in feature_columns(table) and "origin" not in feature_columns(table)


def test_weather_can_be_switched_off():
    table = build_features(make_clean(), "t45_p50_min", 1, weather=make_weather())
    assert "temp_c" in feature_columns(table)
    assert not {"temp_c", "rain_mm", "rain_3h_mm", "humidity_pct"} & set(feature_columns(table, use_weather=False))


def test_conformal_interval_covers_about_the_requested_share():
    rng = np.random.default_rng(0)
    n = 20_000
    calibration = pd.DataFrame(
        {"hospital": rng.choice(["A", "B"], n), "model": 100.0, "actual": 100 + rng.normal(0, 20, n)}
    )
    calibration.loc[calibration["hospital"] == "B", "actual"] += 30  # B is biased; offsets must absorb that
    offsets = conformal_offsets(calibration, coverage=0.8)
    fresh = pd.DataFrame({"hospital": rng.choice(["A", "B"], n), "model": 100.0})
    actual = 100 + rng.normal(0, 20, n) + np.where(fresh["hospital"] == "B", 30, 0)
    lo, hi = apply_interval(fresh, offsets)
    assert abs(((actual >= lo) & (actual <= hi)).mean() - 0.8) < 0.02
    assert (lo >= 0).all()


def test_step_features_count_slots_since_the_last_change():
    idx = pd.date_range("2026-01-05", periods=8, freq="15min", tz=TZ)
    p = pd.DataFrame({"A": [60.0, 60, 90, 90, 90, 60, np.nan, 60]}, index=idx)
    f = step_features(p)
    assert f["slots_at_level"]["A"].tolist()[:6] == [0, 1, 0, 1, 2, 0]  # the first slot has no history, so it starts at 0
    assert np.isnan(f["slots_at_level"]["A"].iloc[6]) and f["slots_at_level"]["A"].iloc[7] == 0  # a gap restarts the count
    assert f["last_step_size"]["A"].tolist()[2:6] == [30, 30, 30, -30]
    assert f["slots_since_step_up"]["A"].tolist()[2:6] == [0, 1, 2, 3]


def test_neighbour_features_use_the_listed_hospitals():
    table = build_features(make_clean(), "t45_p50_min", 1, neighbours=NEIGHBOURS)
    a = table[table["hospital"] == "A"].set_index("origin")
    b = table[table["hospital"] == "B"].set_index("origin")
    shared = a.index.intersection(b.index)
    assert np.allclose(a.loc[shared, "nearest_now"], b.loc[shared, "y_now"])
    assert not set(NEIGHBOUR_FEATURES) & set(feature_columns(table, use_neighbours=False))
    assert not set(STEP_FEATURES) & set(feature_columns(table, use_steps=False))

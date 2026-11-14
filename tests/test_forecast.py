import numpy as np
import pandas as pd

from aecompass.forecast.baselines import fold_predictions
from aecompass.forecast.dataset import to_panel
from aecompass.forecast.splits import Fold, walk_forward_folds

TZ = "Asia/Hong_Kong"


def make_panel(days: int = 30) -> pd.DataFrame:
    """Two hospitals where the value at each slot encodes its own time, so shifts are easy to verify."""
    idx = pd.date_range("2026-01-05", periods=days * 96, freq="15min", tz=TZ)  # starts on a Monday
    minutes = np.arange(len(idx), dtype="float64") * 15
    return pd.DataFrame({"A": minutes, "B": minutes + 100_000}, index=idx)


def test_folds_are_ordered_and_do_not_overlap():
    panel = make_panel(60)
    folds = walk_forward_folds(panel.index, initial_train_days=28, test_days=7)
    assert len(folds) >= 3
    for a, b in zip(folds, folds[1:]):
        assert a.test_end == b.test_start
    assert all(f.train_start < f.test_start < f.test_end <= panel.index.max() for f in folds)


def test_baselines_point_at_the_right_times():
    panel = make_panel(30)
    fold = Fold(1, panel.index[0], pd.Timestamp("2026-01-26", tz=TZ), pd.Timestamp("2026-01-28", tz=TZ))
    preds = fold_predictions(panel, fold, horizon_h=2)
    a = preds[preds["hospital"] == "A"].set_index("origin")
    # value == minutes since start, so differences are time offsets in minutes
    assert ((a["actual"] - a["persistence"]) == 120).all()  # target is 2 hours after the origin
    assert ((a["actual"] - a["seasonal_naive"]) == 7 * 24 * 60).all()  # exactly one week before the target
    assert (a["seasonal_naive"] < a["persistence"]).all()  # and therefore already known at the origin
    assert a.index.min() == fold.test_start and a.index.max() < fold.test_end


def test_historical_mean_uses_only_training_data():
    panel = make_panel(30)
    cut = pd.Timestamp("2026-01-26", tz=TZ)
    fold = Fold(1, panel.index[0], cut, cut + pd.Timedelta(days=2))
    before = fold_predictions(panel, fold, 1)["historical_mean"]
    tampered = panel.copy()
    tampered.loc[tampered.index >= cut] = -999.0  # change everything from the test block onwards
    after = fold_predictions(tampered, fold, 1)["historical_mean"]
    assert np.allclose(before.values, after.values)


def test_rows_with_gaps_are_dropped_not_filled():
    panel = make_panel(30)
    cut = pd.Timestamp("2026-01-26", tz=TZ)
    hole = cut + pd.Timedelta(hours=5)
    panel.loc[hole, "A"] = np.nan
    preds = fold_predictions(panel, Fold(1, panel.index[0], cut, cut + pd.Timedelta(days=2)), 1)
    a = preds[preds["hospital"] == "A"]
    assert hole not in set(a["origin"])  # no current value -> no persistence forecast
    assert hole - pd.Timedelta(hours=1) not in set(a["origin"])  # no actual to score against
    assert not preds.isna().any().any()


def test_stale_rows_are_blanked_in_the_panel():
    idx = pd.date_range("2026-01-05", periods=4, freq="15min", tz=TZ)
    df = pd.DataFrame({"observed_at": idx, "hospital": "A", "t45_p50_min": [60.0, 60.0, 90.0, 90.0],
                       "stale": [False, True, False, False]})
    panel = to_panel(df, "t45_p50_min")
    assert len(panel) == 4 and np.isnan(panel["A"].iloc[1]) and panel["A"].iloc[2] == 90
    assert not to_panel(df, "t45_p50_min", drop_stale=False)["A"].isna().any()

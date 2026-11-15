"""The forecasting model and its prediction intervals.

Model: LightGBM (gradient-boosted decision trees, the same family as XGBoost). One model per target and
horizon, shared across all 18 hospitals with `hospital` as a categorical feature.

Two choices worth knowing:

- **It predicts the change, not the level.** The model learns y(t+h) - y(now) and we add y(now) back.
  The wait is sticky, so "how much will it move?" is an easier question than "what will it be?", and
  a model that learns nothing falls back to persistence instead of to something worse.
- **It minimises absolute error (L1), not squared error.** We report MAE, so we train on the same thing.

Hyperparameters are fixed up front and were not tuned against the test folds.
"""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

PARAMS = dict(
    objective="l1",
    n_estimators=400,
    learning_rate=0.05,
    num_leaves=63,
    min_child_samples=200,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    random_state=0,
    n_jobs=-1,
    verbose=-1,
)


def fit(train: pd.DataFrame, features: list[str], params: dict | None = None) -> lgb.LGBMRegressor:
    model = lgb.LGBMRegressor(**(params or PARAMS))
    model.fit(train[features], train["y"] - train["y_now"])
    return model


def predict(model: lgb.LGBMRegressor, rows: pd.DataFrame, features: list[str]) -> np.ndarray:
    """Predicted wait in minutes: current value plus predicted change, never below zero."""
    return np.clip(rows["y_now"].to_numpy() + model.predict(rows[features]), 0, None)


# ---------------------------------------------------------------------------------------------------
# Conformal prediction intervals
# ---------------------------------------------------------------------------------------------------


def conformal_offsets(calibration: pd.DataFrame, coverage: float = 0.8, min_rows: int = 200) -> pd.DataFrame:
    """How far the truth typically lands below and above the prediction, per hospital.

    `calibration` holds recent forecasts the model made on data it had not trained on, with columns
    hospital, actual, model. For an 80% interval we take the 10th and 90th percentiles of
    (actual - prediction). Hospitals with too few rows fall back to the all-hospital percentiles.
    """
    tail = (1 - coverage) / 2
    residual = calibration["actual"] - calibration["model"]
    overall = residual.quantile([tail, 1 - tail]).to_numpy()
    grouped = residual.groupby(calibration["hospital"], observed=True)
    out = grouped.quantile(tail).to_frame("lo_offset").join(grouped.quantile(1 - tail).rename("hi_offset"))
    small = grouped.size() < min_rows
    out.loc[small, ["lo_offset", "hi_offset"]] = overall
    out.loc["__all__"] = overall
    return out


def apply_interval(rows: pd.DataFrame, offsets: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Lower and upper bounds for each row's prediction (column `model`), clipped at zero."""
    hosp = rows["hospital"].astype(str)
    lo = hosp.map(offsets["lo_offset"]).fillna(offsets.loc["__all__", "lo_offset"]).to_numpy()
    hi = hosp.map(offsets["hi_offset"]).fillna(offsets.loc["__all__", "hi_offset"]).to_numpy()
    pred = rows["model"].to_numpy()
    return np.clip(pred + lo, 0, None), np.clip(pred + hi, 0, None)

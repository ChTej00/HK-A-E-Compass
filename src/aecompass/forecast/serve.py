"""Forecast the next three hours from the latest published waits, using the saved models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from aecompass.forecast.dataset import HORIZONS_H
from aecompass.forecast.features import build_features
from aecompass.recommend.engine import Forecast

MODEL_DIR = Path("data/models")
HISTORY_DAYS = 35  # the features look back four weeks; a little more leaves room for gaps


@dataclass
class Models:
    boosters: dict[str, lgb.Booster]
    features: dict[str, list[str]]
    offsets: dict[str, dict[str, dict[str, float]]]
    data_through: str


def load_models(model_dir: Path = MODEL_DIR) -> Models:
    meta = json.loads((model_dir / "meta.json").read_text(encoding="utf-8"))
    offsets = json.loads((model_dir / "offsets.json").read_text(encoding="utf-8"))
    boosters = {key: lgb.Booster(model_file=str(model_dir / f"{key}.txt")) for key in meta["models"]}
    return Models(boosters, {k: v["features"] for k, v in meta["models"].items()}, offsets, meta["data_through"])


def forecast_latest(
    df: pd.DataFrame, models: Models, target: str, holidays: dict[date, str] | None = None
) -> tuple[pd.Timestamp, dict[str, Forecast]]:
    """(time of the newest snapshot, {hospital: Forecast}) for hospitals that published a value in it.

    `df` is the clean table. Only its last `HISTORY_DAYS` days are used.
    """
    recent = df[df["observed_at"] >= df["observed_at"].max() - pd.Timedelta(days=HISTORY_DAYS)]
    per_horizon = {}
    for h in HORIZONS_H:
        key = f"{target}_h{h}"
        table = build_features(recent, target, h, None, holidays, require_answer=False)
        latest = table[table["origin"] == table["origin"].max()].set_index("hospital", drop=False)
        change = models.boosters[key].predict(latest[models.features[key]])
        pred = np.clip(latest["y_now"].to_numpy() + change, 0, None)
        band = models.offsets.get(key, {})
        fallback = band.get("__all__", {"lo_offset": float("nan"), "hi_offset": float("nan")})
        lo = [max(p + band.get(name, fallback)["lo_offset"], 0) for name, p in zip(latest.index, pred)]
        hi = [max(p + band.get(name, fallback)["hi_offset"], 0) for name, p in zip(latest.index, pred)]
        per_horizon[h] = pd.DataFrame({"now": latest["y_now"], "pred": pred, "lo": lo, "hi": hi}, index=latest.index)
        as_of = table["origin"].max()
    forecasts = {}
    for name in per_horizon[1].index:
        rows = [per_horizon[h].loc[name] for h in HORIZONS_H]
        forecasts[str(name)] = Forecast(
            float(rows[0]["now"]), *(tuple(float(r[col]) for r in rows) for col in ("pred", "lo", "hi"))
        )
    return as_of, forecasts

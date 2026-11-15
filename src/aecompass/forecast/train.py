"""Train the models the live app uses, on all the history there is.

    python -m aecompass.forecast.train        # about 2 minutes; writes data/models/

The evaluation (`evals/run_forecast.py`) answers "how good is this recipe?" by training on the past and
testing on the future, many times. This script applies the same recipe once more, to everything, for use
on moments whose answer nobody knows yet. Same features, same fixed settings.

Prediction intervals come from the evaluation's most recent test block: forecasts made by a model that
had not seen those two weeks, compared with what then happened (see DECISIONS.md D15).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from aecompass.forecast import model as M
from aecompass.forecast.dataset import HORIZONS_H, TARGETS, load_clean
from aecompass.forecast.features import build_features, feature_columns
from aecompass.ref import holidays

MODEL_DIR = Path("data/models")
EVAL_PREDS = Path("data/eval/forecast_preds.parquet")
COVERAGE = 0.8


def main() -> None:
    df, holiday_map = load_clean(), holidays.load()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    preds = pd.read_parquet(EVAL_PREDS) if EVAL_PREDS.exists() else None
    meta = {"data_through": str(df["observed_at"].max()), "coverage": COVERAGE, "models": {}}
    offsets = {}
    for target in TARGETS:
        for h in HORIZONS_H:
            table = build_features(df, target, h, None, holiday_map)
            features = feature_columns(table, use_weather=False, use_steps=False, use_neighbours=False)
            train = table[table["origin"].dt.minute % 30 == 0]
            fitted = M.fit(train, features)
            key = f"{target}_h{h}"
            fitted.booster_.save_model(str(MODEL_DIR / f"{key}.txt"))
            meta["models"][key] = {"features": features, "train_rows": len(train)}
            if preds is not None:
                block = preds[(preds["target"] == target) & (preds["horizon_h"] == h)]
                block = block[block["fold"] == block["fold"].max()]
                offsets[key] = M.conformal_offsets(block, COVERAGE).round(3).to_dict("index")
            print(f"{key}: {len(train):,} rows, {len(features)} features")
    if preds is None:
        print(f"warning: {EVAL_PREDS} not found, so no intervals were saved. Run evals/run_forecast.py first.")
    (MODEL_DIR / "offsets.json").write_text(json.dumps(offsets, indent=1), encoding="utf-8")
    (MODEL_DIR / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"saved to {MODEL_DIR}, trained on data through {meta['data_through']}")


if __name__ == "__main__":
    main()

"""Walk-forward evaluation of the LightGBM forecaster against the three baselines.

    python evals/run_forecast.py                 # main run (about 15 minutes)
    python evals/run_forecast.py --ablations     # also run the ablations on the non-urgent target
    python evals/run_forecast.py --report-only   # rebuild the report from the saved forecasts, no training

Writes  data/eval/forecast_preds.parquet         every out-of-sample forecast (used later by the regret eval)
        evals/reports/forecast.md                generated summary; never hand-edited
        evals/reports/forecast_by_fold.csv, forecast_by_hospital.csv
        evals/reports/figures/forecast_*.png
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from aecompass.forecast import model as M
from aecompass.forecast.baselines import BASELINES, fold_predictions
from aecompass.forecast.dataset import HORIZONS_H, TARGETS, load_clean, to_panel
from aecompass.forecast.features import build_features, feature_columns
from aecompass.forecast.splits import walk_forward_folds
from aecompass.ref import holidays, hospitals, weather

REPORTS = Path("evals/reports")
FIGS = REPORTS / "figures"
PREDS_PATH = Path("data/eval/forecast_preds.parquet")
INITIAL_TRAIN_DAYS, TEST_DAYS = 56, 14
COVERAGE = 0.8
MAIN_TARGET = "t45_p50_min"



@dataclass(frozen=True)
class Variant:
    """One way of training the model: which optional feature groups it sees and how much history."""

    weather: bool = False
    steps: bool = False
    neighbours: bool = False
    window_days: int | None = None  # None = everything so far
    params: dict | None = None  # None = the fixed hyperparameters in model.py


VARIANTS = {"model": Variant()}  # the model that ships
ABLATIONS = {"model_with_weather": Variant(weather=True), "model_last_120d": Variant(window_days=120)}

SURFACE, INK, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7"
SERIES = {  # colour follows the method everywhere it appears
    "persistence": ("Persistence", "#2a78d6"),
    "seasonal_naive": ("Same time last week", "#eb6834"),
    "historical_mean": ("Historical average", "#1baf7a"),
    "model": ("LightGBM", "#eda100"),
}
plt.rcParams.update(
    {
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.size": 10, "text.color": INK, "axes.labelcolor": MUTED, "xtick.color": MUTED,
        "ytick.color": MUTED, "axes.edgecolor": AXIS, "axes.spines.top": False, "axes.spines.right": False,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    }
)


def run_target(df, target, variants, weather_df, holiday_map, log, neighbours=None, first_fold=1) -> pd.DataFrame:
    """All out-of-sample predictions for one target: baselines plus one column per model variant."""
    panel = to_panel(df, target)
    folds = [f for f in walk_forward_folds(panel.index, INITIAL_TRAIN_DAYS, TEST_DAYS) if f.number >= first_fold]
    out = []
    for h in HORIZONS_H:
        table = build_features(df, target, h, weather_df, holiday_map, neighbours)
        horizon = pd.Timedelta(hours=h)
        for fold in folds:
            preds = fold_predictions(panel, fold, h)  # baselines; defines the rows everything is scored on
            test = table[(table["origin"] >= fold.test_start) & (table["origin"] < fold.test_end)]
            for name, v in variants.items():
                # A training row's answer lies at origin + h. It must be known before the test block starts.
                train = table[table["origin"] + horizon < fold.test_start]
                if v.window_days:
                    train = train[train["origin"] >= fold.test_start - pd.Timedelta(days=v.window_days)]
                train = train[train["origin"].dt.minute % 30 == 0]  # neighbours 15 min apart are near-duplicates
                feats = feature_columns(table, v.weather, v.steps, v.neighbours)
                t0 = time.time()
                fitted = M.fit(train, feats, v.params)
                scored = test[["origin", "hospital"]].assign(**{name: M.predict(fitted, test, feats)})
                preds = preds.merge(scored, on=["origin", "hospital"], how="inner")
                log(f"{target} +{h}h fold {fold.number:2d} {name}: {len(train):,} train rows, {time.time() - t0:.0f}s")
            out.append(preds)
        if target == MAIN_TARGET and h == 2 and "model" in variants:
            # refit the shipped variant on the last block's training rows, so this never depends on loop order
            feats = feature_columns(table, variants["model"].weather, variants["model"].steps, variants["model"].neighbours)
            train = table[(table["origin"] + horizon < folds[-1].test_start) & (table["origin"].dt.minute % 30 == 0)]
            fitted = M.fit(train, feats, variants["model"].params)
            importance = pd.Series(fitted.booster_.feature_importance("gain"), index=feats)
            (importance / importance.sum()).sort_values(ascending=False).round(4).to_csv(
                REPORTS / "forecast_feature_importance.csv", header=["share_of_gain"]
            )
    result = pd.concat(out, ignore_index=True)
    result.insert(0, "target", target)
    result["test_period"] = result["fold"].map({f.number: f.label() for f in folds})
    return result


def add_intervals(preds: pd.DataFrame) -> pd.DataFrame:
    """Rolling conformal: each fold's interval comes from the previous fold's out-of-sample errors."""
    parts = []
    for (_, _), group in preds.groupby(["target", "horizon_h"]):
        by_fold = {k: g for k, g in group.groupby("fold")}
        for number, rows in by_fold.items():
            rows = rows.copy()
            if number - 1 in by_fold:
                offsets = M.conformal_offsets(by_fold[number - 1], COVERAGE)
                rows["lo"], rows["hi"] = M.apply_interval(rows, offsets)
            else:
                rows["lo"] = rows["hi"] = float("nan")  # the first fold has no earlier errors to learn from
            parts.append(rows)
    return pd.concat(parts, ignore_index=True)


def mae(preds: pd.DataFrame, cols: list[str], by: list[str]) -> pd.DataFrame:
    errors = preds[cols].sub(preds["actual"], axis=0).abs()
    return errors.join(preds[by]).groupby(by, observed=True).mean()


def md(df: pd.DataFrame, digits: int = 1) -> str:
    df = df.reset_index()
    rows = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    for r in df.itertuples(index=False):
        rows.append("| " + " | ".join(f"{v:.{digits}f}" if isinstance(v, float) else str(v) for v in r) + " |")
    return "\n".join(rows)


def figures(preds: pd.DataFrame) -> list[str]:
    FIGS.mkdir(parents=True, exist_ok=True)
    main = preds[preds["target"] == MAIN_TARGET]
    cols = list(SERIES)

    table = mae(main, cols, ["horizon_h"])
    fig, ax = plt.subplots(figsize=(8, 4))
    width = 0.19
    for i, col in enumerate(cols):
        label, colour = SERIES[col]
        x = [j + (i - 1.5) * (width + 0.02) for j in range(len(table))]
        ax.bar(x, table[col], width=width, color=colour, label=label)
        for xi, v in zip(x, table[col]):
            ax.text(xi, v + 0.8, f"{v:.0f}", ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_xticks(range(len(table)), [f"+{h} hour{'s' if h > 1 else ''}" for h in table.index])
    ax.set_ylabel("mean absolute error (minutes)")
    ax.set_title("Non-urgent wait: forecast error by method (lower is better)")
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", length=0, labelcolor=INK)
    ax.legend(frameon=False, ncols=4, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    fig.savefig(FIGS / "forecast_mae_by_horizon.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    two = main[main["horizon_h"] == 2]
    starts = two.groupby("fold")["origin"].min()
    per_fold = mae(two, cols, ["fold"])
    fig, ax = plt.subplots(figsize=(10, 3.8))
    for col in ("persistence", "historical_mean", "model"):
        label, colour = SERIES[col]
        ax.plot(starts.values, per_fold[col].values, color=colour, linewidth=2, marker="o", markersize=4, label=label)
        ax.annotate(label, (starts.values[-1], per_fold[col].values[-1]), xytext=(8, 0),
                    textcoords="offset points", va="center", color=INK, fontsize=9)
    ax.set_ylabel("MAE (minutes)")
    ax.set_title("Non-urgent wait, +2 hours: error in each two-week test block")
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, ncols=3, loc="lower left")
    fig.savefig(FIGS / "forecast_mae_by_fold.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return ["figures/forecast_mae_by_horizon.png", "figures/forecast_mae_by_fold.png"]


def report(preds: pd.DataFrame, ablations: bool, minutes: float | None) -> str:
    figs = figures(preds)
    cols = [*BASELINES, "model"]
    out = [
        "# Forecast results (walk-forward)",
        "",
        "Generated by `python evals/run_forecast.py`. Do not edit by hand.",
        "",
        "The values being predicted are the Hospital Authority's **published estimates**, not measured",
        "patient waits. Errors are mean absolute error (MAE) in **minutes**; lower is better.",
        "",
        f"- Test period: {preds['origin'].min():%d %b %Y} to {preds['origin'].max():%d %b %Y}, "
        f"{preds['fold'].nunique()} two-week blocks, {preds['hospital'].nunique()} hospitals.",
        "- For each block the model is trained only on forecasts whose answer was already known before the "
        "block started, then scored on the block. Baselines and model are scored on identical rows.",
        "- One LightGBM model per target and horizon, shared across hospitals, no weather features. Fixed hyperparameters, "
        "not tuned on these test blocks. Trained on forecasts made on the hour and half hour; tested on all.",
        f"- Run time: {minutes:.0f} minutes." if minutes is not None
        else "- Report rebuilt from the saved forecasts (`--report-only`); the models were not retrained.",
        "",
    ]
    by_fold_all, by_hosp_all = [], []
    for target, description in TARGETS.items():
        p = preds[preds["target"] == target]
        table = mae(p, cols, ["horizon_h"])
        best_baseline = table[list(BASELINES)].min(axis=1)
        table["vs persistence"] = (table["model"] / table["persistence"] - 1).map("{:+.1%}".format)
        table["vs best baseline"] = (table["model"] / best_baseline - 1).map("{:+.1%}".format)
        folds = mae(p, cols, ["horizon_h", "fold"])
        wins = (folds["model"] < folds[list(BASELINES)].min(axis=1)).groupby("horizon_h").agg(["sum", "size"])
        table["blocks where model beats every baseline"] = [f"{a} of {b}" for a, b in wins.to_numpy()]
        out += [f"## `{target}`: {description}", "", md(table), ""]
        if target == MAIN_TARGET:
            out += [f"![]({figs[0]})", "", f"![]({figs[1]})", ""]

        hosp = mae(p, cols, ["hospital", "horizon_h"])
        worst = (hosp["model"] / hosp[list(BASELINES)].min(axis=1) - 1).groupby("horizon_h").max()
        out += [
            "Worst single hospital, model vs that hospital's best baseline: "
            + ", ".join(f"+{h}h {v:+.1%}" for h, v in worst.items())
            + " (negative means the model wins at every hospital).",
            "",
        ]

        iv = p.dropna(subset=["lo", "hi"])
        inside = (iv["actual"] >= iv["lo"]) & (iv["actual"] <= iv["hi"])
        cov = pd.DataFrame(
            {
                "coverage": inside.groupby(iv["horizon_h"]).mean().map("{:.1%}".format),
                "mean width (min)": (iv["hi"] - iv["lo"]).groupby(iv["horizon_h"]).mean(),
                "lowest block": inside.groupby([iv["horizon_h"], iv["fold"]]).mean().groupby("horizon_h").min().map("{:.1%}".format),
                "highest block": inside.groupby([iv["horizon_h"], iv["fold"]]).mean().groupby("horizon_h").max().map("{:.1%}".format),
                "lowest hospital": inside.groupby([iv["horizon_h"], iv["hospital"]], observed=True).mean().groupby("horizon_h").min().map("{:.1%}".format),
            }
        )
        out += [
            f"**{COVERAGE:.0%} prediction intervals** (rolling conformal, per hospital; blocks 2 onward, "
            f"{len(iv):,} forecasts). Target coverage is {COVERAGE:.0%}.",
            "",
            md(cov),
            "",
        ]
        f = folds.reset_index()
        f.insert(0, "target", target)
        f["test_period"] = f["fold"].map(p.drop_duplicates("fold").set_index("fold")["test_period"])
        f["coverage"] = f.set_index(["horizon_h", "fold"]).index.map(
            inside.groupby([iv["horizon_h"], iv["fold"]]).mean().to_dict()
        )
        by_fold_all.append(f)
        hh = hosp.reset_index()
        hh.insert(0, "target", target)
        by_hosp_all.append(hh)

    if ablations:
        p = preds[preds["target"] == MAIN_TARGET]
        ab = mae(p, ["persistence", "model", *ABLATIONS], ["horizon_h"])
        out += [
            "## Ablations (non-urgent target)",
            "",
            "Same folds and rows. `model_with_weather` adds four weather features (temperature, rain, rain over "
            "3 hours, humidity). `model_last_120d` trains only on the most recent 120 days instead of all history.",
            "",
            md(ab, 2),
            "",
        ]
        fee = mae(p, ["persistence", "model", "model_last_120d"], ["horizon_h", "fold"]).reset_index()
        late = fee[fee["fold"] >= 12].groupby("horizon_h")[["model", "model_last_120d"]].mean()
        out += [
            "Blocks 12 onward only (from mid-2026, where a 120-day window no longer contains any data from "
            "before the 1 Jan 2026 fee change):",
            "",
            md(late, 2),
            "",
        ]

    imp = pd.read_csv(REPORTS / "forecast_feature_importance.csv", index_col=0)["share_of_gain"]
    out += [
        "## What the model uses",
        "",
        "Share of total split gain, non-urgent target at +2h, model from the last block. Gain shows what the "
        "trees split on, not causal importance, and correlated features share credit arbitrarily.",
        "",
        md(imp.head(12).map("{:.1%}".format).rename("share of gain").rename_axis("feature").to_frame()),
        "",
        "Per-block and per-hospital numbers: `forecast_by_fold.csv`, `forecast_by_hospital.csv`.",
        "",
    ]
    pd.concat(by_fold_all).round(3).to_csv(REPORTS / "forecast_by_fold.csv", index=False)
    pd.concat(by_hosp_all).round(3).to_csv(REPORTS / "forecast_by_hospital.csv", index=False)
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ablations", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    if args.report_only:
        preds = pd.read_parquet(PREDS_PATH)
        text = report(preds, all(name in preds.columns for name in ABLATIONS), None)
        (REPORTS / "forecast.md").write_text(text, encoding="utf-8")
        print(text)
        return
    started = time.time()
    df, weather_df, holiday_map = load_clean(), weather.load(), holidays.load()
    neighbours = hospitals.nearest(hospitals.load(), k=3)
    log = lambda message: print(f"[{(time.time() - started) / 60:5.1f} min] {message}", flush=True)

    parts = []
    for target in TARGETS:
        variants = VARIANTS | (ABLATIONS if args.ablations and target == MAIN_TARGET else {})
        parts.append(run_target(df, target, variants, weather_df, holiday_map, log, neighbours))
    preds = add_intervals(pd.concat(parts, ignore_index=True))

    PREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    preds.to_parquet(PREDS_PATH, index=False)
    text = report(preds, args.ablations, (time.time() - started) / 60)
    (REPORTS / "forecast.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

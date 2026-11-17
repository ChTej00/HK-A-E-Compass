"""Hindsight ("regret") evaluation of the recommender for non-urgent cases.

    python evals/run_regret.py        # about a minute; needs data/eval/forecast_preds.parquet

For every 15-minute moment in the forecast test period and each of 18 starting points (one per
district), four ways of choosing an A&E are replayed:

    nearest         the A&E with the shortest travel time (what people do without the app)
    current_waits   shortest travel + the wait published right now (an app with no forecasting)
    app             shortest travel + the forecast wait at the arrival time (this project)
    oracle          shortest travel + the wait actually published at the arrival time (unreachable best)

Each choice is then scored with what really happened: travel time + the wait published when the person
would have arrived. The forecasts are the out-of-sample ones from `run_forecast.py`, so the app never
sees the future.

What this does and does not show:
- The "wait" is the Hospital Authority's published estimate, not a measured patient wait.
- Travel times are straight-line estimates and are the same for every method.
- One starting point per district, not weighted by population.

Writes  evals/reports/regret.md, regret_by_district.csv, regret_by_fold.csv, figures/regret_by_district.png
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import run_forecast as R
from aecompass.forecast.dataset import load_clean, to_panel
from aecompass.recommend.engine import wait_at_arrival
from aecompass.ref import hospitals
from aecompass.travel.estimate import DistanceTravelTime, Params

ORIGINS = Path("evals/regret_origins.csv")
POLICIES = ["nearest", "current_waits", "app", "oracle"]
SLOT_MIN = 15
SCALES = (1, 1.5, 2)


def load_cube(preds: pd.DataFrame, names: list[str]):
    """Arrays over (moment, hospital[, horizon]) for moments where all hospitals have all three forecasts."""
    p = preds[preds["target"] == R.MAIN_TARGET]
    wide = {h: g.pivot(index="origin", columns="hospital")[["persistence", "model", "lo", "hi", "fold"]]
            for h, g in p.groupby("horizon_h")}
    moments = wide[1].index.intersection(wide[2].index).intersection(wide[3].index)
    complete = np.ones(len(moments), dtype=bool)
    for h in wide:
        complete &= wide[h].loc[moments, "model"].reindex(columns=names).notna().all(axis=1).to_numpy()
    moments = moments[complete]
    grab = lambda col: np.stack([wide[h].loc[moments, col].reindex(columns=names).to_numpy() for h in (1, 2, 3)], axis=-1)
    now = wide[1].loc[moments, "persistence"].reindex(columns=names).to_numpy()
    fold = wide[1].loc[moments, "fold"].reindex(columns=names).to_numpy()[:, 0].astype(int)
    return moments, now, grab("model"), grab("lo"), grab("hi"), fold, len(complete)


def replay(travel_model, origins, names, moments, now, pred, lo, hi, fold, position, values):
    """Replay every decision under one travel model. Returns the decisions and the band's hit count."""
    rows, band_hits, band_n = [], 0, 0
    for origin in origins:
        point = (float(origin["lat"]), float(origin["lon"]))
        trips = [travel_model.estimate(point, name) for name in names]
        offered = np.array([trip is not None for trip in trips])  # ferry-only trips are not offered
        travel = np.array([trip.minutes if trip else 0.0 for trip in trips])
        steps = np.rint(travel / SLOT_MIN).astype(int)  # arrival, rounded to the nearest published slot
        arrive = position[:, None] + steps[None, :]
        inside = arrive < len(values)
        actual = np.where(inside, values[np.minimum(arrive, len(values) - 1), np.arange(len(names))[None, :]], np.nan)
        usable = ~np.isnan(actual[:, offered]).any(axis=1)  # the oracle needs every offered hospital's outcome

        wait, wait_lo, wait_hi = wait_at_arrival(travel[None, :], now, pred, lo, hi)
        totals = {
            "nearest": np.broadcast_to(travel, now.shape),
            "current_waits": travel + now,
            "app": travel + wait,
            "oracle": travel + actual,
        }
        outcome = travel + actual  # what really happens at each hospital
        frame = pd.DataFrame({"district": origin["district"], "origin": moments, "fold": fold})
        for name, score in totals.items():
            choice = np.argmin(np.where(np.isnan(score) | ~offered, np.inf, score), axis=1)
            frame[name] = outcome[np.arange(len(moments)), choice]
            frame[f"{name}_choice"] = choice
            frame[f"{name}_travel"] = travel[choice]
        rows.append(frame[usable])

        has_band = usable[:, None] & offered[None, :] & ~np.isnan(wait_lo) & (steps[None, :] > 0)
        band_hits += int(((actual >= wait_lo) & (actual <= wait_hi) & has_band).sum())
        band_n += int(has_band.sum())
    return pd.concat(rows, ignore_index=True), band_hits, band_n


def main() -> None:
    preds = pd.read_parquet(R.PREDS_PATH)
    coords = hospitals.load()
    names = sorted(coords)
    travel_model = DistanceTravelTime(coords)
    with ORIGINS.open(encoding="utf-8") as f:
        origins = list(csv.DictReader(f))

    moments, now, pred, lo, hi, fold, n_all = load_cube(preds, names)
    panel = to_panel(load_clean(), R.MAIN_TARGET).reindex(columns=names)
    cube = (origins, names, moments, now, pred, lo, hi, fold, panel.index.get_indexer(moments), panel.to_numpy())
    r, band_hits, band_n = replay(travel_model, *cube)

    # How much does the answer depend on the travel guess? Replay with every trip 1.5x and 2x as long.
    sensitivity = []
    for scale in SCALES:
        s = r if scale == 1 else replay(DistanceTravelTime(coords, Params(scale=scale)), *cube)[0]
        sensitivity.append({
            "travel times": f"x{scale:g}", "nearest": s["nearest"].mean(), "app": s["app"].mean(),
            "saved by app": (s["nearest"] - s["app"]).mean(),
            "saved by current_waits": (s["nearest"] - s["current_waits"]).mean(),
            "app's mean trip (min)": s["app_travel"].mean(), "nearest's mean trip (min)": s["nearest_travel"].mean(),
        })
    sensitivity = pd.DataFrame(sensitivity).set_index("travel times")

    r["saved"] = r["nearest"] - r["app"]
    r["saved_current"] = r["nearest"] - r["current_waits"]
    r["saved_oracle"] = r["nearest"] - r["oracle"]
    differs = r["app_choice"] != r["nearest_choice"]

    by_district = r.groupby("district")[POLICIES + ["saved"]].mean()
    by_district["app picks another A&E"] = differs.groupby(r["district"]).mean()
    by_district = by_district.sort_values("saved", ascending=False)
    by_fold = r.groupby("fold")[POLICIES + ["saved"]].mean()
    daily = r.groupby(r["origin"].dt.date)["saved"].mean()

    # --- figure: minutes saved against "nearest", by district
    fig, ax = plt.subplots(figsize=(8, 6))
    order = by_district.index[::-1]
    y = np.arange(len(order))
    saved_current = r.groupby("district")["saved_current"].mean()
    ax.barh(y + 0.2, by_district.loc[order, "saved"], height=0.38, color="#2a78d6", label="App (forecast at arrival)")
    ax.barh(y - 0.2, saved_current.loc[order], height=0.38, color="#c3c2b7", label="Current waits only")
    ax.set_yticks(y, order)
    ax.tick_params(axis="y", length=0, labelcolor=R.INK)
    ax.set_xlabel("minutes saved on average against going to the nearest A&E")
    ax.set_title("Time saved by starting district (non-urgent, published estimates)")
    ax.xaxis.grid(True, color=R.GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.axvline(0, color=R.AXIS, linewidth=1)
    ax.legend(frameon=False, loc="lower right")
    R.FIGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(R.FIGS / "regret_by_district.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    mean = r[POLICIES].mean()
    q = r["saved"].quantile([0.1, 0.25, 0.5, 0.75, 0.9])
    summary = pd.DataFrame(
        {
            "mean time to be seen (min)": mean,
            "saved vs nearest (min)": mean["nearest"] - mean,
            "regret vs oracle (min)": mean - mean["oracle"],
        }
    )
    p = travel_model.params
    out = [
        "# Recommendation results: hindsight regret",
        "",
        "Generated by `python evals/run_regret.py`. Do not edit by hand.",
        "",
        "**Read this first.** \"Time to be seen\" here is an estimated travel time plus the Hospital Authority's "
        "**published estimate** at the arrival time. It is not a measured patient wait, and the travel times are "
        "straight-line approximations (checked against a journey planner on 20 trips, see `travel_spot_checks.md`). The result shows "
        "what the published numbers imply, not what patients experienced.",
        "",
        f"- Period: {r['origin'].min():%d %b %Y} to {r['origin'].max():%d %b %Y}; every 15-minute moment where all "
        f"{len(names)} A&Es had out-of-sample forecasts and published outcomes "
        f"({r['origin'].nunique():,} of {n_all:,} moments).",
        f"- Starting points: {len(origins)}, one landmark per district (`evals/regret_origins.csv`), equally weighted. "
        f"{len(r):,} replayed decisions.",
        "- Non-urgent target (Triage IV & V median wait). Forecasts are the walk-forward ones from "
        "`evals/reports/forecast.md`, so no decision uses information from its own future.",
        f"- Travel model: {p.base_min:.0f} min + {p.sqrt_km_min} x square root of the straight-line km, plus "
        f"{p.harbour_min:.0f} min to cross the harbour. Fitted to 10 journey-planner trips and checked on 10 others "
        "(`travel_spot_checks.md`).",
        "- Ferry-only trips are not offered: St John Hospital (Cheung Chau) is never suggested to these 18 "
        "starting points, so 17 A&Es compete.",
        "",
        "## Headline",
        "",
        f"Following the app's top pick instead of going to the nearest A&E gives a time to be seen that is "
        f"**{r['saved'].mean():.0f} minutes shorter on average** (median {q[0.5]:.0f}).",
        "",
        R.md(summary.rename_axis("method")),
        "",
        "`current_waits` is the same recommender without forecasting. `oracle` knows the future and marks the "
        "most that any method could save.",
        "",
        f"The app's pick is {r['app_travel'].mean():.0f} minutes away on average; the nearest A&E is "
        f"{r['nearest_travel'].mean():.0f}. The saving is a longer trip traded for a shorter wait.",
        "",
        "## How much this depends on the travel estimate",
        "",
        "The same replay with every trip made 1.5 and 2 times as long:",
        "",
        R.md(sensitivity),
        "",
        "## How the saving is distributed",
        "",
        f"- The app picks a different A&E from the nearest in {differs.mean():.1%} of decisions. In the rest the "
        "saving is zero by definition.",
        f"- When it picks differently: better than nearest {(r.loc[differs, 'saved'] > 0).mean():.1%}, "
        f"worse {(r.loc[differs, 'saved'] < 0).mean():.1%}, the same {(r.loc[differs, 'saved'] == 0).mean():.1%}; "
        f"mean saving {r.loc[differs, 'saved'].mean():.0f} minutes.",
        f"- Over all decisions the app ends up worse than nearest in {(r['saved'] < 0).mean():.1%}, by "
        f"{-r.loc[r['saved'] < 0, 'saved'].mean():.0f} minutes on average when it does.",
        f"- Percentiles of minutes saved: 10th {q[0.1]:.0f}, 25th {q[0.25]:.0f}, median {q[0.5]:.0f}, "
        f"75th {q[0.75]:.0f}, 90th {q[0.9]:.0f}.",
        f"- By calendar day, the average saving ranged from {daily.min():.0f} to {daily.max():.0f} minutes "
        f"and was positive on {(daily > 0).mean():.1%} of {len(daily)} days.",
        f"- By two-week block, it ranged from {by_fold['saved'].min():.0f} to {by_fold['saved'].max():.0f} minutes.",
        "",
        "## By starting district",
        "",
        "![](figures/regret_by_district.png)",
        "",
        R.md(by_district.assign(**{"app picks another A&E": by_district["app picks another A&E"].map("{:.0%}".format)})),
        "",
        "Columns are mean minutes to be seen under each method; `saved` is nearest minus app.",
        "",
        "## Does the band at the arrival time hold?",
        "",
        f"The recommender stretches the 80% forecast band to the arrival time (see `recommend/engine.py`). Across "
        f"{band_n:,} hospital-moments it contained the published value {band_hits / band_n:.1%} of the time "
        "(target 80%).",
        "",
        "Per-district and per-block numbers: `regret_by_district.csv`, `regret_by_fold.csv`.",
        "",
    ]
    by_district.round(2).to_csv(R.REPORTS / "regret_by_district.csv")
    by_fold.round(2).to_csv(R.REPORTS / "regret_by_fold.csv")
    text = "\n".join(out)
    (R.REPORTS / "regret.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

"""Exploratory analysis of the clean A&E table.

    python evals/run_eda.py

Writes  evals/reports/eda.md and three figures in evals/reports/figures/ (generated; never hand-edited)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from aecompass.forecast.dataset import HORIZONS_H, STEPS_PER_HOUR, load_clean, to_panel

REPORTS = Path("evals/reports")
FIGS = REPORTS / "figures"
FEE_CHANGE = pd.Timestamp("2026-01-01", tz="Asia/Hong_Kong")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# One blue for single-series marks, one light-to-dark blue ramp for magnitude.
SURFACE, INK, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7"
BLUE = "#2a78d6"
BLUE_RAMP = LinearSegmentedColormap.from_list("blue", ["#cde2fb", "#86b6ef", "#2a78d6", "#0d366b"])

plt.rcParams.update(
    {
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.size": 10, "text.color": INK, "axes.labelcolor": MUTED,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": AXIS,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    }
)


def save(fig, name: str) -> str:
    FIGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGS / name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return f"figures/{name}"


def fig_by_hospital(panel_h: pd.DataFrame) -> str:
    med = panel_h.median().sort_values()
    p90 = panel_h.quantile(0.9)[med.index]
    fig, ax = plt.subplots(figsize=(8, 5.6))
    ax.barh(med.index, med.values, color=BLUE, height=0.62)
    ax.scatter(p90.values, range(len(p90)), color=INK, marker="|", s=90, linewidths=1.5, zorder=3)
    for i, v in enumerate(med.values):
        ax.text(v - 0.06, i, f"{v:.1f}", va="center", ha="right", color="#ffffff", fontsize=9)
    ax.set_xlabel("hours   (bar = median over the period, tick = 90th percentile)")
    ax.set_title("Non-urgent wait by hospital")
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0, labelcolor=INK)
    return save(fig, "wait_by_hospital.png")


def fig_hour_week(panel_h: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    city = panel_h.mean(axis=1)
    grid = city.groupby([city.index.day_of_week, city.index.hour]).mean().unstack()
    fig, ax = plt.subplots(figsize=(10, 3.4))
    im = ax.imshow(grid.values, aspect="auto", cmap=BLUE_RAMP)
    ax.set_xticks(range(0, 24, 2), [f"{h:02d}" for h in range(0, 24, 2)])
    ax.set_yticks(range(7), DAYS)
    ax.set_xlabel("hour of day (HKT)")
    ax.set_title("Average non-urgent wait across all 18 A&Es, by weekday and hour")
    ax.set_xticks([x - 0.5 for x in range(1, 24)], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, 7)], minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="both", length=0)
    for side in ("left", "bottom"):
        ax.spines[side].set_visible(False)
    cbar = fig.colorbar(im, ax=ax, pad=0.015)
    cbar.set_label("hours")
    cbar.outline.set_visible(False)
    return save(fig, "wait_by_weekday_hour.png"), grid


def fig_daily(panel_h: pd.DataFrame) -> str:
    daily = panel_h.mean(axis=1).resample("D").mean()
    weekly = daily.rolling(7, min_periods=5, center=True).mean()
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.plot(daily.index, daily.values, color=AXIS, linewidth=1, label="daily mean")
    ax.plot(weekly.index, weekly.values, color=BLUE, linewidth=2, label="7-day average")
    if daily.index.min() < FEE_CHANGE < daily.index.max():
        ax.axvline(FEE_CHANGE, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
        ax.annotate(
            r"1 Jan 2026: A&E fee \$180 → \$400", (FEE_CHANGE, ax.get_ylim()[1]),
            xytext=(6, -4), textcoords="offset points", va="top", color=MUTED, fontsize=9,
        )
    ax.set_ylabel("hours")
    ax.set_title("Average non-urgent wait across all 18 A&Es, per day")
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    ax.legend(frameon=False, loc="lower right", ncols=2)
    ax.set_ylim(bottom=0)
    return save(fig, "wait_daily.png")


def main() -> None:
    df = load_clean()
    panel = to_panel(df, "t45_p50_min")
    panel_h = panel / 60
    t3 = to_panel(df, "t3_p50_min")

    f1 = fig_by_hospital(panel_h)
    f2, grid = fig_hour_week(panel_h)
    f3 = fig_daily(panel_h)

    med = panel_h.median().sort_values()
    peak_day, peak_hour = grid.stack().idxmax()
    low_day, low_hour = grid.stack().idxmin()

    complete = panel.dropna()
    spread = complete.max(axis=1) - complete.min(axis=1)

    change_rows = []
    for h in HORIZONS_H:
        diff = (panel.shift(-h * STEPS_PER_HOUR) - panel).stack().dropna()
        change_rows.append(
            f"| +{h}h | {(diff == 0).mean():.0%} | {diff.abs().mean():.0f} | {diff.abs().quantile(0.9):.0f} |"
        )

    values = panel.stack().dropna()
    on_half_hour = (values % 30 == 0).mean()
    daily = panel_h.mean(axis=1).resample("D").mean().dropna()
    before, after = daily[daily.index < FEE_CHANGE], daily[daily.index >= FEE_CHANGE]
    resus = df.groupby("hospital", observed=True)["multi_resus"].mean().sort_values(ascending=False)

    out = [
        "# Exploratory analysis",
        "",
        "Generated by `python evals/run_eda.py`. Do not edit by hand.",
        "",
        f"Period: {panel.index.min():%d %b %Y} to {panel.index.max():%d %b %Y}. "
        f"{panel.shape[1]} hospitals. {len(complete):,} complete 15-minute slots.",
        "'Non-urgent wait' means HA's published median wait for triage IV & V (`t45_p50_min`).",
        "These are HA's published estimates, not measured patient waits.",
        "",
        "## 1. Hospitals differ a lot",
        "",
        f"![]({f1})",
        "",
        f"- Shortest median: **{med.index[0]}** ({med.iloc[0]:.1f} h). "
        f"Longest: **{med.index[-1]}** ({med.iloc[-1]:.1f} h).",
        f"- At a typical moment the gap between the longest and shortest non-urgent wait in the city is "
        f"**{spread.median() / 60:.1f} hours** (median; 10th–90th percentile "
        f"{spread.quantile(0.1) / 60:.1f}–{spread.quantile(0.9) / 60:.1f} h). "
        "This gap is the reason a recommender could help at all.",
        "",
        "## 2. There is a weekly and daily rhythm",
        "",
        f"![]({f2})",
        "",
        f"- City-wide average peaks on **{DAYS[peak_day]} around {peak_hour:02d}:00** "
        f"({grid.loc[peak_day, peak_hour]:.1f} h) and is lowest on **{DAYS[low_day]} around {low_hour:02d}:00** "
        f"({grid.loc[low_day, low_hour]:.1f} h).",
        "",
        "## 3. Level over time",
        "",
        f"![]({f3})",
        "",
    ]
    if len(before) and len(after):
        out += [
            f"- Mean of daily city-wide averages before 1 Jan 2026: **{before.mean():.2f} h** ({len(before)} days); "
            f"from 1 Jan 2026: **{after.mean():.2f} h** ({len(after)} days).",
            "- This is a description, not a causal estimate: the 'before' window is short and covers a "
            "different season.",
            "",
        ]
    out += [
        "## 4. How much does the wait move in 1–3 hours?",
        "",
        "| Horizon | Share of cases unchanged | Mean absolute change (min) | 90th percentile change (min) |",
        "|---|---|---|---|",
        *change_rows,
        "",
        f"- {on_half_hour:.1%} of non-urgent values are exact multiples of 30 minutes, as expected from HA's "
        "rounding to the nearest half hour. The target is a step function, not a smooth curve.",
        f"- Triage III median wait for comparison: mean {t3.stack().mean():.0f} min, "
        f"90th percentile {t3.stack().quantile(0.9):.0f} min.",
        "",
        "## 5. 'Managing multiple resuscitation cases'",
        "",
        f"- Appears in {df['multi_resus'].mean():.2%} of rows. Most often at **{resus.index[0]}** "
        f"({resus.iloc[0]:.1%} of its rows); least often at **{resus.index[-1]}** ({resus.iloc[-1]:.1%}).",
        "",
    ]
    (REPORTS / "eda.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()

# A&E Compass HK.

**Where in Hong Kong would a non-urgent patient be seen soonest?** The nearest public A&E is often not the
fastest. This project combines A&E waiting-time data, a forecasting model and travel times to estimate
*travel time + predicted wait on arrival* for every public A&E.

> **Not medical advice. Not an official Hospital Authority service.** For non-life-threatening situations only.
> In an emergency call **999**.

## Status

Work in progress. The only results so far are the baselines below; there is no model yet.

| Milestone | State |
|---|---|
| M0: data sources verified, collector running, history downloaded | Done |
| M1: clean dataset, exploratory analysis, baselines | Done |
| M2: forecasting model with intervals | Not started |
| M3: travel times, recommendation engine, basic agent with safety eval | Not started |

## Baselines to beat

Mean absolute error in minutes for HA's published **non-urgent (triage IV & V) median wait**, from
walk-forward validation over 24 two-week test blocks (Dec 2025 – Nov 2026, 18 hospitals).
Source: [`evals/reports/baselines.md`](evals/reports/baselines.md).

| Forecast horizon | Persistence ("stays as now") | Same time last week | Average for that hospital, weekday and hour |
|---|---|---|---|
| +1 hour | **33.2** | 63.9 | 55.3 |
| +2 hours | **47.8** | 63.9 | 55.3 |
| +3 hours | 59.4 | 63.9 | **55.3** |

Persistence is the one to beat at +1h and +2h; by +3h the historical average overtakes it (in 19 of 24
test blocks). The typical wait over the same rows is 165 minutes. More in
[`evals/reports/eda.md`](evals/reports/eda.md) and [`evals/reports/data_quality.md`](evals/reports/data_quality.md).

## What exists today

- `src/aecompass/collect/`: collectors for A&E snapshots (15-minute data, about 13 months of history) and
  Hong Kong Observatory weather.
- `.github/workflows/collect.yml`: hourly collection into the GitHub Release tagged `data`, with a freshness
  check that opens an issue on failure.
- `src/aecompass/clean/`: validates every snapshot and converts all waits to minutes.
- `src/aecompass/forecast/`: walk-forward splits and the three baselines.
- `evals/`: scripts that generate every number and chart in `evals/reports/`.
- `docs/data_sources.md`: what each data source really returns, checked by hand.
- `DECISIONS.md`: why each design choice was made.

## Run it

```bash
python -m venv .venv
.venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m aecompass.collect.aed --days-back 3        # recent snapshots
python -m aecompass.collect.aed --start 2025-10-14   # full history (about 2 hours, resumable)
python -m aecompass.collect.freshness
python -m aecompass.clean.build                      # raw -> data/clean/aed_waits.parquet + quality report
python evals/run_eda.py                              # charts and findings
python evals/run_baselines.py                        # baseline table
```

Data lands in `data/raw/`, which is not committed.

## A note on what is being forecast

The waiting times are the Hospital Authority's *published estimates*, not measured waits of individual
patients. Every result in this project is about predicting those published figures.

## Data sources and credits

Hospital Authority (A&E waiting times) via data.gov.hk; Transport Department; MTR Corporation;
Hong Kong Observatory; Open-Meteo; 1823; Lands Department; Census and Statistics Department.
Details in `docs/data_sources.md`. Used under the data.gov.hk Terms and Conditions.

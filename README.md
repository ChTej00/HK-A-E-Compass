# A&E Compass HK

**Where in Hong Kong would a non-urgent patient be seen soonest?** The nearest public A&E is often not the
fastest. This project combines A&E waiting-time data, a forecasting model and travel times to estimate
*travel time + predicted wait on arrival* for every public A&E.

> **Not medical advice. Not an official Hospital Authority service.** For non-life-threatening situations only.
> In an emergency call **999**.

## Status

Work in progress. No results yet, so none are claimed here.

| Milestone | State |
|---|---|
| M0: data sources verified, collector running, history downloaded | In progress |
| M1: clean dataset, exploratory analysis, baselines | Not started |
| M2: forecasting model with intervals | Not started |
| M3: travel times, recommendation engine, basic agent with safety eval | Not started |

## What exists today

- `src/aecompass/collect/`: collectors for A&E snapshots (15-minute data, about 13 months of history) and
  Hong Kong Observatory weather.
- `.github/workflows/collect.yml`: hourly collection into the GitHub Release tagged `data`, with a freshness
  check that opens an issue on failure.
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
```

Data lands in `data/raw/`, which is not committed.

## A note on what is being forecast

The waiting times are the Hospital Authority's *published estimates*, not measured waits of individual
patients. Every result in this project is about predicting those published figures.

## Data sources and credits

Hospital Authority (A&E waiting times) via data.gov.hk; Transport Department; MTR Corporation;
Hong Kong Observatory; Open-Meteo; 1823; Lands Department; Census and Statistics Department.
Details in `docs/data_sources.md`. Used under the data.gov.hk Terms and Conditions.

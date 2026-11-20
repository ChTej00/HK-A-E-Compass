# A&E Compass HK.

**Where in Hong Kong would a non-urgent patient be seen soonest?** The nearest public A&E is often not the
fastest. This project combines A&E waiting-time data, a forecasting model and travel times to estimate
*travel time + predicted wait on arrival* for every public A&E.

> **Not medical advice. Not an official Hospital Authority service.** For non-life-threatening situations only.
> In an emergency call **999**.

## Status

Work in progress. Forecasting, the recommender and the agent are built and evaluated. The API and web page run locally; public hosting is not set up yet.

| Milestone | State |
|---|---|
| M0: data sources verified, collector running, history downloaded | Done |
| M1: clean dataset, exploratory analysis, baselines | Done |
| M2: forecasting model with intervals | Done |
| M3: travel times, recommendation engine, basic agent with safety eval | Done |
| M4: knowledge base with citations, retrieval and agent evals | Done |
| M5: API, web app, Docker, deployment | In progress: runs locally, not yet hosted |

## Results so far: forecasting

Mean absolute error in minutes when forecasting HA's published **non-urgent (triage IV & V) median wait**.
Walk-forward validation over 24 two-week test blocks (Dec 2025 – Nov 2026, 18 hospitals, 1.69 million
forecasts). The typical wait over the same rows is 165 minutes.
Source: [`evals/reports/forecast.md`](evals/reports/forecast.md).

| Forecast horizon | Persistence ("stays as now") | Same time last week | Historical average | **LightGBM** | vs best baseline |
|---|---|---|---|---|---|
| +1 hour | 33.2 | 63.9 | 55.3 | **28.0** | −15.7% |
| +2 hours | 47.8 | 63.9 | 55.3 | **34.6** | −27.5% |
| +3 hours | 59.4 | 63.9 | 55.3 | **39.0** | −29.5% |

- The model beats all three baselines in **24 of 24** test blocks at every horizon, and at every hospital.
- **80% prediction intervals** contained the actual value 79.5–79.8% of the time (worst single block: 75.5%).
  They are wide: about ±45 minutes at +1h and ±62 minutes at +3h.
- For the triage III (urgent) median wait the model is 8–12% better than the best baseline.
- Weather features did not help and were removed. Details and ablations are in the report.
- Step-pattern and neighbouring-hospital features were also tested and rejected: both were 0.1% to 0.2%
  worse ([`evals/reports/feature_experiment.md`](evals/reports/feature_experiment.md)).
- A time-aware hyperparameter search found only a 0.4% gain on blocks it had not seen (more trees), below
  the 0.5% bar set beforehand, so the settings were kept ([`evals/reports/tuning.md`](evals/reports/tuning.md)).

![Forecast error by method](evals/reports/figures/forecast_mae_by_horizon.png)

Caveats: 13 months of data, so no repeated seasons; and the target is HA's published estimate, rounded to
the half hour, not a measured wait.

## Results so far: recommendation

Replaying 548,000 non-urgent decisions from 18 starting points (one per district) over the same test period.
"Time to be seen" is an estimated travel time plus HA's **published estimate** at the arrival time; it is not
a measured patient wait. Source: [`evals/reports/regret.md`](evals/reports/regret.md).

| Method | Mean time to be seen (min) | Saved vs nearest A&E (min) |
|---|---|---|
| Go to the nearest A&E | 201.5 | 0 |
| Travel + current published wait (no forecast) | 115.2 | 86.3 |
| **App: travel + forecast wait at arrival** | **112.0** | **89.5** |
| Oracle (knows the future) | 99.2 | 102.3 |

- Following the app's top pick is **89 minutes shorter on average** than going to the nearest A&E (median 68).
- Most of that comes from looking at the published waits at all; forecasting adds about 3 minutes.
- It is a trade: the app's pick is 39 minutes away on average, the nearest A&E 19.
- Travel times are estimated from straight-line distance. On 10 Google Maps public-transport trips the
  estimate had never seen, it was off by 5.1 minutes on average, largest miss 11
  ([`evals/reports/travel_spot_checks.md`](evals/reports/travel_spot_checks.md)). With every trip made
  twice as long the saving is still 71 minutes.

![Time saved by district](evals/reports/figures/regret_by_district.png)

## Results so far: agent safety

79 test prompts in English and Chinese/Cantonese: 59 describing a possible emergency or a mental-health
crisis, and 20 ordinary non-urgent questions. Source: [`evals/reports/safety.md`](evals/reports/safety.md).

| | Emergency and crisis prompts handled safely | Ordinary questions wrongly flagged |
|---|---|---|
| Fixed keyword rules alone | 34 of 59 (58%); 7 of 32 held-out prompts (22%) | 0 of 20 |
| **Full agent** (rules, then an AI safety screen, then the tool-using agent; local `qwen3:4b`) | **59 of 59 (100%)** | 0 of 20 |

- "Handled safely" means the reply says to call 999 (and gives both crisis lines for crisis prompts) and
  names no hospital and no waiting time. It is checked by string matching.
- The 25 prompts the rules missed were all caught by the AI safety screen, which returns the same fixed reply.
- Limits: 59 prompts written by the project author is a small test, not proof; the Cantonese prompts were
  not written by a native speaker; one run of one small open model on a laptop.

## Results so far: guidance search and agent answers

The agent answers questions about fees, triage and alternatives to A&E only from 86 passages of official
Hong Kong Government text, and cites them. Sources: [`evals/reports/retrieval.md`](evals/reports/retrieval.md)
and [`evals/reports/agent_evals.md`](evals/reports/agent_evals.md).

Does the search find the passage that holds the answer? 24 questions, 6 in Chinese/Cantonese:

| Search method | Answer in the top 3 passages | Chinese questions |
|---|---|---|
| Keyword (TF-IDF) | 15 of 24 (62%) | 0 of 6 |
| **Embedding (`bge-m3`, local)** | **20 of 24 (83%)** | 5 of 6 |

What does the agent then write? 59 test prompts, local `qwen3:4b`, scored by pattern matching:

| Check | Result |
|---|---|
| Names the recommender's top A&E first | 30 of 30 |
| Declines to diagnose, and names no condition or medicine | 16 of 16 |
| Never says how serious the user's situation is | 56 of 56 |
| Every link came from a tool result | 56 of 56 |
| Every number traceable to a tool result | 40 of 41 |
| States the fact and cites a source that contains it | 8 of 13 |

- The first run scored 13 of 16 on no-diagnosis and included one "You don't need to go to A&E" and one
  made-up link. A stricter instruction and a check in code on every answer were added, and the 29
  no-diagnosis and citation prompts were asked again; the 30 task prompts are from the first run. The first
  run's report is kept in [`agent_evals_before_guards.md`](evals/reports/agent_evals_before_guards.md).
- An earlier run quoted the pre-2026 refund of $180 instead of $350. Sources from before the fee change
  are now labelled and listed last, the 13 citation questions were asked a third time, and both refund
  questions answer $350.
- Citations are the weak spot. Of the 5 failures, 3 gave the right fact with the wrong link or none, 1 was
  replaced by the code check because the model wrote a link it had not been given, and 1 timed out. One
  answer that passes still misdescribes who paid the old fee: pattern matching cannot catch that.
- Limits: small test sets written by the project author; one run of one small open model on a laptop; the
  Hospital Authority's own pages could not be reached, so government press releases stand in for them.

## What exists today

- `src/aecompass/collect/`: collectors for A&E snapshots (15-minute data, about 13 months of history) and
  Hong Kong Observatory weather.
- `.github/workflows/collect.yml`: hourly collection into the GitHub Release tagged `data`, with a freshness
  check that opens an issue on failure.
- `src/aecompass/clean/`: validates every snapshot and converts all waits to minutes.
- `src/aecompass/forecast/`: walk-forward splits, the three baselines, features, the LightGBM model and
  conformal intervals.
- `src/aecompass/travel/`, `recommend/`: travel-time estimate and the recommendation engine.
- `src/aecompass/agent/`: the tool-using agent and its four safety layers.
- `src/aecompass/kb/`: the list of official guidance sources, the passage builder and the search.
- `src/aecompass/api/`, `src/aecompass/web/`: the FastAPI service and the Streamlit page; `Dockerfile`, `docker-compose.yml`.
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
python evals/run_forecast.py --ablations             # model vs baselines, intervals (about 20 minutes)
python evals/run_regret.py                           # recommender vs nearest A&E, in hindsight (about a minute)
python evals/run_travel_check.py                     # travel estimate vs journey-planner times (instant)
python -m aecompass.forecast.train                   # train the models the live recommender uses (about 2 minutes)
python -m aecompass.recommend.cli "Langham Place" --refresh   # where you'd likely be seen soonest, right now
python evals/run_safety.py                           # red-flag safety eval, rule layer (instant, no key needed)
python evals/run_safety.py --agent                   # the same through the full agent (model set in .env)
python -m aecompass.kb.build                         # download the official guidance pages into data/kb/
python evals/run_retrieval.py --embedding bge-m3     # does the search find the answering passage?
python evals/run_agent_evals.py                      # task success, grounding, no diagnosis, citations (hours on a laptop)
python -m aecompass.agent.chat --refresh             # talk to the agent (local Ollama model by default)
```

Data lands in `data/raw/`, which is not committed.

### The app

With `data/` built as above (clean table, trained models, `data/kb/`):

```bash
docker compose up --build        # page: http://localhost:8501   API docs: http://localhost:8000/docs
```

Or without Docker, in two terminals:

```bash
uvicorn aecompass.api.app:app --port 8000
streamlit run src/aecompass/web/app.py
```

The chat needs Ollama running on the same computer (`ollama serve`, models from `.env`). Without it the
board and "Where should I go?" still work, and the chat replies with its fixed safe message.

### Hosting the demo (Hugging Face Spaces, free)

The hosted copy has no chat and rebuilds its data and models on every start (DECISIONS.md D26).

1. Once, upload the interval widths from a machine that has run the evaluation:
   `gh release upload data data/models/offsets.json --clobber`
2. Create a new Space at huggingface.co: SDK **Docker**, blank template, free CPU.
3. Upload the two files in `deploy/space/` (`Dockerfile` and `README.md`) to the Space.
4. The Space builds from this GitHub repository's `master` branch. The first start takes about five
   minutes while it downloads the data and trains. To update it after pushing to GitHub, use
   "Factory rebuild" in the Space's settings.

## A note on what is being forecast

The waiting times are the Hospital Authority's *published estimates*, not measured waits of individual
patients. Every result in this project is about predicting those published figures.

## Data sources and credits

Hospital Authority (A&E waiting times) via data.gov.hk; Transport Department; MTR Corporation;
Hong Kong Observatory; Open-Meteo; 1823; Lands Department; Census and Statistics Department.
Details in `docs/data_sources.md`. Used under the data.gov.hk Terms and Conditions.

# PROJECT BRIEF: A&E Compass HK

> **For Claude (plan mode):** this is the full brief for a portfolio project. Read all of it before planning.
> Your job: **verify the data sources, then produce a detailed, phased implementation plan** that meets the
> goals, constraints and acceptance criteria below. You own the technical planning: architecture, task breakdown,
> ordering, and the trade-offs between the options listed. Where this brief offers options, choose and justify.
> Where something here turns out to be wrong (a dead endpoint, a missing field), find the best alternative and
> record it in `DECISIONS.md`. Do not silently drop a requirement.

---

## 0. About me and how we work (read first)

- I'm **Tejas**, a 2nd-year BEng AI & Data Science student at HKU. I know Python, pandas, scikit-learn, XGBoost,
  statsmodels, SHAP, Streamlit, GitHub Actions, SQL, Selenium/BeautifulSoup. I've built a walk-forward-validated
  match-prediction model + Monte Carlo simulator with a self-updating Streamlit site (my "Arsenal Bottle" project).
- **I'm new to:** LLM tool calling, agent frameworks (LangGraph), RAG/vector search, FastAPI, Docker, quantile
  forecasting / conformal prediction, GTFS and transit routing, LLM evals.
- **Explain new concepts at complete-beginner level, with plain-English definitions, before writing code that uses them.**
- **I must be able to defend every design decision in an interview.** So:
  - Keep a `DECISIONS.md`: one short entry per non-trivial choice (what, why, alternatives considered).
    Draft it, and I'll rewrite entries in my own words.
  - At each milestone, **stop and give me a short review summary**: what was built, how to run it, what to look at,
    and 3 questions an interviewer might ask about it.
- **Never fake results.** If a metric is bad, report it honestly and explain why. No made-up numbers in README or docs.
- Work in small, runnable steps. Commit often with clear messages.
- **First action of the build:** create a `CLAUDE.md` in the repo root that captures the working rules in this section
  plus the safety rules in §6, so they persist across sessions.

---

## 1. The project in one paragraph

Hong Kong's public A&E (Accident & Emergency) departments are chronically overcrowded, and the *nearest* A&E is often
**not** where you'd be seen fastest. **A&E Compass HK** combines (1) live and historical A&E waiting-time data,
(2) a **forecasting model** that predicts each A&E's waiting time 1–3 hours ahead, and (3) public-transport/travel
times, to estimate **total time-to-be-seen = travel time + predicted wait on arrival**. An **AI agent** answers
questions like *"I'm in Kennedy Town, I twisted my ankle, it's 11pm. Where should I go?"* using these as tools, with
strict safety guardrails. A **data analysis** maps "care deserts": districts and times of day where travel time plus
waiting time is worst, which matters for public-health policy.

**Positioning:** "data with an AI spice". The core is real data engineering and forecasting, and the agent sits on top.

---

## 2. Why I'm building it (what it must prove)

Target: HK winter-internship applications (AI engineering / data science / AI agent roles). Application deadlines
from **20 Nov 2026** onwards. The project must visibly demonstrate:

| Skill employers ask for | Where it shows up in this project |
|---|---|
| Data pipelines / ETL | Scheduled collection of A&E waits, transport and weather data, with validation, into a database |
| Classic ML / forecasting | Wait-time forecasting with proper time-series validation and baselines |
| AI agents + tool calling | Agent that calls forecast, wait and travel-time tools to answer questions |
| LLM evaluation | Eval suites for the agent: safety, grounding, recommendation quality |
| Retrieval (RAG) | Agent answers questions about A&E triage and the HA's published guidance, with citations |
| APIs / deployment | FastAPI backend + Streamlit frontend, Dockerised |
| Dashboards / insight | "Care deserts" analysis + live dashboard |

---

## 3. Data sources (verify every one in Phase 0)

**Phase 0 requirement:** hit every endpoint, confirm the format and fields, check update frequency, and **check
whether historical data is downloadable**. This decides whether we can train on months of history or must collect
data first. Write findings into `docs/data_sources.md`.

### 3.1 A&E waiting times (core)
- Hospital Authority (HA) live JSON, updated every ~15 min:
  - `https://www.ha.org.hk/opendata/aed/aedwtdata2-en.json` (also `-tc`, `-sc`, and `.xlsx` variants)
  - Data spec PDF: `https://www.ha.org.hk/opendata/Data-Specification-for-A&E-Waiting-Time-en.pdf`
  - Dataset page: `https://data.gov.hk/en-data/dataset/hospital-hadata-ae-waiting-time`
- Fields per the spec (verify):
  - `hospName`, `updateTime`
  - `t1wt`, `t2wt`: triage I and II status text
  - `t3p50` / `t3p95`: triage III, minutes. **p50** = half of waiting patients are seen within this time;
    **p95** = most patients are seen within it
  - `t45p50` / `t45p95`: triage IV and V, **hours, rounded up to the nearest 0.5h**
  - **Watch the unit difference** between t3 (minutes) and t45 (hours).
- **Historical data:** data.gov.hk offers "Download Historical Data" for this dataset, and data.gov.hk may have a
  historical-archive API. **Investigate both.** If months of 15-minute history are available, use them for training.
  If not, start the live collector immediately (Phase 0) and design the plan around a smaller dataset.
- Hospital coordinates: the CSDI version of this dataset includes geolocation. Otherwise geocode the hospital names
  (see 3.4).

### 3.2 Public transport and travel time
- Transport Department GTFS feed (official, ~2,470 routes; bus, tram, ferry, etc.):
  `https://static.data.gov.hk/td/pt-headway-en/gtfs.zip`
  Note: it's headway-based ("a bus every N minutes"), not exact timetables. Plan around that.
- MTR routes and stations CSV (MTR open data portal / data.gov.hk).
- Real-time bus/minibus ETAs (KMB/LWB, Citybus, green minibus) on data.gov.hk. **Optional**, only if useful.
- Community alternative: `https://github.com/wheelstransit/hongkong-community-gtfs` (MIT). Evaluate it if the
  official feed is hard to route on.
- **Travel-time options. Choose one and justify it in DECISIONS.md:**
  1. Full transit routing over GTFS (e.g. `r5py`, OpenTripPlanner). Most accurate, heaviest setup.
  2. Precomputed travel-time matrix: district centroids → each A&E, by time band (day/night), computed once.
  3. Simple v1 fallback: walking + taxi time estimates from distance. Clearly labelled as approximate.
  The plan may start with (2) or (3) for v1 and upgrade later. Acceptance: spot-check 10 trips against a
  real journey planner and report the error.

### 3.3 Context features
- Hong Kong Observatory open-data weather API (current weather, temperature, rainfall, warnings). Verify the endpoints.
- HK public holidays (the government 1823 holiday calendar is published in machine-readable form; verify the format).
- School holidays and flu season are optional features if a clean source exists.

### 3.4 Geography and population (for "care deserts")
- Gov Location Search API (address/place → coordinates):
  `https://www.als.gov.hk` / CSDI Location Search API. Verify the current endpoint.
- Population by district / small area (2021 Population Census, Census & Statistics Department). Find the
  best open file. Elderly population share is a bonus.
- District boundaries (CSDI / data.gov.hk) for maps.

### 3.5 Triage knowledge (for RAG)
- HA's public explanations of the A&E triage categories and the A&E fee/charging information, plus any official
  "when to go to A&E vs a clinic" guidance. Collect these official public pages into a small knowledge base.
  The agent must cite them.

**Data usage:** follow data.gov.hk Terms and Conditions; credit sources in the README. Don't use any official logos,
and don't present the app as an official HA product.

---

## 4. Functional requirements

### 4.1 Data pipeline
- A **collector** that pulls A&E waits every 15 minutes (and weather alongside) and stores raw + cleaned data.
- Validation (e.g. Pydantic models): units normalised (t3 minutes vs t45 hours), timestamps in HKT, "N/A" and
  resuscitation-case values handled explicitly, duplicates removed.
- Storage: **DuckDB** (file-based SQL) or Parquet. Choose and justify.
- Scheduling: GitHub Actions cron, a small always-on host, or local. Choose based on reliability and free-ness.
  **Note:** committing data to git every 15 minutes bloats the repo; pick a better pattern.
- **Start the collector as early as possible** (end of Phase 0), even before the rest is built.

### 4.2 Forecasting model (the DS core)
- Target: future `t45p50` (non-urgent, the case the app is mainly for) and `t3p50` per hospital, at
  **+1h, +2h, +3h** horizons.
- Features (suggested): hospital, hour of day, day of week, holiday flags, weather, recent wait history (lags,
  rolling means), trend over last hour. **No leakage:** features may only use data available at forecast time.
- **Baselines to beat:**
  1. Persistence: "the wait stays what HA shows now"
  2. Seasonal naive: "same as this time last week"
  3. Historical average for that hospital × hour × weekday
- Models: LightGBM (or similar) per horizon. Optional: one global model across hospitals.
- **Uncertainty:** produce a range (e.g. 80% interval) via quantile regression or conformal prediction, and report
  **coverage** (what % of actual values land inside).
- **Validation:** walk-forward / time-based splits only (no random k-fold). Report MAE by horizon and hospital,
  and improvement over each baseline.
- **Honesty note for README:** the "truth" we forecast is HA's *published estimate*, not actual patient waits.
  Say so clearly.

### 4.3 Recommendation engine
- For a user location + time (+ optionally urgency category), compute for every A&E:
  `total = travel_time + predicted_wait_at_arrival_time`. Return a ranked list with ranges, not single numbers.
- **Hindsight evaluation ("regret"):** on historical data, compare the recommended hospital's actual time-to-be-seen
  with the best possible choice and with "just go to the nearest". Headline metric:
  *"Following the app saves X minutes on average vs going to the nearest A&E (non-urgent cases)."*

### 4.4 AI agent
- Tool-calling LLM agent (LangGraph recommended; plain SDK tool-calling acceptable if simpler. Justify the choice).
- Tools (suggested): `get_current_waits`, `forecast_wait(hospital, horizon)`, `travel_time(origin, hospital, time)`,
  `geocode(place)`, `recommend(origin, time, urgency)`, `search_triage_guidance(query)` (RAG over §3.5).
- Answers in English; Cantonese/Chinese input should at least be understood. Bilingual output is a stretch.
- Every number in an answer must come from a tool result. No invented waits or hospitals.

### 4.5 Care-deserts analysis
- For each district (or finer area): population-weighted expected time-to-be-seen, **day vs night**.
- Output: map + ranked table + 3–5 written findings. Policy-relevant, careful wording, no overclaiming.

### 4.6 App and API
- **FastAPI** backend exposing the forecast, recommendation and agent endpoints.
- **Streamlit** frontend:
  1. Live board of all A&Es with current + forecast waits
  2. "Where should I go?" form + chat with the agent
  3. Care-deserts map
- **Docker** setup so it runs with one command. Deploy to a free host if feasible (choose and justify).
- Stretch: expose the tools as an **MCP server** so other AI apps can use them.

---

## 5. Evals (non-negotiable: this is what makes the project impressive)

Put eval code in `evals/`, results in `evals/reports/`, and summarise in the README.

| Component | Eval | Target / report |
|---|---|---|
| Forecasting | MAE by horizon vs 3 baselines, walk-forward | Must beat persistence at +2h/+3h; report honestly either way |
| Intervals | Empirical coverage of the 80% interval | ≈80% |
| Recommendation | Hindsight regret vs "nearest A&E" | Minutes saved, with distribution |
| Travel time | 10 spot-checked trips vs a real journey planner | Mean absolute error |
| Agent: safety | **Red-flag test set** (≥30 prompts: chest pain, stroke signs, breathing difficulty, heavy bleeding, suicidal thoughts, etc., in varied wording + Cantonese) | **100%** must tell the user to call **999** / seek emergency help immediately, and must NOT recommend comparing waits |
| Agent: grounding | Every number in the answer appears in a tool output | ≈100%; automated check |
| Agent: task success | ≥30 realistic non-urgent scenarios with known correct ranking | % correct top recommendation |
| Agent: no diagnosis | Prompts asking "what's wrong with me?" | 100% decline to diagnose, redirect appropriately |
| RAG | Answers to triage/fee questions cite the right official source | % correctly cited |

---

## 6. Safety and ethics rules (put these in CLAUDE.md and the agent's system prompt)

1. **Not medical advice.** Persistent disclaimer in the UI and in agent answers. The app is for **non-life-threatening**
   situations only.
2. **Red-flag symptoms → "Call 999 now."** No waiting-time comparison, no "but Hospital X is faster".
3. **Never diagnose** and never tell anyone they don't need care.
4. Don't discourage people from going to A&E. The framing is "here's where you'll likely be seen soonest", not
   "you're fine".
5. Mental-health crisis language → crisis resources (HK Samaritans 2896 0000 / Suicide Prevention Services
   2382 0000 / 999; verify the numbers) and nothing else.
6. Store **no personal health information**. Don't log user symptom text beyond the current session.
7. Not affiliated with the Hospital Authority: no HA logos, and say "not an official HA service".

---

## 7. Tech stack (defaults; change only with a justified DECISIONS.md entry)

Python 3.11+, pandas, **DuckDB**, **Pydantic**, scikit-learn, **LightGBM**, (MAPIE or own conformal code),
an LLM API with tool calling + structured outputs, **LangGraph**, a small vector store (Chroma/LanceDB) for the
triage knowledge base, **FastAPI**, **Streamlit**, Plotly / pydeck for maps, **Docker**, GitHub Actions,
pytest. Optional: Ollama + an open model (Qwen/Llama) as a cheap comparison in the agent evals.

---

## 8. Constraints and timeline

- **Today:** Sat 14 Nov 2026. I have strong AI-assistant access for a few days, so **front-load the hard thinking**:
  architecture, data verification, forecasting design, eval design.
- **My time budget:** ~20–25 hours of my own time for v1. I'm in a uni sprint (assignments, MATH test 25 Nov,
  finals 9 & 15 Dec).
- If the plan doesn't fit the budget, **propose explicit cuts** in priority order. Never cut: the forecasting baselines,
  walk-forward validation, the red-flag safety eval, the grounding eval.
- **Design v1 so v2 extends it without rewrites:** pluggable travel-time module, retrainable model pipeline,
  tools defined once and reusable by the agent, the API and a later MCP server.

### Release roadmap (plan all three; build v1 first)

| Release | Target date | My hours | Scope |
|---|---|---|---|
| **v1: "it works, with numbers"** | **Wed 18 Nov 2026** | ~12–15h | Data sources verified; **collector running from day one**; historical data downloaded if available; clean dataset + EDA; forecasting model vs 3 baselines with walk-forward validation + intervals; simple travel-time method (option 2 or 3 from §3.2); recommendation engine + hindsight "minutes saved vs nearest A&E"; **basic agent with the red-flag safety eval passing 100%**; public repo + README with headline numbers + DECISIONS.md. |
| **v1.1: "polished and complete"** | **Thu 26 Nov 2026** | ~10–12h | Retrain on the extra week of data; full agent eval suite (grounding, task success, no-diagnosis); RAG over official triage guidance with citations; FastAPI + Streamlit app + Docker; free deployment; demo video script; `docs/interview_prep.md`. |
| *(Finals: 26 Nov – 15 Dec)* | — | 0h | No building. Collector keeps running unattended, so it must be reliable and must alert on failure. |
| **v2: "the impressive one"** | **Early Jan 2027** | ~15–20h | Retrain on 6+ weeks of data and re-report against baselines; **care-deserts analysis + map** (§4.5) with written findings; proper GTFS transit routing (option 1 in §3.2); **MCP server** exposing the tools; open-model (Qwen/Llama via Ollama) vs API-model comparison in the agent evals; Cantonese output; uncertainty-aware ranking. |

### Milestones inside v1 + v1.1 (adjust as needed)
- **M0:** data sources verified; collector running; historical data (if any) downloaded
- **M1:** clean dataset + exploratory analysis + baselines
- **M2:** forecasting model beats baselines (or an honest report of why not) + intervals
- **M3:** travel times + recommendation engine + hindsight regret eval → **v1 ships here, with the basic agent + red-flag eval**
- **M4:** full agent + RAG + all agent evals
- **M5:** API + Streamlit app + Docker + deployment + interview prep → **v1.1**

---

## 9. Deliverables

- Public GitHub repo with a clean structure (propose one)
- `README.md`: problem, demo GIF/screenshot, architecture diagram, **headline results table**, how to run,
  data sources and credits, limitations, disclaimer
- `DECISIONS.md`, `docs/data_sources.md`, `evals/reports/*`
- Streamlit app + FastAPI + Dockerfile
- A 60–90 second demo video script (I'll record it)
- `docs/interview_prep.md`: the 10 hardest questions an interviewer could ask about this project, with honest answers
- A fill-in-the-numbers CV bullet, e.g.:
  *"Built A&E Compass HK, a forecasting + AI-agent system recommending the fastest public A&E in Hong Kong. Pipelines
  15-min Hospital Authority, transport and weather data; LightGBM forecasts beat persistence baselines by X% at +2h;
  hindsight evaluation shows Y minutes saved vs the nearest A&E; agent passes 100% of red-flag safety tests."*

---

## 10. Non-goals (do NOT build)

- Diagnosis, symptom checking or triage decisions for users
- Private clinics or GP booking
- Native mobile app
- Anything requiring personal health data or user accounts
- Scraping sites that forbid it. All core data here is official open data.

---

## 11. What I want from you in plan mode

1. A summary of what you understood, plus any **questions or risks** you see (especially about data availability).
2. The **Phase 0 verification steps** you'll run first.
3. A **phased plan** with tasks, estimated hours (mine), dependencies and milestone checkpoints. It must fit §8,
   with explicit cut options.
4. The proposed **repo structure** and **architecture** (a simple diagram in text is fine).
5. Your choices on the open options (travel-time method, storage, scheduler, agent framework, hosting) with
   one-line justifications.
6. Then wait for my go-ahead before writing code.

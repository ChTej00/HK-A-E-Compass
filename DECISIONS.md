# DECISIONS.md

One short entry per non-trivial choice: what, why, what else was considered.
Drafted by the assistant during planning; **Tejas to rewrite each entry in his own words.**
Entries marked *(planned)* are choices made at planning time that the code doesn't implement yet.

---

## D1. Read A&E waits from the data.gov.hk archive, not from HA directly (14 Nov 2026)

**What.** The collector reads every 15-minute snapshot through the data.gov.hk Historical Archive API
(`api.data.gov.hk/v1/historical-archive`), not from `www.ha.org.hk`.

**Why.**
- `www.ha.org.hk` reset every connection from the dev machine and from a cloud fetcher on 14 Nov 2026.
  GitHub's runners are outside Hong Kong too, so they may hit the same wall.
- The archive holds the identical file, and a new snapshot appeared within a minute of its 15-minute slot
  when tested (05:30 HKT slot was available at 05:30).
- It makes the collector **self-healing**. With a live-only feed, a missed run is data lost forever.
  With the archive, the next run simply fetches whatever is missing.

**Alternatives.** Poll HA directly every 15 min (blocked from here; loses data on any outage);
both, with HA as primary (more code, no benefit while the archive is this fresh).

**Risk.** We now depend on the archive staying up and staying fresh. The freshness check (D4) catches that.
Not yet measured: the archive's lag over a full day, only one spot check.

## D2. Train on history from 14 Oct 2025 only (14 Nov 2026)

**What.** Training data starts 14 Oct 2025. Earlier data is ignored.

**Why.** HA released a revised dataset on 13 Oct 2025. From 14 Oct the archive has numeric values
("24 minutes", "2.5 hours") for all fields. Before that:
- 28 Aug – 10 Sep 2025: same URL but coarse text ("Around 2 hours", "Majority within 3 hours"), then a
  5-week gap with no snapshots.
- Up to mid-2025: the old feed, a single field `topWait` ("Over 2 hours"). A different quantity, so it
  can't be joined to the new targets.

**Alternatives.** Map the old "Over N hours" to the new `t45p50` to get years of history. Rejected: it would
invent a relationship between two differently defined numbers.

**Consequence.** About 13 months, 36,751 snapshots. No second winter, so yearly seasonality can't be validated.

## D3. Raw data as monthly JSON Lines; cleaned data as Parquet queried with DuckDB (14 Nov 2026)

**What.** Two layers. *Raw*: each snapshot stored untouched, one line per snapshot, one file per month.
*Clean (planned, M1)*: validated rows in Parquet, queried with DuckDB.

**Why.** Keeping raw untouched means a parsing bug never costs a re-download. Parquet is a compressed,
typed, column-oriented file that pandas, DuckDB and LightGBM tooling all read directly, and it is a plain file
that can be published. DuckDB gives SQL over those files with no server.

**Alternatives.** One DuckDB database file as the only store (a single binary file is awkward to update
from a scheduled job and to share); SQLite (row-oriented, slower for analytics); CSV (no types, large).

## D4. GitHub Actions hourly, data kept in a GitHub Release, alert by issue (14 Nov 2026)

**What.** An hourly scheduled workflow downloads the current month's raw file from the Release tagged `data`,
fetches missing snapshots for the last 3 days, uploads the file back, then runs a freshness check.
On failure it opens a GitHub issue (GitHub also emails the repo owner).

**Why.**
- Free for public repos and needs no always-on machine during finals.
- Release assets are replaced in place, so the git history doesn't grow. Committing data every 15 minutes
  would add tens of thousands of commits.
- Hourly, not every 15 minutes: GitHub's scheduler is often late and can skip runs. Because of D1 that
  doesn't matter. Each run still collects all four 15-minute snapshots of the hour, and any skipped run is
  covered by the next one (3-day look-back).
- The freshness check fails the run if the newest snapshot is over 3 hours old. This catches the quiet
  failure where the job "succeeds" but collects nothing.

**Alternatives.** Always-on VM (costs money or a free tier that can vanish); local cron on a laptop
(off whenever the laptop sleeps); committing data to a `data` branch (bloats the repo).

**Risks.** GitHub disables scheduled workflows after 60 days with no repo activity (the finals break is
about 3 weeks, so fine). The brief asks for "every 15 minutes": the data is 15-minute, the job is hourly.

## D5. Weather: Open-Meteo for model features, HKO collected live for warnings (14 Nov 2026) *(planned, M1)*

**What.** Temperature, rain and humidity features come from Open-Meteo's hourly archive. HKO current weather
and warnings are collected hourly from now on.

**Why.** HKO's API only serves "now"; it is not in the data.gov.hk archive, so there is no way to get
13 months of HKO history through it. Open-Meteo serves any past hour. Using one source for both training
and live prediction avoids *training/serving skew* (the model seeing differently measured inputs in
production than it was trained on).

**Alternatives.** HKO daily climate CSVs (daily only, and the test query returned no rows; not verified);
no weather at all (fallback if it shows no predictive value, which is plausible).

**Caveat.** Open-Meteo history is a reanalysis (a model's reconstruction), not station readings.

## D6. Travel time v1: distance-based estimate behind a swappable interface (14 Nov 2026) *(planned, M3)*

**What.** v1 estimates travel time from straight-line distance with a detour factor, an average speed and a
harbour-crossing penalty, clearly labelled approximate. It sits behind one interface so v2 can replace it
with real transit routing without touching the recommender.

**Why.** The official Transport Department GTFS has **no MTR rail or Light Rail** (agencies are buses,
minibuses, ferries, trams only). Routing on it alone would give wrong answers for most trips, and proper
routing needs the community GTFS plus a street network, which doesn't fit v1's hours.

**Alternatives.** Full routing now with r5py (v2 plan); precomputed district matrix (still needs a router
to compute it).

## D7. Agent v1: plain SDK tool calling, with a rule-based red-flag check first (14 Nov 2026) *(planned, M3)*

**What.** One loop over a handful of tools using the LLM SDK directly, no LangGraph in v1. Before the LLM sees
a message, a deterministic check looks for red-flag and crisis language and returns the fixed 999 / crisis
response.

**Why.** The brief's default is LangGraph, but a single agent choosing among six tools has no branching
workflow for a graph to manage, and fewer layers are easier to explain and debug. The safety target is 100%,
and an LLM alone can't promise that; a rule layer in front gives a floor that doesn't depend on the model.

**Alternatives.** LangGraph from the start (revisit in v1.1 if the flow gains real steps); LLM-only safety
(no guarantee).

## D8. Hosting: Hugging Face Spaces with Docker (14 Nov 2026) *(planned, M5)*

**What.** One free Docker Space running FastAPI and Streamlit together.

**Why.** Free, runs an arbitrary Dockerfile (so the same image runs locally), and can host two processes.
Streamlit Community Cloud can't run the FastAPI backend.

**Alternatives.** Streamlit Cloud + a separate free API host (two deployments to keep alive); Render / Fly
free tiers (sleep or limits change often).

---

## Known issues to carry forward

- **Fee change inside the training window.** The A&E charge rose from $180 to $400 on 1 Jan 2026 (triage I
  and II exempt). Demand before and after may differ. M2 must compare errors across that date.
- **Target is coarse.** `t45p50` is rounded up to the nearest 0.5 hour, so it moves slowly and
  "no change" (persistence) will be a strong baseline at +1h.
- **HA pages for the knowledge base** couldn't be read from the dev machine. Needed in M4.

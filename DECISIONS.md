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

**Consequence.** About 13 months, 38,022 snapshots (99.94% of all 15-minute slots). No second winter, so
yearly seasonality can't be validated.

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

## D5. Weather: Open-Meteo for model features, HKO collected live for warnings (14 Nov 2026) *(tested in M2; weather features then dropped, see D16)*

**What.** Temperature, rain and humidity features come from Open-Meteo's hourly archive. HKO current weather
and warnings are collected hourly from now on.

**Why.** HKO's API only serves "now"; it is not in the data.gov.hk archive, so there is no way to get
13 months of HKO history through it. Open-Meteo serves any past hour. Using one source for both training
and live prediction avoids *training/serving skew* (the model seeing differently measured inputs in
production than it was trained on).

**Alternatives.** HKO daily climate CSVs (daily only, and the test query returned no rows; not verified);
no weather at all (fallback if it shows no predictive value, which is plausible).

**Caveat.** Open-Meteo history is a reanalysis (a model's reconstruction), not station readings.

## D6. Travel time v1: distance-based estimate behind a swappable interface (14 Nov 2026, built 15 Nov)

**What.** v1 estimates travel time from straight-line distance with a detour factor, an average speed and a
harbour-crossing penalty, clearly labelled approximate. It sits behind one interface so v2 can replace it
with real transit routing without touching the recommender.

**Why.** The official Transport Department GTFS has **no MTR rail or Light Rail** (agencies are buses,
minibuses, ferries, trams only). Routing on it alone would give wrong answers for most trips, and proper
routing needs the community GTFS plus a street network, which doesn't fit v1's hours.

**Alternatives.** Full routing now with r5py (v2 plan); precomputed district matrix (still needs a router
to compute it).

**As built (15 Nov), then replaced (16 Nov, see D20).** The first version was 10 min overhead + straight-line
km x 1.4 / 20 km/h, +10 min to cross the harbour, +10 min for the Lantau link. These were guesses, and the
journey-planner check showed they were badly wrong on long trips. Regions come from rough bounding
boxes; Lamma and other small islands are not handled.

**Ferry-only trips are not offered.** The first replay sent 22% of decisions to St John Hospital on Cheung
Chau, because a short wait there outweighed a flat ferry penalty. A ferry has a timetable and no overnight
service, the model knows neither, and telling someone to take a ferry to an A&E is a bad recommendation. St
John is now suggested only to someone already on Cheung Chau. Cost: the headline saving fell from 82 to 75
minutes.

## D7. Agent v1: plain SDK tool calling, with a rule-based red-flag check first (14 Nov 2026, built 15 Nov)

**What.** One loop over a handful of tools using the LLM SDK directly, no LangGraph in v1. Before the LLM sees
a message, a deterministic check looks for red-flag and crisis language and returns the fixed 999 / crisis
response.

**Why.** The brief's default is LangGraph, but a single agent choosing among six tools has no branching
workflow for a graph to manage, and fewer layers are easier to explain and debug. The safety target is 100%,
and an LLM alone can't promise that; a rule layer in front gives a floor that doesn't depend on the model.

**Alternatives.** LangGraph from the start (revisit in v1.1 if the flow gains real steps); LLM-only safety
(no guarantee).

**As built (15 Nov): three layers, not two.** The first safety eval showed the fixed rules catch 100% of the
wording they were written around but only 22% of held-out paraphrases ("an elephant sitting on my chest",
"我已經寫好遺書"). So the rules are a floor that works with no network, not the safety system. A second layer
was added: one separate AI call that only classifies the message as emergency, crisis or none, with a
forced answer shape, before the tool-using agent runs. Both layers return fixed text, so an emergency
reply cannot contain a hospital name or a waiting time. The main agent carries the same rules in its
instructions as a third layer. Any failure (no network, a refusal, too many tool steps) returns a fixed safe
message that says to call 999 if it could be an emergency.

**More choices made while building.**
- The held-out prompts are never used to change the rules; otherwise the rule-layer score would mean nothing.
- The tool loop is written by hand (about 25 lines) instead of using the SDK's tool runner, so every step can
  be explained and so tests can swap in a fake model. Tests run with no API key.
- Model: the agent talks to a small provider interface (`agent/providers.py`: screen, turn, add tool
  results) with two implementations. The default is a free open model run locally with Ollama, chosen
  because the project has no budget for API calls; nothing leaves the laptop. Claude through the Anthropic
  API (`claude-opus-5-5`, with the API's server-side fallback beta) is the alternative, set in `.env`.
  A small local model is expected to be weaker at catching unusual emergency wording and at Cantonese, and
  a free hosted demo cannot run Ollama, so the model for the public demo is still an open decision (M5).
- Tool inputs use `strict` schemas, and every number in an answer must come from a tool result.
- Privacy: nothing the user types is written to disk or logged. With Ollama, messages stay on the machine.
  With a hosted model they are sent to that provider, and the UI must say so.

**Result (16 Nov).** With a local `qwen3:4b` model the full agent handled 59 of 59 emergency and crisis
prompts safely and wrongly flagged 0 of 20 ordinary questions. The rules answered 34; the AI screen caught
the other 25; none reached the tool-using agent. This is one run of one small model on 59 prompts written
by the project author: enough to show the design works, not enough to call it proven. Two things found on
the first real run and fixed: the model leaked its private reasoning into answers (now stripped before
anything is shown or kept), and only the last few turns of a chat are sent to the model, because a small
model's 4,096-token window would otherwise cut the oldest text first, which is the safety rules. Known gap:
the screen reads only the newest message, so an emergency that only becomes clear across several messages
relies on the main agent's instructions. The Cantonese prompts were not written by a native speaker.

## D8. Hosting: Hugging Face Spaces with Docker (14 Nov 2026; built 20 Nov, see D26)

**What.** One free Docker Space running FastAPI and Streamlit together.

**Why.** Free, runs an arbitrary Dockerfile (so the same image runs locally), and can host two processes.
Streamlit Community Cloud can't run the FastAPI backend.

**Alternatives.** Streamlit Cloud + a separate free API host (two deployments to keep alive); Render / Fly
free tiers (sleep or limits change often).

## D9. Time index is the archive slot, not HA's "updateTime" (14 Nov 2026)

**What.** Every row is indexed by `observed_at`, the archive's 15-minute slot. HA's own `updateTime`
(15 minutes earlier in 99.99% of rows) is kept as a column but not used as the clock.

**Why.** Leakage safety. I can prove a value was visible at its archive slot, because that is when the
archive captured it. I can't prove it was public at HA's stamp, since HA's site isn't reachable from here.
Using the later time means a forecast "made at 10:00" only uses what was really downloadable at 10:00.

**Alternatives.** Index by `updateTime` (reads more naturally, but risks using data 15 minutes before it
existed publicly).

**Consequence.** If HA does publish at its stamp, the live app could be up to 15 minutes fresher than the
evaluation assumes. That makes the evaluation slightly pessimistic, which is the safe direction.

## D10. One unit everywhere: minutes (14 Nov 2026)

**What.** The cleaner converts every wait to minutes once, in `clean/models.py`. All columns end in `_min`.

**Why.** HA publishes triage III in minutes and triage IV/V in hours. Converting in one place, with the
unit in the column name, removes the most likely silent bug in the project.

**Alternatives.** Keep HA's units (invites a ×60 mistake); hours everywhere (triage III becomes awkward decimals).

## D11. Validation design: expanding window, 14-day test blocks, identical rows (14 Nov 2026)

**What.** Walk-forward with an expanding training window. First test block starts after 56 days; each block is
14 days. Forecasts are made at every 15-minute slot. A row is scored only if the actual value and all three
baselines exist.

**Why.**
- Expanding (not sliding) window: there is only about a year of data, so nothing is thrown away.
- 14-day blocks: each contains two of every weekday, and gives about 24 folds, enough to see whether a result
  holds across seasons rather than in one lucky month.
- 56 days first: the historical-mean baseline needs several examples of each weekday-hour cell.
- Identical rows: seasonal naive needs the value from a week ago, which is sometimes missing. Scoring each
  baseline on its own available rows would compare them on different, unequal test sets.
- Gaps stay empty. Filling a missing slot with the previous value would hand persistence free correct answers.

**Alternatives.** Single train/test split (one number, no idea of its stability); sliding window (useful later
to test whether old data hurts after the fee change); forward-filling gaps (biased toward persistence).

**Caveat.** Forecasts 15 minutes apart are highly correlated, so the row counts overstate how much independent
evidence there is. Per-fold results are the honest unit for judging stability.

## D12. Request every 15-minute slot; don't trust the archive's listing (14 Nov 2026)

**What.** The collector asks for each of the day's 96 slots directly and treats a 404 as "not there".
It no longer uses the archive's `list-file-versions` endpoint to decide what to download.

**Why.** The first full download used the listing and came back with ten whole days missing in
Oct–Nov 2026, plus about 340 scattered slots. The data-quality report showed gaps starting exactly at
midnight and lasting exactly 24 or 48 hours, which looked like an indexing fault rather than an outage.
Asking for those slots directly returned every file. Refilling recovered 1,297 snapshots; only 35 slots
are truly absent.

**Alternatives.** Trust the listing (loses 3.4% of the data without any error); use the listing first and
probe only the days it reports as empty (misses the scattered slots).

**Cost.** A few dozen wasted requests per full run for slots that really are missing. Hourly runs only
re-check the last 3 days.

**Lesson worth telling.** The download "succeeded" with zero errors. Only the gap table in the quality
report exposed it.

## D13. Stale rows are excluded from modelling and scoring (14 Nov 2026)

**What.** A row is "stale" when HA's update stamp is more than 20 minutes behind the slot, meaning the feed
repeated an old update instead of refreshing (368 slots, about 1%). Stale rows are kept in the clean table
with a flag, but blanked when building the modelling panel.

**Why.** While the feed is frozen, "no change" is trivially correct, so leaving those rows in would flatter
persistence and anything that leans on the current value. Excluding them is the conservative choice.

**Alternatives.** Keep them (it is what a user saw at the time, but it rewards a frozen feed); drop them from
the clean table entirely (loses the evidence that the feed stalls).

**Open question for the live app.** When the feed is stale right now, the app should say so rather than
present an old number as current.

## D14. Model design: one LightGBM per horizon, predicting the change, trained on absolute error (15 Nov 2026)

**What.** For each target and horizon (+1h, +2h, +3h) one LightGBM model shared by all 18 hospitals, with
`hospital` as a categorical feature. It predicts `wait(t+h) - wait(now)`; the current wait is added back.
The training loss is absolute error (L1). Hyperparameters were fixed before the run and not tuned.

**Why.**
- *Change, not level.* The wait is sticky. Predicting the change means a model that learns nothing equals
  persistence, the strongest baseline at +1h, instead of something worse.
- *L1 loss.* The reported metric is MAE, so the model is trained on the thing it is judged on. Squared error
  would chase the rare huge swings.
- *One shared model.* 18 separate models would each see 1/18 of the data. A shared model learns patterns common
  to all hospitals (the morning drop, the evening build-up) and still tells hospitals apart by the category.
- *Separate model per horizon.* Simple and standard ("direct" forecasting). The alternative, predicting +1h and
  feeding that back in to get +2h, compounds its own errors.
- *No tuning.* With only 13 months there is no spare data to tune on. Tuning against the same test blocks that
  produce the headline number would make that number optimistic.

**Alternatives.** Per-hospital models; predicting the level; squared-error loss; recursive forecasting; a
tuned model with a held-out tuning period (worth doing in v2 with more data).

**Shortcut taken.** Training uses forecasts made on the hour and half hour only (half the rows). Forecasts
15 minutes apart are near-duplicates; on one block this cost 0.3 minutes of MAE and halved run time.
Testing uses every 15-minute forecast.

## D15. Intervals: rolling conformal from the previous block's errors, per hospital (15 Nov 2026)

**What.** The 80% interval for a forecast is `prediction + [10th, 90th percentile]` of the model's signed
errors (actual minus predicted) for that hospital in the previous two-week test block.

**Why.**
- Those errors are genuinely out-of-sample: the previous block was predicted by a model that had not seen it.
  Errors on training data would be too small and the intervals too narrow.
- No extra models. Quantile regression needs two more models per horizon.
- Per hospital, because error size differs several-fold between hospitals. One city-wide margin would
  over-cover the calm hospitals and under-cover the volatile ones.
- Signed percentiles (not one symmetric margin) let the interval be lopsided, which suits a wait that can
  jump up further than it can fall.
- "Previous block" rather than "all past errors" lets the width adapt as conditions change.

**Alternatives.** Quantile regression (LightGBM `objective="quantile"`); a held-out calibration slice inside
the training window (the model then can't train on its most recent data); MAPIE (adds a dependency for
about 20 lines of logic).

**Limits.** The formal conformal guarantee assumes errors are exchangeable (roughly: no drift over time).
Time series break that, so coverage is measured, not assumed; the report gives it per block. The interval
has the same width at 4am and 6pm for a given hospital, which is cruder than it could be.

## D16. No weather in the model; train on all history, not a recent window (15 Nov 2026)

**What.** The shipped model has no weather features and trains on everything since 14 Oct 2025.

**Why.** Both were tested as ablations on the same folds (see `evals/reports/forecast.md`):
- Adding temperature, rain and humidity did not improve the error at any horizon. Dropping them removes an
  external dependency, a serving-time data source and the reanalysis caveat in D5.
- Training on only the last 120 days was slightly worse than using all history, including in the blocks where
  a 120-day window contains no data from before the 1 Jan 2026 fee change. So there is no evidence that
  pre-fee-change data hurts.

**Alternatives.** Keep weather "because it should matter" (it adds complexity for no measured gain).

**Caveats.** One weather point for the whole city, hourly, from a reanalysis: a weak test of weather. Rare
events (typhoon signals, black rainstorms) are too few in 13 months to learn from; HKO warnings are being
collected for a later test. This supersedes the modelling half of D5.

---

## D17. Step-pattern and neighbouring-hospital features were tested and rejected (15 Nov 2026)

**What.** Two extra feature groups were tried on the non-urgent target and neither is in the shipped model:
five "step" features (how long the published number has held its level, last jump, time since it last rose
or fell, changes in the past 3 hours) and five "neighbour" features (the three closest other A&Es by
straight-line distance: their waits now and their 1-hour change).

**Why.** Both made the error very slightly worse, by 0.1% to 0.2% at every horizon, on the 20 development
blocks and again on the 4 held-back blocks (`evals/reports/feature_experiment.md`). The rule was written
into the script before the run: adopt only if better at all three horizons on both sets. Likely reasons:
the published wait changes in about half of all 15-minute slots, so there is little "holding a level" to
exploit, and the model already sees the city-wide mean and each hospital's gap to it, which carries most of
what neighbours would add.

**Alternatives.** Keep them anyway (more features with no measured gain is harder to defend); pick
neighbours by travel time or by learned correlation instead of straight-line distance (not tried; a learned
choice would have to be fitted inside each training window to avoid leakage).

**Caveats.** The held-back blocks had already been scored once for the M2 headline, so they were unseen by
this experiment only. The feature code stays in `features.py`, switched off, so the result is reproducible.

**Also fixed.** The "What the model uses" table in `forecast.md` had been computed from the last variant
trained (the 120-day ablation) instead of the shipped model. It now refits the shipped model explicitly.
The ranking changed slightly; no error or coverage number changed.

## D18. Recommender and hindsight evaluation design (15 Nov 2026)

**What.** `total = travel + forecast wait at the arrival time`. The wait at arrival is read off a straight
line through the published value now and the +1h, +2h, +3h forecasts. The 80% band is zero now and grows with
the square root of time over the first hour. The evaluation replays every 15-minute moment of the forecast
test period from 18 starting points (one landmark per district) under four methods: nearest, current waits
only, the app, and an oracle that knows the future.

**Why.** Trips rarely take a whole number of hours, so some interpolation is needed, and a straight line is
the simplest one to explain. Including "current waits only" separates what forecasting adds from what simply
looking at the published board adds. The oracle shows the most any method could save. The recommender is pure
functions, so the live app and the evaluation run the same code.

**Result (`evals/reports/regret.md`, rerun 16 Nov with the refitted travel estimate, D20).** The app's pick is
89 minutes shorter on average than the nearest A&E (median 68). Most of that comes from using current waits
at all (86 minutes); forecasting adds about 3 more and cuts the gap to the oracle from 16.0 to 12.8 minutes.
With every trip twice as long the saving is 71. (With the first, unfitted travel guess these were 75, 72 and 58.)

**Alternatives.** Train extra models at 15-minute horizons instead of interpolating (more models to maintain
for a small part of the total); weight starting points by population (planned with the census data in v2).

**Caveats.** The outcome is HA's published estimate at the arrival time, not a measured wait. Travel times
are straight-line estimates, about 5 minutes off on average (D20). The app's pick is 39 minutes away on
average against 19 for the nearest, so the saving is a longer trip traded for a shorter wait, which not every
patient can make. The interpolated band contained the published value 75.0% of the time against a target of 80%, so it is slightly
too narrow at arrival times that fall between whole hours.

## D19. Hyperparameters: searched, gain too small, settings kept (15 Nov 2026)

**What.** The fixed LightGBM settings from D14 stay. A search was run and its winner was not adopted.

**Why.** `evals/run_tuning.py` scored 12 random settings plus the current one, each at 200 to 1,200 trees, on
blocks 4, 8 and 12 at +2h. The winner was the current settings with 1,200 trees instead of 400; no other
setting beat the current one by more than 0.07%. On blocks 13 to 24, which the search never used, the winner
was better at all three horizons for the non-urgent target but only by 0.39% on average (0.62%, 0.40%, 0.16%),
and Triage III did not move. The rule written before the run required at least 0.5%, so the verdict is keep.
Three times the trees for a 0.1 to 0.2 minute gain is not worth slower training.

**Alternatives.** Adopt 1,200 trees anyway (breaks the pre-set rule for a gain smaller than the noise between
blocks); a larger or Bayesian search (the flat results across very different settings suggest the features,
not the settings, are the limit).

**Caveat.** The confirmation blocks had been scored before for other results; they were untouched by this
search, not unseen altogether.

## D20. Travel estimate refitted after the journey-planner check (16 Nov 2026)

**What.** The travel estimate is now `8 + 9.8 x sqrt(straight-line km)` minutes, plus 8 to cross the harbour,
shown as a +/-25% range. The Lantau penalty is gone. Ferry-only trips are still not offered (D6).

**Why.** Checked against Google Maps public-transport times for 10 trips fixed in advance, the first guess
(constant speed) was off by 15.0 minutes on average: fine under 9 km (about 4 minutes) but 25 to 70 minutes
too slow on the three trips over 15 km. Long trips use faster transport (rail, expressway buses), so time
grows more slowly than distance. Two simple shapes were fitted to those 10 trips, a straight line and a
square root, and compared by leave-one-out error (10.7 vs 8.4 minutes); the square root was chosen. The
choice was then fixed and tested on 10 new trips looked up afterwards: **5.1 minutes mean absolute error,
largest miss 11** (first guess on the same trips: 11.9, largest miss 59).

**Effect on the headline.** The regret evaluation was rerun: the saving against the nearest A&E moved from
75 to 89 minutes (median 68), because distant hospitals had been unfairly penalised. Forecasting still adds
about 3 minutes over current waits alone.

**Alternatives.** Keep the guesses and only report their error (the recommender would stay biased against
far hospitals); real routing (v2, D6).

**Caveats.** 20 trips is a small check. Planner times were read by Claude in a browser, not by Tejas, for one
departure time (Monday 10:00), so night-time and peak-hour travel are untested. The 10 validation trips start
from the same 18 district landmarks the regret evaluation uses. The estimate still knows nothing about
which places have a rail line.

## D21. Knowledge base and retrieval for the agent (16 Nov 2026, finished 17 Nov)

**What.** The agent answers questions about triage, fees, refunds and alternatives to A&E only from passages
found in a small knowledge base, and cites the source title and URL. The knowledge base is 86 passages cut
from 7 Hong Kong Government press releases on info.gov.hk (Hospital Authority and Health Bureau statements,
2023 to 2026) and the Hospital Authority's 2026 fee table (a PDF attached to one release), listed in
`src/aecompass/kb/sources.py`. Passages are whole paragraphs grouped to about 130 words, capped at 220. Search sits behind one `search(query, k)` method with two implementations: keyword (TF-IDF) and
embedding (vector) search through Ollama.

**Why these sources.** The brief asks for HA's own triage and fee pages, but www.ha.org.hk still refuses
connections from the development machine (D1). The press releases are official, reachable, dated, and state
the same rules (five triage categories, the $400 fee from 1 Jan 2026, the exemption for critical and
emergency patients, the $350 refund). Only the list of URLs is committed; the text is downloaded locally into
the git-ignored `data/kb/` and not redistributed.

**Why two search methods.** Keyword search needs no model and is easy to explain, so it is the baseline. On
24 test questions it found the answering passage in the top 3 for 15 of 18 English questions and 0 of 6
Chinese ones, and it missed "How much is the A&E fee now?" because the passage that says $400 shares few
words with the question. Embedding search with the multilingual `bge-m3` model, run locally through Ollama,
found it for 20 of 24 questions (15 of 18 English, 5 of 6 Chinese) and is what the agent uses. Combining the
two rankings (hybrid) also scored 20 of 24 and ranked the answer first less often (15 times against 19), so
it was not adopted. Source: `evals/reports/retrieval.md`.

**Alternatives.** A vector database such as Chroma or FAISS (pointless for 86 passages: a matrix
multiplication is exact and instant); letting the model answer from memory (unverifiable, and fees changed
in 2026); pasting all the text into every prompt (would not fit a small local model's context).

**Caveats.** Press releases are written for news, not as reference pages, and several are question-and-answer
replies full of statistics tables that make poor passages. Rules can change after a release's date; the tool
returns the date with every passage. One source tells non-emergency patients to "avoid using A&E", which
conflicts with this project's rule never to discourage attendance: the agent is told to report it only as
what the guidance says and never to judge whether a user's own symptoms are mild.

## D22. Answer guard in code, and what the agent evaluation showed (17 Nov 2026)

**What.** A fourth safety layer, `check_answer` in `src/aecompass/agent/safety.py`, reads the model's finished
answer before the user sees it. If the answer tells the user they do not need care, judges how serious their
situation is, or contains a web address that was in no tool result, the answer is thrown away and replaced
with fixed text. The system prompt also gained a rule to say plainly, first, that the agent cannot diagnose.

**Why.** The first full run of `evals/run_agent_evals.py` (59 prompts, local `qwen3:4b`) found two answers
that instructions alone had not prevented: "You don't need to go to A&E for this" for a cut finger, and a
made-up gov.hk address cited for a wrong "20 minutes" target. Both break rules this project treats as
absolute. A check in code does not depend on a small model following instructions every time.

**Result** (`evals/reports/agent_evals.md`; first run kept in `agent_evals_before_guards.md`). The 29
no-diagnosis and citation prompts were asked again with the guard and the new prompt rule. The 30 task
prompts were not asked again, so their rows are from the first run.

| | First run | With guard and new rule |
|---|---|---|
| Task success (names the recommender's top A&E first) | 30 of 30 | not asked again |
| No diagnosis | 13 of 16 | 16 of 16 |
| No judging of the user's situation | 54 of 55 | 56 of 56 |
| No invented links | 54 of 55 | 56 of 56 |
| Grounding (every number traceable to a tool result) | 39 of 40 | 39 of 41 |
| Citations (states the fact and cites a source containing it) | 9 of 13 | 7 of 13 |
| Replaced by the fixed safe message because the model failed | 3 | 2 |

**Reading it honestly.**
- The guard did not fire once in the second run. The improvement in no-diagnosis therefore comes from the
  new prompt rule or from run-to-run chance, not from the guard. The guard is covered by unit tests and was
  checked against the first run's saved answers (it blocks the two bad ones and none of the other 53).
- Citations got worse, and 13 questions is too few to call that a real change. The six failures: two Chinese
  questions where the local model server returned an error and the agent fell back to its safe message; two
  answers with the right fact and no link; one answer that said, truthfully, that the passages it was given
  did not state the Category II target; and one wrong answer, a "$180 refund" taken from an older passage
  when the current refund is $350. That last one is the real weakness: the knowledge base holds rules
  from before and after the January 2026 fee change, and the model picked the old one.
- Scoring is by pattern matching. Three false alarms in the scorer were fixed before this table was made:
  numbers the sources write with a space ("6 719"), numbers in table cells, and a site the source prints
  without "https://". The two grounding misses that remain are a month number in a date and a year.
- The task prompts have not been run with the new prompt rule, so "30 of 30" describes the earlier prompt.

**Alternatives.** A second model call to review each answer (doubles a wait that is already minutes long on
this laptop); relying on the prompt alone (failed twice in 59); refusing every question about the user's own
symptoms before the model sees it (would also block ordinary "where is quickest" questions).

**Caveats.** The guard is a pattern list, like layer 1, so it only catches wording it knows. One run each,
one small model, test prompts written by the project author.

## D23. Sources from before the 2026 fee change are labelled and listed last (17 Nov 2026)

**What.** Three sources (the 2023 and 2024 A&E service replies and the December 2025 surge notice) carry
`old_fees=True` in `src/aecompass/kb/sources.py`. The search tool lists passages from current sources first
and attaches a warning to each older passage: its fee and refund amounts are out of date and must not be
given as current.

**Why.** In the second agent evaluation the agent told a user the refund for leaving A&E was $180. That was
the amount before 1 January 2026; it is now $350. The tool had returned old and new passages with only a
date to tell them apart, and a small model did not use the date.

**Result** (`evals/reports/agent_evals.md`). The 13 citation questions were asked again. Both refund
questions (English and Cantonese) now answer $350 and cite the January 2026 release. Citations overall went
from 7 of 13 to 8 of 13, which is within run-to-run noise for 13 questions. The five that still fail:
- two fee answers state $400 correctly but link the press release, not the fee table attached to it, which
  is the document that contains the figure;
- one names the right source for the doctor directory but gives no link to it;
- one (Category III target) was replaced by the answer guard because the model wrote a link that was in no
  tool result, which is the guard doing its job;
- one (Category II target) timed out on the laptop and got the fixed safe message.

One answer the scorer passes is still muddled: asked what A&E cost before the reform, the agent gave $180
(right) but said it applied to "non-urgent and semi-urgent patients" who are "now fully exempted" (wrong: it
was the fee for everyone, and it is critical and emergency patients who are now exempt). Pattern matching
cannot see that kind of error. It needs a person, or a stronger model, to read the answers.

**Alternatives.** Deleting the older sources (they are the only ones that list the five triage categories
and the waiting-time targets); filtering old passages out of fee questions only (needs code to decide what
counts as a fee question); splitting the knowledge base in two (more to maintain for 86 passages).

**Caveats.** The flag is set by hand per source. The warning is attached even when the question is about
triage, where the older source is still right; the wording limits it to fee and refund amounts.

## D24. The API wraps the agent's tools; the web page only talks to the API (20 Nov 2026)

**What.** `src/aecompass/api/app.py` is a FastAPI service with five endpoints: `GET /health`, `GET /waits`
(every A&E now and +1/+2/+3 h), `GET /forecast/{hospital}`, `POST /recommend` and `POST /chat`. Each one
calls the same `Toolbox` methods the agent's tools call. The Streamlit page (`src/aecompass/web/app.py`)
holds no data or models; it calls the API over HTTP. A background thread in the API downloads the newest
published waits every 15 minutes (`AECOMPASS_REFRESH_MINUTES`) and swaps them in.

**Why.** One code path for every number: the page, the API and the agent cannot disagree about a wait,
because they all read it from the same function. Keeping the page thin means a second client (a phone app,
an MCP server, the brief's stretch goal) needs no changes to the model code.

**Privacy choices.** Places and chat messages go in the request body (POST), never the URL, because web
servers log URLs. The server keeps no chat history: the browser sends the conversation with each message
and the server forgets it after replying. A test checks that nothing the user types reaches the logs.
Fixed safety replies (999, crisis lines) are not added to the conversation sent to the model.

**Alternatives.** Streamlit calling the Python functions directly (simpler, but then there is no API to
show, and the page and the models must share one process); keeping chat history on the server in a session
store (needs storage of health-related text, which the rules forbid).

**Caveats.** `/chat` answers take minutes with the local model, so the page waits up to 15 minutes. There is
no rate limit or authentication; that matters only once it is public (D8).

## D25. Docker: one image, two containers, data mounted rather than built in (20 Nov 2026)

**What.** One `Dockerfile` (Python 3.12 slim) builds an image with the package installed. `docker compose up`
runs it twice: the API on port 8000 and the page on port 8501. `./data` is mounted into the API container.
The local Ollama server stays outside Docker and is reached at `host.docker.internal`.

**Why.** "Runs with one command" (brief 4.6) without copying data into the image: `data/` is never
committed, and a mounted folder lets the API's refresh write new snapshots that survive a restart.
Dependencies are installed in their own layer, so editing code rebuilds in seconds. The container runs as
a normal user, not root.

**Alternatives.** Two images (smaller each, more to maintain); running Ollama in a container too (would
need about 4 GB more memory on an 8 GB laptop, and GPU passthrough differs by machine); baking data and
models into the image (needed for hosting, see D8, but would put data in every local build).

## D26. The hosted demo has no chat, and rebuilds its data and models on every start (20 Nov 2026)

**What.** The public copy on a free Hugging Face Space runs with `AECOMPASS_CHAT=off`: the live board and
"Where should I go?" work, and the chat tab explains that the assistant runs only locally. On every start,
`python -m aecompass.deploy.serve` downloads the raw monthly files and `offsets.json` from the public GitHub
Release `data`, fetches the last two days from the official archive, trains the models with the usual
recipe, then starts the API (internal port 8000) and the page (public port 7860). The Space's Dockerfile
(`deploy/space/`) clones the public GitHub repository, so it always builds from the committed code.

**Why no chat.** The agent needs an AI model. The free host can't reach Ollama on a laptop; running Ollama
inside the Space would fit in memory but answer in minutes, and an open, unauthenticated chat could be
abused; a paid API needs a key and a budget. The forecasting and recommendation, which are the evaluated
core, work without it. The chat stays fully usable locally, and its evaluations are in `evals/reports/`.

**Why rebuild on start.** A free Space's disk is wiped when it sleeps, and `data/` is never committed. The
release is already kept current by the hourly collector, so the Space needs no extra pipeline, and its
models are retrained on all the data up to the moment it starts. `offsets.json` (the 80% interval widths,
about 10 KB) can't be rebuilt there, because it comes from the walk-forward evaluation, so it is uploaded
to the release by hand and downloaded with the data.

**Measured.** In a local container starting from an empty disk: data downloaded in about 1 s (from a local
copy of the release), caught up with the archive by 19 s, models trained by 284 s, page up straight after.
A free Space's CPU may be slower. The first visitor after the Space has slept waits for this.

**Alternatives.** Uploading trained models to the release instead of training on start (faster start, but
the hosted model goes stale unless someone re-uploads); keeping the Space awake with a paid tier; Ollama in
the Space (above).

**Caveats.** The intervals come from the last evaluation run; if the recipe changes, re-run the evaluation
and re-upload `offsets.json`. The hosted copy has no rate limit; it has no AI and stores nothing, so the
cost of abuse is only CPU.

## Known issues to carry forward

- **Fee change inside the training window.** The A&E charge rose from $180 to $400 on 1 Jan 2026 (triage I
  and II exempt). Demand before and after may differ. M2 must compare errors across that date.
- **Target is coarse.** `t45p50` is rounded up to the nearest 0.5 hour, so it moves slowly and
  "no change" (persistence) will be a strong baseline at +1h.
- **HA pages for the knowledge base** couldn't be read from the dev machine. Government press releases and
  the HA fee table are used instead (D21).
- **Old and new fee rules sit side by side in the knowledge base.** The agent once quoted the pre-2026 $180
  refund (D22). Older sources are now labelled and listed last (D23).
- **The agent's guidance answers have only been checked by pattern matching.** At least one passing answer
  misreads its source (D23). Read the transcripts by hand before the demo.

# CLAUDE.md: working rules for A&E Compass HK

Portfolio project by Tejas (2nd-year BEng AI & Data Science, HKU). It forecasts Hong Kong public A&E
waiting times and recommends where a non-urgent patient is likely to be seen soonest.
The full brief is `docs/PROJECT_BRIEF.md`. Decisions live in `DECISIONS.md`.

## Git and GitHub: hands off

**Claude never touches the repository history or GitHub.** No `git init`, `git add`, `git commit`,
`git push`, no creating repos, releases, issues or PRs, and no co-author or "generated with" lines anywhere.
Tejas is the only committer. Claude writes files in the working folder, then says what changed and
suggests a commit message for Tejas to use.

## How we work

1. **Explain before code.** Tejas is new to: LLM tool calling, agent frameworks, RAG / vector search, FastAPI,
   Docker, quantile forecasting / conformal prediction, GTFS routing, LLM evals. Give a plain-English,
   beginner-level definition of any such concept before writing code that uses it.
   He already knows Python, pandas, scikit-learn, XGBoost, statsmodels, SHAP, Streamlit, GitHub Actions, SQL.
2. **Every decision must be defensible in an interview.** Add a short `DECISIONS.md` entry (what, why,
   alternatives considered) for each non-trivial choice. Claude drafts; Tejas rewrites in his own words.
3. **Stop at each milestone** with a review summary: what was built, how to run it, what to look at, and
   3 questions an interviewer might ask.
4. **Never fake results.** Report bad metrics honestly and explain them. No made-up numbers anywhere.
   Every number in the README must be reproducible from a file in `evals/reports/`.
5. **Small, runnable steps**, each ending at a point where Tejas can commit.
6. **Never silently drop a requirement.** If a source is dead or a field is missing, find the best
   alternative and record it in `DECISIONS.md`.
7. **Never cut:** the three forecasting baselines, walk-forward validation, the red-flag safety eval,
   the grounding eval.
8. Time-series rules: time-based splits only (no random k-fold); features may only use data available at
   forecast time (no leakage).
9. The forecast target is HA's *published estimate*, not actual patient waits. Say so wherever results appear.

## Safety and ethics rules (also go in the agent's system prompt)

1. **Not medical advice.** Persistent disclaimer in the UI and in agent answers. The app is for
   **non-life-threatening** situations only.
2. **Red-flag symptoms → "Call 999 now."** No waiting-time comparison, no "but Hospital X is faster".
3. **Never diagnose**, and never tell anyone they don't need care.
4. **Don't discourage people from going to A&E.** The framing is "here's where you'll likely be seen
   soonest", never "you're fine".
5. **Mental-health crisis language → crisis resources and nothing else:** The Samaritans 2896 0000
   (24h, multilingual), Suicide Prevention Services 2382 0000 (24h), or 999.
6. **Store no personal health information.** Don't log user symptom text beyond the current session.
7. **Not affiliated with the Hospital Authority.** No HA logos; say "not an official HA service".

## Data rules

- Follow data.gov.hk Terms and Conditions; credit every source in the README.
- Official open data only. No scraping of sites that forbid it.
- `data/` is never committed to git. Raw data lives in the GitHub Release tagged `data`.

## Practical notes

- Python 3.11+, virtualenv in `.venv`. Install with `pip install -e ".[dev]"`. Tests: `pytest`.
- All timestamps are Hong Kong time (`Asia/Hong_Kong`, UTC+8, no daylight saving).
- `www.ha.org.hk` refused connections from the dev machine on 14 Nov 2026. A&E data is read through the
  data.gov.hk historical archive API instead (see `DECISIONS.md` D1).

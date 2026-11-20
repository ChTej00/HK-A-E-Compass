# Demo video script (60–90 seconds)

Draft for Tejas to record. Show real output only: refresh the data first (`docker compose up`, wait for a
refresh or run `python -m aecompass.recommend.cli "Langham Place" --refresh`), and don't splice in numbers
that weren't on screen. Pre-record the chat answer, since a local model takes minutes; say so on screen.

| Time | On screen | Say |
|---|---|---|
| 0:00–0:08 | Title, disclaimer banner | "Hong Kong's public A&Es publish waiting estimates every 15 minutes. This app forecasts them and tells a non-urgent patient where they'd likely be seen soonest. It's not medical advice." |
| 0:08–0:20 | Live board tab, scroll the table, then the map | "Here's every A&E now, and the forecast for the next three hours with an 80% range. The model beats three baselines at every hospital; the ranges hold about 80% of the time." |
| 0:20–0:40 | "Where should I go?": type a place, show the table and map | "From Tuen Mun, say: travel time plus the forecast wait when you'd arrive. In a replay of a year's data, following the app was about 89 minutes faster on average than going to the nearest A&E, though most of that comes from just checking the published waits." |
| 0:40–0:55 | Chat: type "chest pain, which A&E is fastest?" | "Safety first: emergency wording never gets a waiting-time comparison. It's fixed text, decided by code before any AI sees the message." |
| 0:55–1:10 | Chat (pre-recorded): "How much is the A&E fee now?" answer with its citation | "Questions about fees and triage are answered only from official government text, with the source linked. It runs on a small free model on my laptop." |
| 1:10–1:20 | `evals/reports/` folder, README results table | "Every number I've said is reproducible from a script in the repo, including the parts that didn't work well." |

Numbers used: 89 minutes (`regret.md`), ~80% coverage (`forecast.md`), baselines (`forecast.md`).

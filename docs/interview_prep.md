# Interview prep: the 10 hardest questions about A&E Compass HK

Draft by Claude for Tejas to rewrite in his own words. Every number here comes from a file in
`evals/reports/`; the file is named next to it. If a number changes, re-run the script and update this page.

---

### 1. "You forecast HA's published estimate, not real waits. Isn't that useless?"

It's a real limit, and I say it everywhere the results appear. HA publishes a median-wait estimate for
triage 4–5, rounded to the half hour; that's the number patients actually see and act on, and it's the only
open data. So the honest claim is: "the app predicts what HA's board will say when you arrive", not "how long
you will wait". I can't measure the gap between the estimate and true waits without patient-level data,
which isn't public. If I had it, I'd recalibrate the target, not the method.

### 2. "Your +1 h error is 28 minutes. Is that good?"

It's 15.7% better than the best of three baselines at +1 h and about 29% better at +2 and +3 h
(`forecast.md`), and it wins in all 24 test blocks and at every hospital. In absolute terms 28 minutes on a
typical 165-minute wait is useful but not precise, which is why every forecast shows an 80% range, and
those ranges held 79.5–79.8% of the time. The +1 h gain is smallest because "stays as now" is already
strong when the target only moves in half-hour steps.

### 3. "How do you know there's no leakage?"

Splits are by time only: walk-forward, expanding window, 24 two-week test blocks, and the model never sees
a row after its forecast time. Features are built from data available at the forecast time; stale
snapshots are excluded rather than carried forward (D13). Hyperparameters and feature ideas were judged on
early blocks with the decision rule written down before looking at the held-back blocks (`tuning.md`,
`feature_experiment.md`), and both ideas were rejected by that rule.

### 4. "Does forecasting even matter for the recommendation?"

Barely, and I report that. In the hindsight replay (`regret.md`) the app saves 89.5 minutes on average
against going to the nearest A&E, but just looking at current published waits already saves 86.3. The
forecast adds about 3 minutes. The big win is "don't just go to the nearest one"; the forecast mostly
matters for long trips and fast-changing hospitals. The cost is real too: the app's pick is 39 minutes
away on average against 19 for the nearest.

### 5. "Your travel times are straight-line estimates. Why trust them?"

I checked them. The first guess was off by 15 minutes on calibration trips. I refit a simple formula on 10
journey-planner trips and then tested it on 10 new ones: average error 5.1 minutes, largest 11
(`travel_spot_checks.md`). And the conclusion is robust to it: with every trip made twice as long, the app
still saves 71 minutes (`regret.md`). Real routing (GTFS) is in v2.

### 6. "How do you stop the chatbot giving dangerous advice?"

Four layers, and the first and last don't involve AI. (1) Fixed keyword rules catch emergency or crisis
wording before any model sees it and reply with fixed text: call 999, or the crisis lines. (2) An AI
screen with a fixed output format catches wording the rules miss. (3) The agent's instructions forbid
diagnosis and wait comparisons for emergencies. (4) A code check reads the finished answer and replaces it
if it discourages care or cites a link no tool returned. On 59 emergency and crisis prompts the full agent
was safe 59 times with no false alarms on 20 ordinary prompts (`safety.md`); the rules alone managed 34.
If anything fails, it fails closed to a fixed "call 999 if this could be an emergency" message.

### 7. "Your safety eval is 59 prompts you wrote yourself. That proves nothing."

Agreed that it's not proof. It's a regression test: it shows each layer does its job and catches it if a
change breaks something. The held-out split shows the rules generalise badly (7 of 32 held-out prompts),
which is exactly why the AI screen exists. The Cantonese prompts weren't written by a native speaker. The
next step would be prompts from clinicians or real (anonymised) symptom phrasing, and a second rater.

### 8. "How do you know the agent's answers are grounded?"

The tools return every number; a checker flags any number in an answer that appears in no tool result
(40 of 40 answers clean, `agent_evals.md`), and any link that wasn't returned (all clean after the guard).
Citations are the weak spot: 8 of 13 questions both stated the fact and cited a source that contains it.
One earlier run quoted the old $180 refund because old and new rules sat side by side; old sources are now
labelled and listed last (D23). And pattern-matching misses meaning errors: one passing answer misdescribed
who paid the old fee. That's the case for a human or stronger-model review.

### 9. "Why a 4-billion-parameter local model instead of a frontier API?"

Cost and privacy: I had no API budget, and a local model means symptom text never leaves the machine. The
code supports both behind one interface, so switching is a config change. The trade is speed (minutes per
answer on an 8 GB laptop) and quality on citations. The safety layers are designed not to depend on the
model being good, which is what makes a small model acceptable here.

### 10. "Why didn't you use LangGraph / a vector database?"

Both would add machinery without solving a problem I had. The agent is a loop of at most six model turns
with four tools; a plain loop is easier to test and explain (D7). The knowledge base is 86 passages: a
matrix multiplication over their embeddings is exact and instant, so a vector database would only add a
service to run (D21). If the knowledge base grew to tens of thousands of passages, I'd revisit.

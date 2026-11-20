---
title: A&E Compass HK
emoji: 🧭
colorFrom: blue
colorTo: red
sdk: docker
app_port: 7860
pinned: false
short_description: Where you'd likely be seen soonest at a Hong Kong public A&E
---

# A&E Compass HK (demo)

Forecasts the Hospital Authority's published A&E waiting-time estimates 1 to 3 hours ahead and adds a rough
travel time, to suggest where a non-urgent patient is likely to be seen soonest.

**Not medical advice. Not an official Hospital Authority service.** For non-life-threatening situations
only. In an emergency, call 999.

The AI assistant is switched off in this demo; it runs on a local model. Code, evaluation and data sources:
https://github.com/ChTej00/HK-A-E-Compass

The first visit after the Space has been asleep takes a few minutes: it downloads the data and trains the
forecasting models on start-up.

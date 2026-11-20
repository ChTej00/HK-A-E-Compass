"""The web page. It only talks to the API (aecompass.api.app), so the page holds no models and no data.

    streamlit run src/aecompass/web/app.py           # needs the API running; set AECOMPASS_API_URL if not local

Nothing typed here is stored: the chat lives in this browser session's memory and is gone when the tab closes.
"""

from __future__ import annotations

import os

import httpx
import pandas as pd
import pydeck as pdk
import streamlit as st

API = os.environ.get("AECOMPASS_API_URL", "http://localhost:8000").rstrip("/")
CHAT_TIMEOUT_S = 900  # a small local model can take several minutes per answer
STALE_AFTER_MIN = 45

DISCLAIMER = (
    "**Not medical advice. Not an official Hospital Authority service.** For non-life-threatening situations "
    "only. Waits are the Hospital Authority's *published estimates* for triage categories 4 and 5 (semi-urgent "
    "and non-urgent) plus a forecast; sicker patients are always seen first, so your own wait may differ."
)
RED_FLAGS = (
    "**Call 999 now** for chest pain, difficulty breathing, signs of stroke (face drooping, arm weakness, slurred "
    "speech), heavy bleeding, collapse or seizures. Don't compare waiting times."
)
CRISIS = "In crisis? The Samaritans **2896 0000** (24h, multilingual) · Suicide Prevention Services **2382 0000** (24h) · **999**"


def fmt(minutes: float | None) -> str:
    if minutes is None:
        return "–"
    hours, mins = divmod(int(round(minutes)), 60)
    return f"{hours}h {mins:02d}m" if hours else f"{mins}m"


def with_range(value: float, low_high: list[float]) -> str:
    return f"{fmt(value)} ({fmt(low_high[0])}–{fmt(low_high[1])})"


@st.cache_data(ttl=300, show_spinner=False)
def get(path: str) -> dict:
    response = httpx.get(f"{API}{path}", timeout=60)
    response.raise_for_status()
    return response.json()


def post(path: str, body: dict, timeout: float = 60) -> httpx.Response:
    return httpx.post(f"{API}{path}", json=body, timeout=timeout)


def freshness(data: dict) -> None:
    age = data["data_age_minutes"]
    text = f"Published waits as of **{data['data_time_hkt']}** Hong Kong time"
    if age > STALE_AFTER_MIN:
        st.warning(f"{text}: about {fmt(age)} old. Current waits may be different.")
    else:
        st.caption(f"{text} ({fmt(age)} ago).")


def hospital_map(points: pd.DataFrame, start: list[float] | None = None) -> None:
    """Hospitals as circles (bigger and redder = longer wait); the starting place, if any, in blue."""
    worst = max(float(points["minutes"].max()), 1.0)
    points = points.assign(
        radius=250 + 900 * points["minutes"] / worst,
        red=(80 + 175 * points["minutes"] / worst).astype(int),
    )
    layers = [pdk.Layer("ScatterplotLayer", points, get_position="[lon, lat]", get_radius="radius",
                        get_fill_color="[red, 90, 60, 170]", pickable=True)]
    if start:
        layers.append(pdk.Layer("ScatterplotLayer", pd.DataFrame([{"lat": start[0], "lon": start[1], "label": "You start here"}]),
                                get_position="[lon, lat]", get_radius=300, get_fill_color="[30, 110, 220, 230]", pickable=True))
    view = pdk.ViewState(latitude=start[0] if start else 22.36, longitude=start[1] if start else 114.12, zoom=10 if start else 9.6)
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, tooltip={"text": "{label}"}, map_style=None))


def board_tab() -> None:
    try:
        data = get("/waits")
    except httpx.HTTPError as error:
        st.error(f"The API is not reachable at {API} ({type(error).__name__}). Start it with `uvicorn aecompass.api.app:app`.")
        return
    freshness(data)
    rows = []
    for h in data["hospitals"]:
        f = {x["hours_ahead"]: x for x in h["forecast"]}
        rows.append({
            "A&E": h["hospital"],
            "Non-urgent now": fmt(h["now_min"]),
            "+1 hour": with_range(f[1]["wait_min"], f[1]["range_min"]),
            "+2 hours": with_range(f[2]["wait_min"], f[2]["range_min"]),
            "+3 hours": with_range(f[3]["wait_min"], f[3]["range_min"]),
            "Urgent (cat. 3) now": fmt(h["urgent_triage_3_now_min"]),
            "_now": h["now_min"],
        })
    table = pd.DataFrame(rows).sort_values("_now")
    st.dataframe(table.drop(columns="_now"), hide_index=True, width="stretch")
    st.caption("Forecast ranges are 80% intervals: in testing, the published estimate landed inside them about 8 times in 10. "
               "HA rounds its estimates, so small changes may not show.")
    if data["no_current_wait"]:
        st.caption(f"No current published wait for: {', '.join(data['no_current_wait'])}.")
    points = pd.DataFrame([{"lat": h["lat"], "lon": h["lon"], "minutes": h["now_min"],
                            "label": f"{h['hospital']}: {fmt(h['now_min'])} now"} for h in data["hospitals"] if h["lat"]])
    hospital_map(points)


def where_tab() -> None:
    st.info(RED_FLAGS)
    with st.form("where"):
        place = st.text_input("Where are you starting from?", placeholder="A building, estate or station, e.g. Langham Place")
        go = st.form_submit_button("Find where I'd likely be seen soonest")
    if not go or not place.strip():
        return
    with st.spinner("Looking up the place and the forecasts..."):
        try:
            response = post("/recommend", {"place": place.strip()})
        except httpx.HTTPError as error:
            st.error(f"The API is not reachable at {API} ({type(error).__name__}).")
            return
    if response.status_code == 404:
        st.warning(response.json()["detail"])
        return
    if response.status_code != 200:
        st.error(f"Something went wrong ({response.status_code}). Try a different place name.")
        return
    result = response.json()
    st.write(f"Starting from **{result['start_matched_to']}**. If that's not right, try a more specific name.")
    freshness(result)
    options = result["options_soonest_first"]
    st.dataframe(pd.DataFrame([{
        "A&E": o["hospital"],
        "Travel (rough)": f"~{fmt(o['travel_min'])}",
        "Wait when you arrive": with_range(o["wait_on_arrival_min"], o["wait_range_min"]),
        "Total": with_range(o["total_min"], o["total_range_min"]),
    } for o in options]), hide_index=True, width="stretch")
    if result["too_close_to_call"]:
        st.write(f"**Too close to call:** {', '.join(result['too_close_to_call'])} are within 15 minutes of each other. "
                 "Pick whichever is easier for you.")
    st.caption("Total = rough travel time + the forecast published wait when you'd arrive. Travel is a straight-line "
               "estimate checked against a journey planner (typical error about 5 minutes), not live traffic.")
    points = pd.DataFrame([{"lat": o["lat"], "lon": o["lon"], "minutes": o["total_min"],
                            "label": f"{o['hospital']}: about {fmt(o['total_min'])} in total"} for o in options if o["lat"]])
    hospital_map(points, result.get("start_point"))


def chat_tab() -> None:
    try:
        health = get("/health")
    except httpx.HTTPError:
        health = {"chat": True}  # let the message below report the problem
    if not health.get("chat", True):
        st.info("The assistant runs only on the developer's own computer, because it uses a local AI model, so "
                "it is switched off in this online demo. The live board and \"Where should I go?\" work as normal.")
        st.info(RED_FLAGS)
        return
    st.caption("Ask where you'd likely be seen soonest, or about A&E fees, triage and alternatives. It can't diagnose "
               "and won't tell you whether you need care. Answers come from a small AI model and can take a few minutes.")
    history = st.session_state.setdefault("history", [])
    shown = st.session_state.setdefault("shown", [])  # what's on screen, including fixed safety replies
    for role, text in shown:
        st.chat_message(role).markdown(text)
    message = st.chat_input("e.g. Twisted ankle near Tsuen Wan MTR, where is quickest?")
    if not message:
        return
    st.chat_message("user").markdown(message)
    with st.chat_message("assistant"), st.spinner("Thinking (a small local model: this can take a few minutes)..."):
        try:
            response = post("/chat", {"message": message, "history": history}, timeout=CHAT_TIMEOUT_S)
            response.raise_for_status()
            data = response.json()
            reply = data["reply"]
            st.session_state["history"] = data["history"]
        except httpx.HTTPError:
            reply = "Sorry, I can't answer right now. If this could be an emergency, call 999 now or go to the nearest A&E."
        st.markdown(reply)
    shown += [("user", message), ("assistant", reply)]


def deserts_tab() -> None:
    st.write("**Coming in v2 (January 2027).** A map of how long it takes, by district, to be seen at the "
             "nearest-soonest A&E, by day and by night, weighted by where people live.")


def about_tab() -> None:
    st.markdown(
        "This is a student portfolio project. It forecasts the Hospital Authority's *published* A&E waiting-time "
        "estimates 1 to 3 hours ahead and adds a rough travel time, to suggest where a non-urgent patient is likely "
        "to be seen soonest. It is **not** an official Hospital Authority service and is not medical advice.\n\n"
        "- The forecast target is HA's published estimate, not how long patients actually waited.\n"
        "- How well it works, with every number reproducible: see `evals/reports/` in the code repository.\n"
        "- Nothing you type is stored. Chat history stays in this browser tab.\n\n"
        "Data: Hospital Authority A&E waiting times via DATA.GOV.HK; hospital locations from the Common Spatial "
        "Data Infrastructure; address lookup from the Address Lookup Service (OGCIO); guidance from Government "
        "press releases on info.gov.hk."
    )


def main() -> None:
    st.set_page_config(page_title="A&E Compass HK", layout="wide")
    st.title("A&E Compass HK")
    st.caption("Where you're likely to be seen soonest at a Hong Kong public A&E, for non-urgent problems.")
    st.warning(DISCLAIMER)
    st.error(RED_FLAGS)
    with st.sidebar:
        st.markdown(CRISIS)
        st.caption("Not medical advice. Not an official Hospital Authority service.")
    tabs = st.tabs(["Live board", "Where should I go?", "Ask the assistant", "Care deserts", "About"])
    for tab, render in zip(tabs, [board_tab, where_tab, chat_tab, deserts_tab, about_tab]):
        with tab:
            render()


main()

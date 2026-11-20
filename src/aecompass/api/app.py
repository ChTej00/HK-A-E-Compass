"""The web API: the recommender, forecasts and agent over HTTP, for the web page or any other client.

    uvicorn aecompass.api.app:app --port 8000      # then open http://localhost:8000/docs

An API is a program that answers requests from other programs instead of people. FastAPI turns ordinary
Python functions into web addresses ("endpoints"): `GET /waits` calls `waits()` and sends back its result
as JSON. The input and output shapes are declared as Pydantic classes, so FastAPI checks every request
(a missing or overlong field is rejected before our code runs) and writes the interactive page at /docs.

Endpoints use the same Toolbox the agent uses, so the page, the API and the agent can never disagree.

Privacy: nothing a user types is stored or logged. A chat's history lives in the user's browser session
and is sent with each message; the server forgets it when the reply is sent. Places and messages go in the
request body (POST), never in the URL, because web servers log URLs.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from aecompass.agent import providers
from aecompass.agent.loop import Agent, load_env

log = logging.getLogger("aecompass.api")

DISCLAIMER = (
    "Not medical advice and not an official Hospital Authority service. For non-life-threatening situations "
    "only. In an emergency, call 999. Waits are the Hospital Authority's published estimates for triage "
    "categories 4 and 5, plus a forecast; sicker patients are always seen first."
)
MAX_HISTORY = 20
CHAT_OFF_MESSAGE = (
    "The assistant runs only on the developer's own computer (it uses a local AI model), so it is switched "
    "off in this demo. The live board and \"Where should I go?\" work as normal."
)


def chat_enabled() -> bool:
    return os.environ.get("AECOMPASS_CHAT", "on").lower() not in ("off", "0", "false", "no")


class RecommendRequest(BaseModel):
    place: str = Field(min_length=2, max_length=200, examples=["Langham Place"])


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000, examples=["Sprained ankle near Mong Kok, where is quickest?"])
    history: list[Message] = Field(default_factory=list, max_length=MAX_HISTORY)


class ChatReply(BaseModel):
    reply: str
    handled_by: str  # which safety layer answered: rules, screen, agent, guard or fallback
    history: list[Message]


def refresh_loop(toolbox, minutes: float, stop: threading.Event) -> None:
    """Every few minutes, download the newest published waits and swap them in."""
    from aecompass.forecast.dataset import load_clean
    from aecompass.recommend.cli import refresh

    while not stop.wait(minutes * 60):
        try:
            refresh()
            toolbox.reload(load_clean())
            log.info("refreshed waits; data time %s", toolbox.data_time())
        except Exception as error:  # noqa: BLE001 - keep serving the last good data
            log.warning("refresh failed, keeping the previous data: %s", error)


def create_app(toolbox=None, llm=None, refresh_minutes: float | None = None, chat: bool | None = None) -> FastAPI:
    """Tests pass stand-ins; the real server loads data, models and the AI provider from `.env`.

    With the chat off (AECOMPASS_CHAT=off, used by the hosted demo) no AI model or guidance search is loaded.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        load_env()
        if app.state.chat is None:
            app.state.chat = chat_enabled()
        if app.state.toolbox is None:
            from aecompass.agent.tools import Toolbox

            app.state.toolbox = Toolbox.load(with_search=app.state.chat)
        if app.state.llm is None and app.state.chat:
            app.state.llm = providers.from_env()
        minutes = refresh_minutes if refresh_minutes is not None else float(os.environ.get("AECOMPASS_REFRESH_MINUTES", "0"))
        stop = threading.Event()
        if minutes > 0:
            threading.Thread(target=refresh_loop, args=(app.state.toolbox, minutes, stop), daemon=True).start()
        yield
        stop.set()

    app = FastAPI(
        title="A&E Compass HK",
        description=f"Where a non-urgent patient is likely to be seen soonest in Hong Kong public A&Es. {DISCLAIMER}",
        version="1.1",
        lifespan=lifespan,
    )
    app.state.toolbox, app.state.llm, app.state.chat = toolbox, llm, chat

    @app.get("/health")
    def health() -> dict:
        stamp = app.state.toolbox._stamp(app.state.toolbox.data_time())
        return {"status": "ok", "chat": app.state.chat, "model": getattr(app.state.llm, "name", None),
                "data_time_hkt": stamp["data_time_hkt"], "data_age_minutes": stamp["data_age_minutes"]}

    @app.get("/waits")
    def waits() -> dict:
        """Every A&E: the published wait now and the forecast for +1, +2 and +3 hours, with 80% ranges."""
        return {**app.state.toolbox.board(), "disclaimer": DISCLAIMER}

    @app.get("/forecast/{hospital}")
    def forecast(hospital: str) -> dict:
        try:
            return {**app.state.toolbox.forecast_wait(hospital), "disclaimer": DISCLAIMER}
        except ValueError as error:
            raise HTTPException(404, str(error)) from None

    @app.post("/recommend")
    def recommend(request: RecommendRequest) -> dict:
        """Where you would likely be seen soonest from a place: travel time plus the forecast wait on arrival."""
        try:
            result = app.state.toolbox.recommend(request.place)
        except ValueError as error:
            raise HTTPException(404, str(error)) from None
        coords = app.state.toolbox.coords
        for option in result["options_soonest_first"]:
            option["lat"], option["lon"] = coords.get(option["hospital"], (None, None))
        return {**result, "disclaimer": DISCLAIMER}

    @app.post("/chat")
    def chat(request: ChatRequest) -> ChatReply:
        """One message to the agent. Slow with a local model: allow several minutes."""
        if not app.state.chat:
            raise HTTPException(503, CHAT_OFF_MESSAGE)
        history = [m.model_dump() for m in request.history]
        agent = Agent(app.state.llm, app.state.toolbox)  # one per request: an Agent remembers its last reply
        reply = agent.reply(request.message, history)
        return ChatReply(reply=reply, handled_by=agent.handled_by, history=history[-MAX_HISTORY:])

    return app


app = create_app()

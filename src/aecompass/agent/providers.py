"""Which AI model the agent talks to. The agent itself does not know or care.

Every provider offers the same three operations, so swapping models changes nothing else:

    screen(system, text)                 -> "emergency" | "crisis" | "none"   (the safety screen)
    turn(system, messages, tools)        -> Turn: either a final answer or a list of tool calls
    add_tool_results(messages, results)  -> puts the tools' outputs into the conversation

Two providers:
- `OllamaLLM`: an open model running on this computer through Ollama. Free, private, slower, weaker.
- `AnthropicLLM`: Claude through the Anthropic API. Needs a paid API key.

Choose with the environment variable AECOMPASS_PROVIDER (`ollama` or `anthropic`); AECOMPASS_MODEL picks
the model within it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Literal

import httpx
from pydantic import BaseModel

CATEGORIES = ("emergency", "crisis", "none")


class Screen(BaseModel):
    """The safety screen's answer. A fixed shape, so the model cannot reply with anything else."""

    category: Literal["emergency", "crisis", "none"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Turn:
    """One reply from the model: a final answer, or a request to run tools."""

    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------------
# Ollama: an open model on this computer
# ---------------------------------------------------------------------------------------------------


def strip_reasoning(text: str) -> str:
    """Remove a model's private reasoning from its reply.

    Some open models write their reasoning into the reply, ending with `</think>`. The user must never see
    it: it is long, and it can contain exactly the speculation about symptoms that the agent must not give.
    """
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return text.split("<think>", 1)[0].strip()  # an unfinished reasoning block is dropped too


class OllamaLLM:
    """Talks to a local Ollama server over HTTP (http://localhost:11434 by default)."""

    def __init__(self, model: str = "qwen3:4b", host: str | None = None, client: httpx.Client | None = None):
        self.model = model
        self.name = f"ollama/{model}"
        host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        if not host.startswith("http"):
            host = f"http://{host}"
        # A laptop CPU can take minutes on a long prompt, so the timeout is generous.
        self.http = client or httpx.Client(base_url=host, timeout=httpx.Timeout(600, connect=5))
        self.think = False  # "thinking" models reason at length first; off keeps a laptop usable
        # Qwen3 also needs this written into the prompt, or it reasons anyway once tools are involved.
        self.system_suffix = " /no_think" if model.startswith("qwen3") else ""

    def _chat(self, payload: dict) -> dict:
        body = {"model": self.model, "stream": False, "options": {"temperature": 0}, **payload}
        if self.think is not None:
            body["think"] = self.think
        r = self.http.post("/api/chat", json=body)
        if r.status_code == 400 and "think" in r.text and self.think is not None:
            self.think = None  # this model has no thinking switch; ask again without it
            return self._chat(payload)
        r.raise_for_status()
        return r.json()["message"]

    def screen(self, system: str, text: str) -> str:
        message = self._chat({
            "messages": [{"role": "system", "content": system + self.system_suffix}, {"role": "user", "content": text}],
            "format": Screen.model_json_schema(),  # Ollama constrains the output to this JSON shape
        })
        return Screen.model_validate_json(message["content"]).category

    def turn(self, system: str, messages: list, tools: list[dict]) -> Turn:
        message = self._chat({
            "messages": [{"role": "system", "content": system + self.system_suffix}, *messages],
            "tools": [
                {"type": "function",
                 "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
                for t in tools
            ],
        })
        message["content"] = strip_reasoning(message.get("content") or "")
        message.pop("thinking", None)
        messages.append(message)
        calls = []
        for i, call in enumerate(message.get("tool_calls") or []):
            arguments = call["function"].get("arguments") or {}
            if isinstance(arguments, str):  # some models send the arguments as JSON text
                arguments = json.loads(arguments)
            calls.append(ToolCall(f"call_{i}", call["function"]["name"], arguments))
        return Turn(message["content"], calls)

    def add_tool_results(self, messages: list, results: list[tuple[ToolCall, str, bool]]) -> None:
        for call, output, _ in results:
            messages.append({"role": "tool", "tool_name": call.name, "content": output})


# ---------------------------------------------------------------------------------------------------
# Anthropic: Claude through the API
# ---------------------------------------------------------------------------------------------------

FALLBACK_BETA = "server-side-fallback-2026-07-01"  # lets the API retry on another model if one declines


class AnthropicLLM:
    def __init__(self, model: str = "claude-opus-5-5", messages_api=None):
        """`messages_api` defaults to `anthropic.Anthropic().beta.messages`; tests pass a stand-in."""
        if messages_api is None:
            import anthropic  # imported here so the project works without the SDK when using Ollama

            messages_api = anthropic.Anthropic().beta.messages
        self.api, self.model, self.name = messages_api, model, f"anthropic/{model}"

    def screen(self, system: str, text: str) -> str:
        response = self.api.parse(
            model=self.model, max_tokens=2000, system=system, output_format=Screen,
            output_config={"effort": "low"}, betas=[FALLBACK_BETA], fallbacks="default",
            messages=[{"role": "user", "content": text}],
        )
        return response.parsed_output.category

    def turn(self, system: str, messages: list, tools: list[dict]) -> Turn:
        response = self.api.create(
            model=self.model, max_tokens=16000, system=system, tools=tools,
            betas=[FALLBACK_BETA], fallbacks="default", messages=messages,
        )
        if response.stop_reason not in ("end_turn", "tool_use"):
            raise RuntimeError(f"stopped with {response.stop_reason}")  # refusal, max_tokens, ...
        messages.append({"role": "assistant", "content": response.content})
        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in response.content if b.type == "tool_use"]
        return Turn(text, calls if response.stop_reason == "tool_use" else [])

    def add_tool_results(self, messages: list, results: list[tuple[ToolCall, str, bool]]) -> None:
        messages.append({  # all results go back in one message
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": call.id, "content": output, "is_error": is_error}
                for call, output, is_error in results
            ],
        })


def from_env():
    provider = os.environ.get("AECOMPASS_PROVIDER", "ollama").lower()
    model = os.environ.get("AECOMPASS_MODEL")
    if provider == "anthropic":
        return AnthropicLLM(model) if model else AnthropicLLM()
    if provider == "ollama":
        return OllamaLLM(model) if model else OllamaLLM()
    raise ValueError(f"AECOMPASS_PROVIDER must be 'ollama' or 'anthropic', not {provider!r}")

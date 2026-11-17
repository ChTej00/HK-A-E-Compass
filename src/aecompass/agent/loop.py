"""The agent: three safety layers, then a tool-calling loop.

    message -> 1. fixed rules (safety.py)        emergency/crisis -> fixed reply, stop
            -> 2. AI safety screen (one call)     emergency/crisis -> fixed reply, stop
            -> 3. AI model with tools, in a loop  -> answer + fixed disclaimer

Layers 1 and 2 return fixed text, so an emergency reply never contains a hospital name or a waiting time.
If anything fails (the model is unreachable, it refuses, too many steps), the reply is a fixed safe
message: the agent "fails closed". Nothing the user types is written to disk or logged.

Which model is used is decided in `providers.py`; this file works the same with any of them.
"""

from __future__ import annotations

import os
from pathlib import Path

from aecompass.agent import providers, safety
from aecompass.agent.prompts import CLASSIFIER_PROMPT, DISCLAIMER, SAFE_FALLBACK, SYSTEM_PROMPT
from aecompass.agent.tools import TOOL_SPECS

MAX_STEPS = 6  # a question needs one or two tool calls; more than this means something is going wrong
# Only the most recent turns are sent to the model. A small local model reads about 4,000 tokens at a time;
# if a long chat overflowed that, the oldest text would be cut first, and the oldest text is the safety rules.
MAX_HISTORY_MESSAGES = 6
REPLIES = {"emergency": safety.EMERGENCY_REPLY, "crisis": safety.CRISIS_REPLY}


def load_env(path: Path = Path(".env")) -> None:
    """Read KEY=value lines from a local .env file (git-ignored) into the environment, if it exists."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class Agent:
    def __init__(self, llm, toolbox):
        """`llm` is a provider from providers.py (or a stand-in in tests); `toolbox` runs the tools."""
        self.llm, self.toolbox = llm, toolbox
        self.model = getattr(llm, "name", "unknown")
        # What happened on the most recent reply, for the evals: which layer answered and what the tools
        # returned. Kept in memory only and overwritten on the next message; never written to disk here.
        self.handled_by, self.trace, self.last_error = None, [], None

    @classmethod
    def from_env(cls) -> "Agent":
        from aecompass.agent.tools import Toolbox

        load_env()
        return cls(providers.from_env(), Toolbox.load())

    def reply(self, text: str, history: list | None = None) -> str:
        """Answer one user message. `history` is the earlier turns of this session, kept by the caller in memory."""
        history = history if history is not None else []
        self.trace, self.last_error = [], None
        flagged = safety.check(text).kind  # layer 1: no AI involved
        self.handled_by = "rules" if flagged else None
        try:
            flagged = flagged or self.llm.screen(CLASSIFIER_PROMPT, text)  # layer 2
            if flagged in REPLIES:
                self.handled_by = self.handled_by or "screen"
                return REPLIES[flagged]
            recent = history[-MAX_HISTORY_MESSAGES:]
            answer = self._converse(recent + [{"role": "user", "content": text}])  # layer 3
        except Exception as error:  # noqa: BLE001 - whatever went wrong, the user gets a safe message, not a stack trace
            self.handled_by = self.handled_by or "fallback"
            self.last_error = f"{type(error).__name__}: {error}"[:300]  # for the evals; never contains user text
            return REPLIES.get(flagged, SAFE_FALLBACK)
        # Layer 4: check what the model wrote before anyone sees it.
        problem = safety.check_answer(answer, [step["output"] for step in self.trace])
        if problem:
            self.handled_by, self.last_error = "guard", problem
            return f"{safety.GUARD_REPLIES[problem]}\n\n{DISCLAIMER}"
        self.handled_by = "agent"
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": answer}]
        return f"{answer}\n\n{DISCLAIMER}"

    def _converse(self, messages: list) -> str:
        """The tool-calling loop: ask the model; if it wants tools, run them and ask again."""
        messages = list(messages)
        for _ in range(MAX_STEPS):
            turn = self.llm.turn(SYSTEM_PROMPT, messages, TOOL_SPECS)
            if not turn.calls:
                if not turn.text:
                    raise RuntimeError("empty answer")
                return turn.text
            results = [(call, *self.toolbox.run(call.name, call.arguments)) for call in turn.calls]
            self.trace += [{"tool": c.name, "arguments": c.arguments, "output": out, "is_error": err} for c, out, err in results]
            self.llm.add_tool_results(messages, results)
        raise RuntimeError("too many steps")

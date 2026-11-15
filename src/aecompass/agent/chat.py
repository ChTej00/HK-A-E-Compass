"""Talk to the agent in the terminal.

    python -m aecompass.agent.chat             # uses the model set in .env (local Ollama by default)
    python -m aecompass.agent.chat --refresh   # fetch the newest published waits first

The conversation lives in memory for this session only and is not saved by this program. With Ollama
your messages never leave this computer; with the Anthropic provider they are sent to Anthropic.
"""

from __future__ import annotations

import argparse

from aecompass.agent.loop import Agent
from aecompass.agent.prompts import DISCLAIMER
from aecompass.recommend.cli import refresh


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true")
    if parser.parse_args().refresh:
        refresh()
    agent, history = Agent.from_env(), []
    print(f"A&E Compass HK. {DISCLAIMER}")
    print(f"Model: {agent.model}. Type 'quit' to stop.\n")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in {"quit", "exit"}:
            break
        if text:
            print(f"\n{agent.reply(text, history)}\n")


if __name__ == "__main__":
    main()

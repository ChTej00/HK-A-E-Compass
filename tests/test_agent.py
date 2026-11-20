"""The agent is tested with stand-ins for the AI model, so these run with no API key, no Ollama and no network."""

import json
from types import SimpleNamespace

import httpx
import pytest

from aecompass.agent import safety
from aecompass.agent.loop import MAX_HISTORY_MESSAGES, MAX_STEPS, Agent
from aecompass.agent.prompts import DISCLAIMER, SAFE_FALLBACK
from aecompass.agent.providers import AnthropicLLM, OllamaLLM, ToolCall, Turn, strip_reasoning
from aecompass.agent.tools import TOOL_SPECS


class FakeLLM:
    """Plays back scripted turns and records what it was asked."""

    name = "fake"

    def __init__(self, screen="none", turns=()):
        self._screen, self.turns, self.screened, self.asked, self.results = screen, list(turns), [], 0, []

    def screen(self, system, text):
        self.screened.append(text)
        if isinstance(self._screen, Exception):
            raise self._screen
        return self._screen

    def turn(self, system, messages, tools):
        self.asked += 1
        return self.turns.pop(0)

    def add_tool_results(self, messages, results):
        self.results.append(results)


class FakeToolbox:
    def __init__(self):
        self.calls = []

    def run(self, name, arguments):
        self.calls.append((name, arguments))
        return ('{"ok": true}', False) if name != "broken" else ("Error: no data", True)


# --- the agent, whatever the model -------------------------------------------------------------------


@pytest.mark.parametrize("message", ["I have chest pain, which A&E is fastest?", "我胸口痛，邊間急症室最快？"])
def test_rule_layer_answers_emergencies_without_calling_the_model(message):
    llm, toolbox = FakeLLM(), FakeToolbox()
    reply = Agent(llm, toolbox).reply(message)
    assert reply == safety.EMERGENCY_REPLY and "999" in reply
    assert not llm.screened and not llm.asked and not toolbox.calls


def test_crisis_language_gets_the_crisis_lines_and_nothing_else():
    llm = FakeLLM()
    reply = Agent(llm, FakeToolbox()).reply("I want to kill myself. Which A&E has the shortest wait?")
    assert reply == safety.CRISIS_REPLY
    assert "2896 0000" in reply and "2382 0000" in reply and "999" in reply and "Hospital" not in reply
    assert not llm.screened and not llm.asked


def test_ai_screen_catches_wording_the_rules_miss():
    message = "It feels like an elephant is sitting on my chest"
    assert safety.check(message).kind is None  # the rules do not know this phrasing
    llm, toolbox = FakeLLM(screen="emergency"), FakeToolbox()
    assert Agent(llm, toolbox).reply(message) == safety.EMERGENCY_REPLY
    assert llm.screened == [message] and not llm.asked and not toolbox.calls


def test_tool_loop_runs_tools_then_returns_the_answer_with_the_disclaimer():
    calls = [ToolCall("a", "recommend", {"place": "Mong Kok"}), ToolCall("b", "broken", {})]
    llm = FakeLLM(turns=[Turn(calls=calls), Turn(text="Kwong Wah looks soonest.")])
    toolbox, history = FakeToolbox(), []
    reply = Agent(llm, toolbox).reply("Sprained ankle in Mong Kok, where is quickest?", history)
    assert reply == f"Kwong Wah looks soonest.\n\n{DISCLAIMER}"
    assert toolbox.calls == [("recommend", {"place": "Mong Kok"}), ("broken", {})]
    assert [(c.id, is_error) for c, _, is_error in llm.results[0]] == [("a", False), ("b", True)]
    assert [m["role"] for m in history] == ["user", "assistant"]  # kept in memory for the session only


def test_only_recent_turns_are_sent_to_the_model():
    class Recording(FakeLLM):
        def turn(self, system, messages, tools):
            self.seen = list(messages)
            return Turn(text="ok")

    llm = Recording()
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"old {i}"} for i in range(20)]
    Agent(llm, FakeToolbox()).reply("Wait at Pok Oi?", history)
    assert len(llm.seen) == MAX_HISTORY_MESSAGES + 1 and llm.seen[-1]["content"] == "Wait at Pok Oi?"
    assert llm.seen[0]["role"] == "user" and len(history) == 22  # the session keeps everything; the model sees the tail


def test_failures_fail_closed_to_a_safe_message():
    silent = Agent(FakeLLM(turns=[Turn()]), FakeToolbox()).reply("Wait at Pok Oi?")
    assert silent == SAFE_FALLBACK and "999" in silent
    looping = FakeLLM(turns=[Turn(calls=[ToolCall("a", "get_current_waits", {})])] * (MAX_STEPS + 1))
    assert Agent(looping, FakeToolbox()).reply("Wait at Pok Oi?") == SAFE_FALLBACK
    assert looping.asked == MAX_STEPS
    offline = Agent(FakeLLM(screen=ConnectionError("model unreachable")), FakeToolbox())
    assert offline.reply("Wait at Pok Oi?") == SAFE_FALLBACK
    assert offline.reply("my chest hurts") == safety.EMERGENCY_REPLY  # the rules still work with no model


def test_tool_schemas_are_strict():
    for spec in TOOL_SPECS:
        schema = spec["input_schema"]
        assert spec["strict"] and schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


# --- the Ollama provider, against a fake local server --------------------------------------------------


def ollama_with(handler):
    requests = []

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        return handler(body)

    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle))
    return OllamaLLM("test-model", client=client), requests


def test_ollama_screen_asks_for_a_fixed_json_shape():
    llm, requests = ollama_with(lambda body: httpx.Response(200, json={"message": {"content": '{"category": "crisis"}'}}))
    assert llm.screen("screen prompt", "some text") == "crisis"
    sent = requests[0]
    assert sent["format"]["properties"]["category"]["enum"] == ["emergency", "crisis", "none"]
    assert sent["messages"][0] == {"role": "system", "content": "screen prompt"} and sent["stream"] is False
    assert OllamaLLM("qwen3:4b", client=llm.http).system_suffix == " /no_think"


def test_ollama_turn_reads_tool_calls_and_sends_results_back():
    replies = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "recommend", "arguments": {"place": "Sha Tin"}}}]},
        {"role": "assistant", "content": "Prince of Wales looks soonest."},
    ]
    llm, requests = ollama_with(lambda body: httpx.Response(200, json={"message": replies.pop(0)}))
    messages = [{"role": "user", "content": "from Sha Tin?"}]
    turn = llm.turn("system prompt", messages, TOOL_SPECS)
    assert [(c.name, c.arguments) for c in turn.calls] == [("recommend", {"place": "Sha Tin"})]
    assert requests[0]["tools"][0]["function"]["parameters"] == TOOL_SPECS[0]["input_schema"]
    llm.add_tool_results(messages, [(turn.calls[0], '{"ok": true}', False)])
    assert messages[-1] == {"role": "tool", "tool_name": "recommend", "content": '{"ok": true}'}
    final = llm.turn("system prompt", messages, TOOL_SPECS)
    assert final.text == "Prince of Wales looks soonest." and not final.calls
    assert [m["role"] for m in requests[1]["messages"]] == ["system", "user", "assistant", "tool"]


def test_private_reasoning_never_reaches_the_user():
    leaked = "The user may have a fracture...\n</think>\n\nKwong Wah looks soonest."
    assert strip_reasoning(leaked) == "Kwong Wah looks soonest."
    assert strip_reasoning("<think>hmm</think>Answer") == "Answer"
    assert strip_reasoning("Answer <think>unfinished reasoning") == "Answer"
    assert strip_reasoning("Plain answer") == "Plain answer"
    leaky = {"role": "assistant", "content": "Let me think about the symptoms.</think>Go to Pok Oi.", "thinking": "secret"}
    llm, _ = ollama_with(lambda body: httpx.Response(200, json={"message": dict(leaky)}))
    messages = []
    assert llm.turn("system", messages, TOOL_SPECS).text == "Go to Pok Oi."
    assert messages[-1]["content"] == "Go to Pok Oi." and "thinking" not in messages[-1]  # not kept in history either


def test_ollama_retries_without_the_thinking_switch_when_the_model_has_none():
    def handler(body):
        if "think" in body:
            return httpx.Response(400, json={"error": '"test-model" does not support thinking'})
        return httpx.Response(200, json={"message": {"content": '{"category": "none"}'}})

    llm, requests = ollama_with(handler)
    assert llm.screen("p", "t") == "none" and len(requests) == 2 and "think" not in requests[1]


# --- the Anthropic provider, against a fake SDK ---------------------------------------------------------


def block(**fields):
    return SimpleNamespace(**fields)


class FakeMessagesAPI:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=SimpleNamespace(category="emergency"))


def test_anthropic_turn_and_single_message_of_results():
    api = FakeMessagesAPI([
        SimpleNamespace(stop_reason="tool_use", content=[block(type="tool_use", id="t1", name="recommend", input={"place": "Central"}),
                                                         block(type="tool_use", id="t2", name="get_current_waits", input={})]),
        SimpleNamespace(stop_reason="refusal", content=[]),
    ])
    llm = AnthropicLLM("claude-test", messages_api=api)
    messages = [{"role": "user", "content": "from Central?"}]
    turn = llm.turn("system prompt", messages, TOOL_SPECS)
    assert [c.id for c in turn.calls] == ["t1", "t2"] and api.calls[0]["tools"] == TOOL_SPECS
    llm.add_tool_results(messages, [(turn.calls[0], "{}", False), (turn.calls[1], "Error: x", True)])
    assert messages[-1]["role"] == "user" and [r["tool_use_id"] for r in messages[-1]["content"]] == ["t1", "t2"]
    assert messages[-1]["content"][1]["is_error"] is True
    with pytest.raises(RuntimeError, match="refusal"):
        llm.turn("system prompt", messages, TOOL_SPECS)
    assert llm.screen("p", "t") == "emergency"


# --- layer 4: the model's own answer is checked before it is shown ------------------------------------


def test_answer_guard_replaces_answers_that_discourage_care_or_invent_a_link():
    told_off = Agent(FakeLLM(turns=[Turn(text="You don't need to go to A&E for this.")]), FakeToolbox())
    reply = told_off.reply("small cut on my finger")
    assert "don't need" not in reply and "can't judge" in reply and told_off.handled_by == "guard"

    judging = Agent(FakeLLM(turns=[Turn(text="Kwong Wah is quickest. This is not an emergency.")]), FakeToolbox())
    assert "not an emergency" not in judging.reply("sore wrist, Mong Kok")

    made_up = Turn(text="The target is 20 minutes (https://www.gov.hk/made/up.htm).")
    inventing = Agent(FakeLLM(turns=[Turn(calls=[ToolCall("a", "search_triage_guidance", {"query": "x"})]), made_up]), FakeToolbox())
    reply = inventing.reply("what is the urgent target?")
    assert "gov.hk/made" not in reply and "20 minutes" not in reply and inventing.handled_by == "guard"


def test_answer_guard_lets_good_answers_through():
    assert safety.check_answer("I can't assess if this is serious. If you're worried, go to the nearest A&E.", []) is None
    assert safety.check_answer("Kwong Wah looks soonest, about 50 minutes for non-urgent patients.", []) is None
    source = '{"url": "https://www.info.gov.hk/gia/general/202601/01/P2026010100712.htm", "text": "see www.pcdirectory.gov.hk"}'
    assert safety.check_answer("The fee is $400 (https://www.info.gov.hk/gia/general/202601/01/P2026010100712.htm).", [source]) is None
    assert safety.check_answer("There is a directory at https://www.pcdirectory.gov.hk/.", [source]) is None
    assert safety.check_answer("See https://example.com/fees", [source]) == "invented link"


# --- the guidance tool labels sources that predate the 2026 fee change --------------------------------


def test_guidance_tool_lists_current_sources_first_and_warns_about_old_fees():
    from aecompass.agent.tools import OLD_FEES_WARNING, Toolbox
    from aecompass.kb.search import Hit
    from aecompass.kb.sources import BY_ID

    class FakeSearch:
        def search(self, query, k):
            order = ["lcq22-ae-services", "fee-reform-day1", "surge-measures-2025", "fee-list-2026"]
            return [Hit(f"{sid}-0", BY_ID[sid], f"text from {sid}", 1.0) for sid in order]

    result = Toolbox(None, None, None, None, FakeSearch()).search_triage_guidance("refund")
    titles = [p["source_title"] for p in result["passages"]]
    assert titles == [BY_ID[s].title for s in ["fee-reform-day1", "fee-list-2026", "lcq22-ae-services", "surge-measures-2025"]]
    assert ["warning" in p for p in result["passages"]] == [False, False, True, True]
    assert result["passages"][2]["warning"] == OLD_FEES_WARNING and "without a warning" in result["note"]

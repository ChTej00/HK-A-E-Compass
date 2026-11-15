"""The safety floor: a fixed check that runs on every message *before* any AI model sees it.

If a message mentions a possible emergency, the reply is "Call 999 now" and nothing about waiting times.
If it mentions suicide or self-harm, the reply is crisis lines and nothing else. Both replies are fixed
text, so they cannot be talked out of, reworded or mixed with a hospital comparison.

This is a list of patterns, so it only catches wording it knows. It is deliberately trigger-happy: "no
chest pain" still triggers, because wrongly showing 999 costs little and wrongly comparing waiting times
for a heart attack could cost a life. Wording it misses is the AI model's job (the same rules are in its
instructions), and `evals/run_safety.py` measures both layers.

Nothing here is stored or logged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

EMERGENCY_REPLY = (
    "Call 999 now.\n\n"
    "What you describe could be an emergency. Do not wait and do not compare hospitals: call 999 or go to "
    "the nearest A&E immediately. If you are with the person, stay with them until help arrives.\n\n"
    "請立即致電 999。你描述的情況可能屬於緊急情況，請勿等候或比較醫院，應立即致電 999 或前往最近的急症室。\n\n"
    "This is not medical advice and not an official Hospital Authority service."
)
CRISIS_REPLY = (
    "You don't have to face this alone. Please talk to someone now:\n\n"
    "- The Samaritans: 2896 0000 (24 hours, multilingual)\n"
    "- Suicide Prevention Services: 2382 0000 (24 hours)\n"
    "- If you are in immediate danger, call 999.\n\n"
    "你不需要獨自面對。請立即聯絡：撒瑪利亞會 2896 0000（24 小時，多種語言）、"
    "生命熱線 2382 0000（24 小時）；如有即時危險，請致電 999。"
)

# Each entry: (label, pattern). English patterns run on lower-cased text with apostrophes removed.
CRISIS = [
    ("suicide", r"\bsuicid|\bkill(ing)? (myself|himself|herself|themselves)\b|\bend(ing)? (my|his|her|their) (own )?life\b|\btake my own life\b"),
    ("wants to die", r"\b(want|wants|wanted|wish|going) to die\b|\bdont want to (live|be alive|be here)\b|\bno reason to live\b|\bbetter off dead\b|\bbetter off without me\b"),
    ("self-harm", r"\bself[- ]?harm|\b(hurt|hurting|harm|harming|cut|cutting) (myself|himself|herself)\b"),
    ("自殺", r"自殺|輕生|想死|唔想活|不想活|唔想生存|了結(自己|生命)|結束(自己|生命)|自殘|𠝹手|割脈|跳樓"),
]
EMERGENCY = [
    ("chest pain", r"\bchest (pain|pains|tightness|pressure|hurts|is hurting|feels tight)|\b(pain|tightness|pressure|tight|crushing|squeezing)\b[^.?!]{0,25}\bchest\b|\bheart attack\b"),
    ("breathing", r"\b(cant|cannot|can not|couldnt|unable to|hard to|trouble|difficulty|struggling to|struggling for) breath|\bshort(ness)? of breath\b|\bnot breathing\b|\bstopped breathing\b|\bgasping\b|\bchoking\b|\b(lips|face) (are |is |have |has )?(turning |turned |gone |going )?blue\b"),
    ("stroke", r"\bstroke\b|\bface (is |has )?(droop|drooping|drooped)|\b(droop|drooping|lopsided)[^.?!]{0,20}\bface\b|\bface[^.?!]{0,20}\b(droop|drooping|lopsided)|\bslurr(ed|ing)\b|\b(sudden|suddenly)[^.?!]{0,30}\b(numb|numbness|weak|weakness|cant (move|lift|speak|see))\b|\bcant (move|lift|feel) (my|his|her|one) (arm|leg|side)\b"),
    ("bleeding", r"\b(heavy|heavily|severe|severely|a lot of|lots of|uncontrolled|wont stop|will not stop|doesnt stop|cant stop)[^.?!]{0,20}\bbleed|\bbleed(ing)?[^.?!]{0,25}\b(heavily|wont stop|will not stop|not stopping|doesnt stop|everywhere|a lot)\b|\b(vomit|vomiting|vomited|throwing up|coughing|coughed|coughing up)[^.?!]{0,10}\bblood\b"),
    ("unconscious", r"\bunconscious|\bunresponsive\b|\bnot responding\b|\b(passed|blacked) out\b|\bcollapsed\b|\bfainted\b|\bwont wake\b|\bcant wake\b|\bnot waking\b"),
    ("seizure", r"\bseizure|\bconvuls|\bfitting\b|\bhaving a fit\b"),
    ("allergic reaction", r"\banaphyla|\b(throat|tongue|lips|face) (is |are )?(swelling|swollen|closing)|\bsevere(ly)? allerg"),
    ("overdose or poisoning", r"\boverdos|\bpoison|\btook too many\b|\bswallowed (bleach|detergent|a battery|batteries)\b"),
    ("severe injury", r"\bsevere(ly)? burn|\bhit by a (car|bus|truck|taxi|van)\b|\bfell from (a height|the \w+ floor)\b|\bstabbed\b|\bbone (is )?sticking out\b|\bhead injury\b"),
    ("worst headache", r"\bworst headache\b|\bthunderclap\b"),
    ("胸口痛", r"胸口痛|心口痛|胸痛|心臟病發|心絞痛|胸口(好)?(翳|實|緊)"),
    ("呼吸困難", r"(抖|唞|透|呼吸)唔到氣|唔夠氣|呼吸困難|呼吸唔到|氣促|窒息|哽(親|住)|嘴唇發紫"),
    ("中風", r"中風|口眼歪斜|嘴歪|半邊身(麻|無力|冇力|郁唔到)|講嘢唔清|說話不清|突然(手腳)?(麻痺|無力|冇力)"),
    ("大量出血", r"大量(出血|流血)|流血不止|止唔到血|血流不止|不停流血|嘔血|吐血|咳血"),
    ("昏迷", r"昏迷|不省人事|暈咗|暈倒|叫唔醒|冇反應|失去知覺|冇知覺"),
    ("抽搐", r"抽搐|抽筋發作|癲癇|發羊吊"),
    ("其他", r"嚴重過敏|喉嚨腫|食錯藥|服藥過量|中毒|嚴重燒傷|車禍|撞車"),
]
_CRISIS = [(label, re.compile(pattern)) for label, pattern in CRISIS]
_EMERGENCY = [(label, re.compile(pattern)) for label, pattern in EMERGENCY]


@dataclass(frozen=True)
class SafetyResult:
    kind: str | None  # "crisis", "emergency" or None
    matched: str | None
    reply: str | None


def normalise(text: str) -> str:
    text = text.lower().replace("’", "'").replace("'", "")
    return re.sub(r"\s+", " ", text)


def check(text: str) -> SafetyResult:
    """Crisis language wins over emergency language: someone who has taken an overdose on purpose needs both
    999 and the crisis lines, and the crisis reply carries both."""
    clean = normalise(text)
    for label, pattern in _CRISIS:
        if pattern.search(clean):
            return SafetyResult("crisis", label, CRISIS_REPLY)
    for label, pattern in _EMERGENCY:
        if pattern.search(clean):
            return SafetyResult("emergency", label, EMERGENCY_REPLY)
    return SafetyResult(None, None, None)

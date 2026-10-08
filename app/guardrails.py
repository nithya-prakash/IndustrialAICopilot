"""Prompt-injection screen for retrieved/tool text.

Pattern-based and deliberately conservative: it flags instruction-like content
so the diagnosis can disclose it in `limitations`; it does not rewrite or drop
the text (the agent prompt already treats tool output as data). A regex screen
is a tripwire, not a defence on its own: paraphrased, non-English or obfuscated
attacks get through (measured: evaluation/injection_eval.py, results in the README).
INJECTION_SCANNER=llm_guard adds llm-guard's classifier on top of the regex screen.
"""

import re
from functools import lru_cache

from app.config import get_settings

_PATTERNS: dict[str, re.Pattern] = {
    "override_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|your)\b.{0,30}"
        r"\b(instructions?|rules?|prompts?|guidelines?)\b",
        re.I | re.S,
    ),
    "reveal_system_prompt": re.compile(
        r"\b(reveal|show|print|repeat|output)\b.{0,30}\b(system|hidden|initial)\b.{0,15}\b(prompt|instructions?)\b",
        re.I | re.S,
    ),
    "role_hijack": re.compile(r"\b(you are now|act as|pretend to be|new instructions?:)\b", re.I),
    "forged_tool_or_citation": re.compile(
        r"(<\s*/?\s*(system|assistant|tool_use|tool_result)\s*>|\"type\"\s*:\s*\"tool_use\")", re.I
    ),
    "suppress_safety": re.compile(
        r"\b(do not|don't|never)\b.{0,20}\b(escalate|require approval|flag|mention|report)\b",
        re.I | re.S,
    ),
    "set_confidence_or_approval": re.compile(
        r"\b(set|report|mark)\b.{0,20}\b(confidence|severity)\b.{0,15}\b(to|as)\b"
        r"|\bapproval\b.{0,15}\b(not required|unnecessary)\b",
        re.I | re.S,
    ),
}


@lru_cache
def _llm_guard_scanner():
    """llm-guard's PromptInjection classifier (a local transformer model, downloaded on
    first use). Optional: enable with INJECTION_SCANNER=llm_guard and `pip install llm-guard`."""
    from llm_guard.input_scanners import PromptInjection

    return PromptInjection(threshold=0.5)


def scan_text(text: str) -> list[str]:
    """Names of the injection patterns found in `text` (empty list = clean)."""
    found = [name for name, pattern in _PATTERNS.items() if pattern.search(text or "")]
    if text and get_settings().injection_scanner == "llm_guard":
        if not _llm_guard_scanner().scan(text)[1]:
            found.append("llm_guard_prompt_injection")
    return found


def scan_obj(value: object) -> list[str]:
    """scan_text over every string inside a nested dict/list tool result."""
    found: set[str] = set()
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            found.update(scan_text(item))
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list | tuple):
            stack.extend(item)
    return sorted(found)


# --- Unsafe-action filter ---------------------------------------------------------------------
# The agent's recommended action/checks go to a technician. Whatever the model (or text injected
# into its context) suggests, a recommendation that bypasses a safety device, skips lockout,
# pushes equipment past its rating or tells someone to ignore an alarm must not be shown as
# advice. This is a rule-based screen for those few high-consequence cases, not a safety
# system: it cannot judge advice in general, and sentences containing a negation
# ("do not bypass the interlock") are treated as safe.
_NEGATION = re.compile(
    r"\b(not|never|don't|dont|avoid|must not|mustn't|shouldn't|cannot|can't|prohibited|"
    r"forbidden)\b",
    re.I,
)
_UNSAFE_ACTIONS: dict[str, re.Pattern] = {
    "bypass_safety_device": re.compile(
        r"\b(bypass|disable|defeat|jumper|short[- ]?out|override|remove|take off|disconnect)\w*\b"
        r".{0,40}\b(interlock|thermal (cut-?out|protection|switch|overload)|"
        r"overload (relay|protection)|safety (switch|circuit|device|relay|guard)|e-?stop|"
        r"emergency stop|guards?|covers?|protection|trip)\b",
        re.I | re.S,
    ),
    "skip_isolation": re.compile(
        r"\b(without|skip(ping)?|no need (to|for))\b.{0,30}"
        r"\b(lock(ing|ed)? ?-?out|tag ?-?out|isolat\w+|"
        r"de-?energi[sz]\w+|power(ing)? (off|down)|disconnect\w*)\b",
        re.I | re.S,
    ),
    "work_on_live_equipment": re.compile(
        r"\b(while|when)\b.{0,20}\b(running|energi[sz]ed|live|powered)\b.{0,50}"
        r"\b(inspect|touch|clean|adjust|replace|reach|open|service|grease)\w*|"
        r"\b(inspect|touch|clean|adjust|replace|reach into|open|service|grease)\w*\b.{0,60}"
        r"\b(while|when)\b.{0,20}\b(running|energi[sz]ed|live|powered)\b",
        re.I | re.S,
    ),
    "exceed_ratings": re.compile(
        r"\b(1[1-9]\d|[2-9]\d\d)\s?%\s*(of\s+)?(rated\s+|nameplate\s+|full[- ]load\s+)?"
        r"(load|current|speed|amperage|rating)\b|"
        r"\b(run|operate|overload|increase)\w*\b.{0,40}\b(above|beyond|over|more than)\b.{0,20}"
        r"\b(rated|nameplate|full[- ]load|maximum)\b",
        re.I | re.S,
    ),
    "ignore_alarm": re.compile(
        r"\b(ignore|silence|mute|suppress|disregard)\w*\b.{0,25}"
        r"\b(alarm|fault|warning|trip|alert)\b",
        re.I | re.S,
    ),
}
UNSAFE_ACTION_FALLBACK = (
    "Recommendation withheld: it conflicted with basic safety rules. Isolate and lock out the "
    "equipment and have a qualified supervisor decide the next step."
)


def unsafe_action_categories(text: str) -> list[str]:
    """Categories of unsafe advice in `text`, sentence by sentence (negated sentences pass)."""
    found: set[str] = set()
    for sentence in re.split(r"(?<=[.!?;\n])\s+", text or ""):
        if _NEGATION.search(sentence):
            continue
        found.update(name for name, pattern in _UNSAFE_ACTIONS.items() if pattern.search(sentence))
    return sorted(found)


def sanitize_recommendations(action: str, checks: list[str]) -> tuple[str, list[str], list[str]]:
    """Replaces an unsafe recommended action with a safe fallback and drops unsafe checks.
    Returns (action, checks, categories_blocked)."""
    blocked = set(unsafe_action_categories(action))
    safe_checks = []
    for check in checks:
        categories = unsafe_action_categories(check)
        blocked.update(categories)
        if not categories:
            safe_checks.append(check)
    safe_action = UNSAFE_ACTION_FALLBACK if unsafe_action_categories(action) else action
    return safe_action, safe_checks, sorted(blocked)

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

"""Prompt-injection screen for retrieved/tool text.

Pattern-based and deliberately conservative: it flags instruction-like content
so the diagnosis can disclose it in `limitations`; it does not rewrite or drop
the text (the agent prompt already treats tool output as data). A regex screen
is a tripwire, not a defence on its own: paraphrased or non-English attacks
will get through. Measured coverage lives in tests/test_guardrails.py.
"""
import re

_PATTERNS: dict[str, re.Pattern] = {
    "override_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|your)\b.{0,30}"
        r"\b(instructions?|rules?|prompts?|guidelines?)\b", re.I | re.S),
    "reveal_system_prompt": re.compile(
        r"\b(reveal|show|print|repeat|output)\b.{0,30}\b(system|hidden|initial)\b.{0,15}\b(prompt|instructions?)\b",
        re.I | re.S),
    "role_hijack": re.compile(r"\b(you are now|act as|pretend to be|new instructions?:)\b", re.I),
    "forged_tool_or_citation": re.compile(
        r"(<\s*/?\s*(system|assistant|tool_use|tool_result)\s*>|\"type\"\s*:\s*\"tool_use\")", re.I),
    "suppress_safety": re.compile(
        r"\b(do not|don't|never)\b.{0,20}\b(escalate|require approval|flag|mention|report)\b", re.I | re.S),
    "set_confidence_or_approval": re.compile(
        r"\b(set|report|mark)\b.{0,20}\b(confidence|severity)\b.{0,15}\b(to|as)\b|\bapproval\b.{0,15}\b(not required|unnecessary)\b",
        re.I | re.S),
}


def scan_text(text: str) -> list[str]:
    """Names of the injection patterns found in `text` (empty list = clean)."""
    return [name for name, pattern in _PATTERNS.items() if pattern.search(text or "")]


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
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return sorted(found)

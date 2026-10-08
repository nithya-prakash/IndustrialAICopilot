"""Central validation of tool arguments, run before any tool executes.

Models choose tool arguments, and a prompt-injected or confused model can send garbage:
missing or unknown keys, wrong types, oversized strings, malformed UUIDs or timestamps. Rejecting
them here (with a message the model can act on) keeps handlers simple and keeps untrusted
strings out of queries, embeddings and calculators.
"""

import uuid
from datetime import datetime

from app.tools.definitions import TOOL_DEFINITIONS

MAX_STRING_CHARS = 2000
MAX_LENGTHS = {"query": 500, "expression": 200, "section": 200, "metric": 64, "equipment_id": 128}
UUID_FIELDS = {"document_id", "image_analysis_id", "diagnosis_id"}
TIME_FIELDS = {"start_time", "end_time"}
_SCHEMAS = {t["name"]: t["input_schema"] for t in TOOL_DEFINITIONS}


def validate_tool_input(name: str, tool_input: object) -> str | None:
    """Returns an error message, or None if the arguments are acceptable."""
    schema = _SCHEMAS.get(name)
    if schema is None:
        return f"Unknown tool: {name}"
    if not isinstance(tool_input, dict):
        return "Tool arguments must be a JSON object"
    properties = schema.get("properties", {})
    unknown = sorted(set(tool_input) - set(properties))
    if unknown:
        return f"Unknown argument(s): {', '.join(unknown)}"
    missing = [key for key in schema.get("required", []) if tool_input.get(key) in (None, "")]
    if missing:
        return f"Missing required argument(s): {', '.join(missing)}"
    for key, value in tool_input.items():
        if properties[key].get("type") == "string":
            if not isinstance(value, str):
                return f"Argument {key} must be a string"
            if len(value) > MAX_LENGTHS.get(key, MAX_STRING_CHARS):
                return f"Argument {key} is too long"
        if key in UUID_FIELDS:
            try:
                uuid.UUID(value)
            except (ValueError, AttributeError, TypeError):
                return f"Argument {key} must be a UUID"
        if key in TIME_FIELDS:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                return f"Argument {key} must be an ISO 8601 timestamp"
    return None

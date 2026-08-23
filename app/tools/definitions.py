"""Tool schemas in Anthropic's tool-use format (name/description/
input_schema). Kept as plain dicts rather than a framework abstraction —
seven tools with no sub-agents does not need one (see docs/
architecture-decisions.md: "why not a multi-agent architecture").
"""

TOOL_DEFINITIONS = [
    {
        "name": "search_technical_documents",
        "description": (
            "Search the equipment manuals/documentation for information relevant to a "
            "question. Returns a grounded answer with citations to the source manual "
            "sections. Use this first for any question that might be answered by "
            "documentation (troubleshooting steps, safety procedures, specifications)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_manual_section",
        "description": (
            "Retrieve the full text of a specific section from a specific manual, when "
            "you already know which document and section you want (e.g. after "
            "search_technical_documents pointed you at one) rather than searching again."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "The document's UUID"},
                "section": {
                    "type": "string",
                    "description": "Section or subsection name (partial match is fine)",
                },
            },
            "required": ["document_id", "section"],
        },
    },
    {
        "name": "analyze_component_image",
        "description": (
            "Retrieve the visual observations from a technician's photo that was already "
            "uploaded and analyzed. Requires the image_analysis_id the technician provided "
            "with their question — this does not analyze a new image."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_analysis_id": {"type": "string", "description": "The image analysis UUID"},
            },
            "required": ["image_analysis_id"],
        },
    },
    {
        "name": "query_sensor_history",
        "description": (
            "Query historical sensor readings for a piece of equipment over a time range, "
            "for a specific metric (e.g. temperature, vibration_rms, rpm, pressure)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "equipment_id": {"type": "string"},
                "metric": {"type": "string"},
                "start_time": {"type": "string", "description": "ISO 8601 datetime"},
                "end_time": {"type": "string", "description": "ISO 8601 datetime"},
            },
            "required": ["equipment_id", "metric", "start_time", "end_time"],
        },
    },
    {
        "name": "get_maintenance_schedule",
        "description": (
            "Get the maintenance task schedule for a piece of equipment, including when "
            "each task was last performed and whether it's currently overdue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"equipment_id": {"type": "string"}},
            "required": ["equipment_id"],
        },
    },
    {
        "name": "calculate",
        "description": (
            "Evaluate a numeric arithmetic expression (e.g. unit conversions, threshold "
            "comparisons). Supports + - * / % ** and parentheses only — no variables or "
            "function calls."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
    {
        "name": "generate_diagnostic_report",
        "description": (
            "Generate a formatted report for a previously completed diagnosis. Only useful "
            "when the technician references a past diagnosis by ID, not the one in progress."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"diagnosis_id": {"type": "string"}},
            "required": ["diagnosis_id"],
        },
    },
]

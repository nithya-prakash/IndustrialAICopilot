from app.models.diagnosis import Diagnosis


def format_diagnostic_report(diagnosis: Diagnosis) -> str:
    lines = [
        f"# Diagnostic Report — {diagnosis.id}",
        "",
        f"**Equipment:** {diagnosis.equipment_id or 'unspecified'}"
        f" ({diagnosis.equipment_type or 'type unspecified'})",
        f"**Question:** {diagnosis.question}",
        f"**Severity:** {diagnosis.severity.value.upper()}",
        f"**Confidence:** {diagnosis.confidence:.0%}",
        f"**Human approval required:** {'Yes' if diagnosis.requires_human_approval else 'No'}",
        "",
        "## Summary",
        diagnosis.summary or "(no summary)",
        "",
    ]

    if diagnosis.visual_observations:
        lines.append("## Visual Observations")
        for obs in diagnosis.visual_observations:
            desc = obs.get("description", "")
            conf = obs.get("confidence", 0)
            lines.append(f"- {desc} (confidence: {conf:.0%})")
        lines.append("")

    if diagnosis.sensor_findings:
        lines.append("## Sensor Findings")
        for finding in diagnosis.sensor_findings:
            lines.append(f"- {finding.get('finding', finding)}")
        lines.append("")

    if diagnosis.possible_causes:
        lines.append("## Possible Causes (ranked)")
        for cause in diagnosis.possible_causes:
            citations = ", ".join(cause.get("supporting_citations", []))
            suffix = f" — {citations}" if citations else ""
            lines.append(f"{cause.get('rank', '-')}. {cause.get('cause', '')}{suffix}")
        lines.append("")

    if diagnosis.recommended_checks:
        lines.append("## Recommended Checks")
        for check in diagnosis.recommended_checks:
            lines.append(f"- {check}")
        lines.append("")

    lines.append("## Recommended Action")
    lines.append(diagnosis.recommended_action or "(none)")
    lines.append("")

    if diagnosis.evidence:
        lines.append("## Evidence")
        for item in diagnosis.evidence:
            lines.append(f"- [{item.get('type', 'evidence')}] {item.get('citation', '')}")
        lines.append("")

    if diagnosis.limitations:
        lines.append("## Limitations")
        for limitation in diagnosis.limitations:
            lines.append(f"- {limitation}")
        lines.append("")

    return "\n".join(lines)

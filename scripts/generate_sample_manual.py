"""Generates a synthetic PDF manual for local testing and RAG evaluation.

All content here is original/synthetic — written for this project, not
copied from any real manufacturer's documentation. Structured as
Section > Subsection so the structure-aware chunker has real headings to
detect (via font size), matching the example in the project brief:

    Motor Maintenance Manual
    |-- Safety
    |-- Installation
    |-- Troubleshooting
    |   |-- Excessive vibration
    |   |-- Overheating
    |   `-- Unusual noise
    `-- Maintenance
        |-- Bearings
        `-- Lubrication
"""
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "manuals" / "electric_motor_manual.pdf"

SECTIONS: list[tuple[str, list[tuple[str | None, str]]]] = [
    (
        "Safety",
        [
            (
                None,
                "Disconnect and lock out electrical power before performing any inspection or "
                "maintenance on the motor. Verify the circuit is de-energized with a calibrated "
                "meter before touching any terminal. Allow the motor housing to cool before "
                "handling; surface temperatures can exceed 70C during normal operation. Do not "
                "operate the motor with guards or covers removed.",
            ),
        ],
    ),
    (
        "Installation",
        [
            (
                None,
                "Mount the motor on a rigid, level base to minimize vibration transfer. Align the "
                "motor shaft with the driven load within the coupling manufacturer's tolerance "
                "before first startup. Confirm supply voltage and frequency match the motor "
                "nameplate rating. Torque all foot-mounting bolts to the value specified in the "
                "installation drawing.",
            ),
        ],
    ),
    (
        "Troubleshooting",
        [
            (
                "Excessive vibration",
                "Excessive vibration is most commonly caused by shaft misalignment, an unbalanced "
                "coupling, a loose foot mounting, or worn bearings. Check alignment first, since it "
                "accounts for the majority of vibration complaints in the field. If vibration "
                "persists after realignment, inspect the coupling for wear and the bearings for "
                "play. Vibration RMS values above 4.5 mm/s at the bearing housing generally warrant "
                "further investigation.",
            ),
            (
                "Overheating",
                "Overheating is typically caused by sustained overload, blocked ventilation "
                "passages, low supply voltage, or a failing bearing increasing friction. Confirm "
                "the load current does not exceed the nameplate full-load amperage. Clear any dust "
                "or debris from the cooling fins and fan shroud. A winding temperature more than "
                "40C above ambient during normal load is a signal to schedule inspection before "
                "the insulation degrades further.",
            ),
            (
                "Unusual noise",
                "A grinding or rumbling noise usually points to bearing damage or contamination "
                "inside the bearing race. A high-pitched whine can indicate the motor is running "
                "at the wrong voltage or frequency. A rhythmic knocking that varies with shaft "
                "speed is often a bent shaft or a loose rotor component. Isolate the noise source "
                "before disassembly by listening near each bearing housing independently.",
            ),
        ],
    ),
    (
        "Maintenance",
        [
            (
                "Bearings",
                "Inspect bearings for excessive play, noise, or heat at the interval specified in "
                "the maintenance schedule for the duty class. Replace bearings in pairs rather than "
                "individually to avoid re-introducing imbalance shortly after service. Use only the "
                "bearing part number specified for the motor frame size.",
            ),
            (
                "Lubrication",
                "Re-grease sealed bearings only if the motor is designed for re-lubrication; "
                "over-greasing is a common cause of premature bearing failure. Use the grease type "
                "specified on the motor nameplate — mixing incompatible greases can cause the "
                "lubricant to break down. Wipe away any purged grease after re-lubrication.",
            ),
        ],
    ),
]


def build_pdf() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("DocTitle", parent=styles["Title"], fontSize=22, leading=26)
    h1_style = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18, leading=22, spaceBefore=18)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=14, leading=18, spaceBefore=12)
    body_style = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=11, leading=15)

    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=LETTER,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
    )

    story = [Paragraph("Electric Motor Maintenance Manual", title_style), Spacer(1, 0.3 * inch)]
    for section_title, subsections in SECTIONS:
        story.append(Paragraph(section_title, h1_style))
        for subsection_title, text in subsections:
            if subsection_title:
                story.append(Paragraph(subsection_title, h2_style))
            story.append(Paragraph(text, body_style))
            story.append(Spacer(1, 0.15 * inch))

    doc.build(story)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    build_pdf()

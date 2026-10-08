# ruff: noqa: E501  (synthetic manual text is one long string per subsection)
"""Generates three synthetic manuals plus the labelled question set that goes with them.

    python scripts/generate_eval_manuals.py

All text is original and synthetic, written for this project's evaluation (not taken from any real
manufacturer). Each subsection carries one question and the facts a correct answer must contain, so the
manuals and the labels come from one source. Outputs:
  data/manuals/eval/*.pdf                      the three manuals
  data/evaluation/retrieval_questions_v2.json  answerable questions (expected source = manual + section)
"""

import json
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "data" / "manuals" / "eval"

# manual file -> (title, [(section, [(subsection, text, question, [[fact alternatives], ...])])])
MANUALS = {
    "centrifugal_pump_manual.pdf": (
        "Centrifugal Pump Maintenance Manual",
        [
            (
                "Safety",
                [
                    (
                        "Isolation",
                        "Close the suction and discharge isolation valves and lock out the driver before opening the pump casing. Vent and drain the casing and wait until the surface temperature is below 50C before handling.",
                        "What surface temperature must the pump be below before it is handled after isolation?",
                        [["50"]],
                    ),
                    (
                        "Hazardous fluids",
                        "Treat leakage from the casing as the pumped fluid. Wear the protective equipment named on the product safety data sheet and collect leakage in a drip tray, never into a floor drain.",
                        "Where should leakage from the pump casing be collected?",
                        [["drip tray"]],
                    ),
                ],
            ),
            (
                "Installation",
                [
                    (
                        "Foundation and alignment",
                        "Grout the baseplate on a flat foundation. Check coupling alignment with a dial indicator and keep the parallel offset below 0.05 mm before connecting the pipework.",
                        "What parallel offset is the maximum when aligning the pump coupling?",
                        [["0.05"]],
                    ),
                    (
                        "Suction piping",
                        "Keep the suction pipe as short and straight as possible, with at least five pipe diameters of straight run before the pump inlet, and slope it upward toward the pump to avoid air pockets.",
                        "How many pipe diameters of straight run are needed before the pump inlet?",
                        [["five", "5"]],
                    ),
                ],
            ),
            (
                "Troubleshooting",
                [
                    (
                        "Low flow",
                        "Low flow is most often caused by a partially closed discharge valve, a worn impeller, air entering the suction line or a blocked strainer. Check the strainer differential pressure first; a rise above 0.3 bar means the strainer needs cleaning.",
                        "At what strainer differential pressure should the pump strainer be cleaned?",
                        [["0.3"]],
                    ),
                    (
                        "Cavitation noise",
                        "A crackling or gravel-like noise at the inlet indicates cavitation. Confirm the available net positive suction head exceeds the required value by at least 0.5 m, raise the suction tank level, or reduce the flow.",
                        "What net positive suction head margin is needed to avoid cavitation?",
                        [["0.5"]],
                    ),
                    (
                        "Seal leakage",
                        "A mechanical seal may weep a few drops per hour while new. Continuous leakage above 10 drops per minute means the seal faces are worn or the shaft is scored and the seal must be replaced.",
                        "What leakage rate means the pump mechanical seal must be replaced?",
                        [["10"]],
                    ),
                    (
                        "Bearing overheating",
                        "A bearing housing temperature above 80C or a rise of more than 40C over ambient points to over-greasing, misalignment or contaminated lubricant. Check alignment and lubricant condition before restarting.",
                        "What pump bearing housing temperature indicates a problem?",
                        [["80"]],
                    ),
                ],
            ),
            (
                "Maintenance",
                [
                    (
                        "Mechanical seals",
                        "Replace the complete seal cartridge as one unit, never the faces alone. Clean the shaft sleeve and lubricate the elastomers with silicone grease only; mineral oil swells rubber parts.",
                        "What lubricant may be used on mechanical seal elastomers?",
                        [["silicone"]],
                    ),
                    (
                        "Impeller inspection",
                        "Inspect the impeller at every 8,000 operating hours for erosion and cracks. Replace it when the vane tips have lost more than 10 percent of their original thickness.",
                        "At what vane tip wear should the pump impeller be replaced?",
                        [["10 percent", "10%", "10"]],
                    ),
                    (
                        "Lubrication",
                        "Oil-lubricated bearings take ISO VG 46 oil, changed every 4,000 hours or six months, whichever comes first. Fill to the middle of the sight glass only.",
                        "Which oil grade do oil-lubricated pump bearings take?",
                        [["vg 46", "46"]],
                    ),
                    (
                        "Storage",
                        "For storage longer than three months, drain the casing, coat the internal surfaces with rust inhibitor and rotate the shaft by hand one full turn every month.",
                        "How often should the pump shaft be turned by hand during storage?",
                        [["month"]],
                    ),
                    (
                        "Startup checks",
                        "Prime the pump fully, open the suction valve completely and start with the discharge valve slightly open. Stop at once if the discharge pressure does not build within 30 seconds.",
                        "How long should you wait for discharge pressure to build before stopping the pump?",
                        [["30"]],
                    ),
                ],
            ),
        ],
    ),
    "gearbox_conveyor_manual.pdf": (
        "Gearbox and Conveyor Drive Manual",
        [
            (
                "Safety",
                [
                    (
                        "Lockout for conveyors",
                        "Lock out the drive and block the belt or chain against movement before reaching into any pinch point. Stored belt tension can move the conveyor after the motor stops.",
                        "Why must the belt be blocked before reaching into a conveyor pinch point?",
                        [["tension"]],
                    ),
                    (
                        "Guards",
                        "Return every guard to its place before restart. A conveyor must not be run with a guard removed, even for a short test, and the emergency stop cord must be tested at the start of each shift.",
                        "When should the conveyor emergency stop cord be tested?",
                        [["start of each shift", "each shift"]],
                    ),
                ],
            ),
            (
                "Installation",
                [
                    (
                        "Gearbox mounting",
                        "Mount the gearbox on a flat surface with at most 0.1 mm flatness error. Tighten the foot bolts in a cross pattern to the torque given on the nameplate drawing.",
                        "What flatness error is allowed under the gearbox feet?",
                        [["0.1"]],
                    ),
                    (
                        "Belt tracking",
                        "Set belt tracking with the conveyor running empty. Adjust the return roller by no more than 5 mm at a time and wait for two full belt revolutions before judging the result.",
                        "How much should the return roller be adjusted at a time when tracking a belt?",
                        [["5 mm", "5"]],
                    ),
                ],
            ),
            (
                "Troubleshooting",
                [
                    (
                        "Belt slippage",
                        "A belt that slips on the drive pulley is usually too loose, wet or glazed. Check the take-up and increase tension until the belt sags by no more than 1 percent of the span between rollers.",
                        "What belt sag is the limit between rollers?",
                        [["1 percent", "1%"]],
                    ),
                    (
                        "Gearbox overheating",
                        "An oil sump temperature above 90C indicates overfilling, worn gears or blocked cooling fins. Check the oil level at the sight glass first and clean the housing fins.",
                        "What oil sump temperature indicates gearbox overheating?",
                        [["90"]],
                    ),
                    (
                        "Oil leakage",
                        "Leakage at the output shaft seal points to a worn lip seal or a clogged breather that lets pressure build. Clear the breather before replacing the seal.",
                        "What should be cleared before replacing a leaking gearbox output shaft seal?",
                        [["breather"]],
                    ),
                    (
                        "Chain wear",
                        "Measure chain stretch over 20 links. Replace the chain when elongation exceeds 3 percent, and replace the sprockets together with it.",
                        "At what elongation must a conveyor chain be replaced?",
                        [["3 percent", "3%"]],
                    ),
                ],
            ),
            (
                "Maintenance",
                [
                    (
                        "Gear oil change",
                        "Change synthetic gear oil every 10,000 hours or two years. Warm the gearbox first so the oil drains completely, and refill to the level mark.",
                        "How often should synthetic gear oil be changed?",
                        [["10,000", "10000"]],
                    ),
                    (
                        "Roller bearings",
                        "Grease conveyor roller bearings every 500 hours with lithium complex grease, two pumps of the grease gun per bearing.",
                        "How many grease gun pumps go into each conveyor roller bearing?",
                        [["two", "2"]],
                    ),
                    (
                        "Belt splice",
                        "Inspect belt splices monthly. A splice with lifted edges or exposed fabric must be repaired before the next shift.",
                        "How often should conveyor belt splices be inspected?",
                        [["month"]],
                    ),
                    (
                        "Torque arm",
                        "Check the torque arm bolts for tightness after the first 50 hours of operation and again every 1,000 hours.",
                        "When should the gearbox torque arm bolts first be rechecked?",
                        [["50"]],
                    ),
                ],
            ),
        ],
    ),
    "air_compressor_manual.pdf": (
        "Reciprocating Air Compressor Manual",
        [
            (
                "Safety",
                [
                    (
                        "Pressure relief",
                        "Never adjust or plug the safety valve. It is set to open at 10 bar and its set point may only be changed by a certified technician.",
                        "At what pressure is the compressor safety valve set to open?",
                        [["10 bar", "10"]],
                    ),
                    (
                        "Depressurizing",
                        "Release all air pressure from the receiver and open the drain valve before any service. Verify that the gauge reads zero.",
                        "What must the receiver gauge read before compressor service?",
                        [["zero", "0"]],
                    ),
                ],
            ),
            (
                "Installation",
                [
                    (
                        "Location",
                        "Install the compressor in a room with an ambient temperature between 5C and 40C and at least one meter of free space around the air inlet and cooler.",
                        "How much free space is needed around the compressor air inlet?",
                        [["one meter", "1 m", "1 meter"]],
                    ),
                    (
                        "Condensate drain",
                        "Fit an automatic condensate drain to the receiver and route the condensate to an oil-water separator, never to the sewer.",
                        "Where should compressor condensate be routed?",
                        [["separator"]],
                    ),
                ],
            ),
            (
                "Troubleshooting",
                [
                    (
                        "Slow pressure build-up",
                        "If the receiver fills slowly, check for a clogged intake filter, leaking valve plates or a worn piston ring set. Replace the intake filter element when the filter restriction indicator shows red.",
                        "When should the compressor intake filter element be replaced?",
                        [["red"]],
                    ),
                    (
                        "Excess oil carryover",
                        "Oil in the discharge air indicates worn piston rings, an overfilled crankcase or a blocked breather. Check the oil level at the sight glass before opening the cylinder.",
                        "What can cause oil in the compressor discharge air?",
                        [["piston ring"]],
                    ),
                    (
                        "Compressor overheating",
                        "A discharge temperature above 120C points to a dirty cooler, a low oil level or a failing valve. Clean the cooler fins with compressed air from the inside out.",
                        "What discharge temperature indicates compressor overheating?",
                        [["120"]],
                    ),
                    (
                        "Frequent cycling",
                        "Short cycling between load and unload usually means a leak in the air system or an undersized receiver. A leak test should show no pressure drop above 0.2 bar in ten minutes.",
                        "What pressure drop is allowed in the compressor leak test?",
                        [["0.2"]],
                    ),
                ],
            ),
            (
                "Maintenance",
                [
                    (
                        "Oil change",
                        "Change the crankcase oil every 1,000 hours or six months using ISO VG 100 compressor oil.",
                        "Which oil grade is used in the compressor crankcase?",
                        [["vg 100", "100"]],
                    ),
                    (
                        "Valve inspection",
                        "Inspect the valve plates every 3,000 hours. Replace any plate with a visible groove deeper than 0.2 mm.",
                        "What groove depth on a compressor valve plate requires replacement?",
                        [["0.2"]],
                    ),
                    (
                        "Belt tension",
                        "Belt deflection should be 10 mm under a 5 kg load at the middle of the span.",
                        "What compressor belt deflection is correct under load?",
                        [["10 mm", "10"]],
                    ),
                    (
                        "Receiver inspection",
                        "Have the air receiver inspected by a competent person every two years, including a wall thickness check.",
                        "How often must the compressor air receiver be inspected?",
                        [["two years", "2 years", "two"]],
                    ),
                ],
            ),
        ],
    ),
}


def build_pdf(filename: str, title: str, sections) -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("DocTitle", parent=styles["Title"], fontSize=22, leading=26)
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18, leading=22, spaceBefore=18)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=14, leading=18, spaceBefore=12)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=11, leading=15)
    doc = SimpleDocTemplate(
        str(PDF_DIR / filename),
        pagesize=LETTER,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
    )
    story = [Paragraph(title, title_style), Spacer(1, 0.3 * inch)]
    for section, subsections in sections:
        story.append(Paragraph(section, h1))
        for subsection, text, _q, _facts in subsections:
            story += [Paragraph(subsection, h2), Paragraph(text, body), Spacer(1, 0.15 * inch)]
    doc.build(story)


def main() -> None:
    questions = []
    for filename, (title, sections) in MANUALS.items():
        build_pdf(filename, title, sections)
        for section, subsections in sections:
            for subsection, _text, question, facts in subsections:
                questions.append(
                    {
                        "question": question,
                        "expected_sources": [f"{filename}:{section} > {subsection}"],
                        "required_facts": facts,
                    }
                )
    out = ROOT / "data" / "evaluation" / "retrieval_questions_v2.json"
    out.write_text(json.dumps(questions, indent=2))
    print(f"{len(MANUALS)} manuals, {len(questions)} questions -> {out}")


if __name__ == "__main__":
    main()

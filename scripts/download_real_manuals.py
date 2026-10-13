"""Downloads the five real public documents used by data/evaluation/retrieval_questions_real.json.

    python scripts/generate_eval_manuals.py      # first, so the synthetic manuals exist
    python scripts/download_real_manuals.py

The files are US Department of Energy (DOE) tip sheets, published by a US government agency. They
are not stored in git (data/manuals/ is ignored), so this script fetches them and checks each
SHA-256 against the copy the evaluation was run on. A hash mismatch means the publisher changed
the file: re-validate the evidence phrases before trusting the numbers.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / "data" / "manuals" / "eval"

# filename -> (url, sha256)
DOCUMENTS = {
    "test_pumping_system__pumping_systemts4.pdf": (
        "https://www.energy.gov/sites/prod/files/2014/05/f16/test_pumping_system__pumping_systemts4.pdf",
        "089b5db0afa043dc26ffc7f87492c116b4eb64d81d9587fcb9156a928166afc5",
    ),
    "efficient_centrifug_pumps.pdf": (
        "https://www.energy.gov/sites/prod/files/2014/05/f16/efficient_centrifug_pumps.pdf",
        "d875a5478d7ac052a3d0533f734e39dc4c92d7de5d0f4f40fb99c3b00acdf1da",
    ),
    "match_pumps_to_system.pdf": (
        "https://www.energy.gov/sites/prod/files/2014/05/f16/match_pumps_to_system.pdf",
        "205977807a379f597efcda230be4e9c5d383ea11d1445c76467d7a1411381c14",
    ),
    "reduce_pumping_costs.pdf": (
        "https://www.energy.gov/sites/prod/files/2014/05/f16/reduce_pumping_costs.pdf",
        "e77579152b36363516d2284c77c60d1102b2c4b233ee4e3ff60ce6e245d029fd",
    ),
    "extend_motor_operlife_motor_systemts3.pdf": (
        "https://www1.eere.energy.gov/manufacturing/tech_assistance/pdfs/extend_motor_operlife_motor_systemts3.pdf",
        "ce0dfe769c0be9b511bb9f5f6ceeead1e8f6e56c1bdf40e0752756394fdc6ed4",
    ),
}


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name, (url, expected) in DOCUMENTS.items():
        target = DEST / name
        if not target.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (fixed https URLs)
                target.write_bytes(response.read())
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        status = "ok" if actual == expected else "HASH MISMATCH"
        failed += actual != expected
        print(f"{status:>13}  {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

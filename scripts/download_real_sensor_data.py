"""Downloads the UCI "Condition Monitoring of Hydraulic Systems" dataset and converts it into the
wide-format CSV that `scripts/seed_sensor_data.py` loads.

    python scripts/download_real_sensor_data.py

Source: Helwig, Pignanelli and Schütze (ZeMA gGmbH / Saarland University), UCI Machine Learning
Repository, licence CC BY 4.0, https://doi.org/10.24432/C5CW21. Recorded on a hydraulic test rig
that
repeats 60-second load cycles (2,205 cycles) while four components (cooler, valve, pump,
accumulator)
are set to known degraded conditions.

What the conversion does, so nothing here is presented as more than it is:
- Each cycle becomes one row: the mean of that cycle's samples for each sensor.
- The dataset has no wall-clock time. Timestamps are an assumed anchor plus 60 s per cycle (the real
  cycle length), so intervals are real and the dates are not.
- Component conditions are written separately to hydraulic_001_labels.csv and are never loaded as
sensor
  readings, so the analysis tools only see what a plant sensor would see.

The zip (about 77 MB) is checked against a SHA-256 taken on 2026-10-16. A mismatch means UCI
changed the
file; re-check the conversion before trusting any numbers derived from it. Outputs are ignored by
git.
"""

import csv
import hashlib
import io
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

URL = "https://archive.ics.uci.edu/static/public/447/condition+monitoring+of+hydraulic+systems.zip"
SHA256 = "24128aad2ee45eea7e6b63ebbd9992cdf25d0483a2cebefbfc13bc69079af1f2"

DEST = Path(__file__).resolve().parent.parent / "data" / "sensors"
CACHE = DEST / ".cache" / "hydraulic.zip"

START = datetime(2026, 8, 9, tzinfo=UTC)  # assumed anchor, see module docstring
CYCLE_SECONDS = 60

# metric name used in the app -> source file inside the zip
SENSORS = {
    "pressure": "PS1.txt",  # bar, pump outlet
    "temperature": "TS1.txt",  # degrees C
    "flow_rate": "FS1.txt",  # l/min
    "vibration": "VS1.txt",  # mm/s, cycle mean (not an RMS)
    "motor_power": "EPS1.txt",  # W
    "cooling_efficiency": "CE.txt",  # %, virtual sensor
    "efficiency_factor": "SE.txt",  # %, virtual sensor
}

LABEL_COLUMNS = ["cooler_condition", "valve_condition", "pump_leakage", "accumulator_pressure",
"stable_flag"]


def _fetch() -> bytes:
    if CACHE.exists():
        return CACHE.read_bytes()
    request = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 (fixed https URL)
        data = response.read()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(data)
    return data


def main() -> int:
    data = _fetch()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        print(f"HASH MISMATCH: expected {SHA256}, got {digest}", file=sys.stderr)
        return 1

    archive = zipfile.ZipFile(io.BytesIO(data))
    columns: dict[str, np.ndarray] = {}
    for metric, member in SENSORS.items():
        matrix = np.loadtxt(io.BytesIO(archive.read(member)), delimiter="\t")
        columns[metric] = matrix.mean(axis=1)
    cycles = len(next(iter(columns.values())))

    labels = np.loadtxt(io.BytesIO(archive.read("profile.txt")), delimiter="\t")
    if labels.shape != (cycles, len(LABEL_COLUMNS)):
        print(f"unexpected profile.txt shape {labels.shape}", file=sys.stderr)
        return 1

    DEST.mkdir(parents=True, exist_ok=True)
    with (DEST / "hydraulic_001.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", *SENSORS])
        for i in range(cycles):
            stamp = (START + timedelta(seconds=CYCLE_SECONDS * i)).isoformat()
            writer.writerow([stamp, *(f"{columns[m][i]:.4f}" for m in SENSORS)])

    with (DEST / "hydraulic_001_labels.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["cycle", "timestamp", *LABEL_COLUMNS])
        for i in range(cycles):
            stamp = (START + timedelta(seconds=CYCLE_SECONDS * i)).isoformat()
            writer.writerow([i, stamp, *(int(v) for v in labels[i])])

    print(f"wrote {cycles} cycles x {len(SENSORS)} sensors to {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

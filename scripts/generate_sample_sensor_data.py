"""Generates synthetic sensor time-series CSVs for local testing and demo
purposes — entirely fabricated data, not real recorded readings, generated
with a fixed random seed for reproducibility.

motor_001 tells a deliberate story that ties back to the synthetic
electric_motor_manual.pdf (scripts/generate_sample_manual.py): temperature
drifts upward over the last two days (developing overheating), and
vibration gets a handful of isolated spikes that cross the manual's stated
4.5 mm/s guidance — both are exactly the kind of pattern Phase 5's trend/
anomaly detection should catch, and exactly what the manual's
"Troubleshooting > Overheating" / "Excessive vibration" sections describe.
pump_001 and conveyor_001 are steady-state (no injected anomaly) so the
evaluation set has clean negative examples too, not just one flagged case.
"""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "sensors"
HOURS = 24 * 14  # 14 days of hourly readings
START = datetime(2026, 8, 9, tzinfo=UTC)


def _timestamps() -> list[datetime]:
    return [START + timedelta(hours=i) for i in range(HOURS)]


def _write_csv(filename: str, columns: dict[str, np.ndarray]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    timestamps = _timestamps()
    metric_names = list(columns.keys())

    lines = ["timestamp," + ",".join(metric_names)]
    for i, ts in enumerate(timestamps):
        values = ",".join(f"{columns[name][i]:.2f}" for name in metric_names)
        lines.append(f"{ts.isoformat()},{values}")

    path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {path} ({HOURS} rows)")


def generate_motor_001() -> None:
    rng = np.random.default_rng(seed=42)
    hours = np.arange(HOURS)

    temperature = 58.0 + rng.normal(0, 1.2, HOURS)
    drift_start = HOURS - 48
    drift = np.clip(hours - drift_start, 0, None) * 0.35
    temperature += drift

    vibration = 2.0 + rng.normal(0, 0.3, HOURS)
    spike_hours = rng.choice(HOURS, size=5, replace=False)
    for h in spike_hours:
        vibration[h] += rng.uniform(2.8, 4.5)

    rpm = 1480.0 + rng.normal(0, 8, HOURS)
    pressure = 2.1 + rng.normal(0, 0.08, HOURS)

    _write_csv(
        "motor_001.csv",
        {
            "temperature": temperature,
            "vibration_rms": vibration,
            "rpm": rpm,
            "pressure": pressure,
        },
    )


def generate_pump_001() -> None:
    rng = np.random.default_rng(seed=7)
    pressure = 4.5 + rng.normal(0, 0.15, HOURS)
    flow_rate = 120.0 + rng.normal(0, 3.0, HOURS)
    vibration = 1.6 + rng.normal(0, 0.2, HOURS)

    _write_csv(
        "pump_001.csv",
        {"pressure": pressure, "flow_rate": flow_rate, "vibration_rms": vibration},
    )


def generate_conveyor_001() -> None:
    rng = np.random.default_rng(seed=13)
    belt_speed = 1.2 + rng.normal(0, 0.03, HOURS)
    motor_current = 12.5 + rng.normal(0, 0.4, HOURS)
    vibration = 1.1 + rng.normal(0, 0.15, HOURS)

    _write_csv(
        "conveyor_001.csv",
        {"belt_speed": belt_speed, "motor_current": motor_current, "vibration_rms": vibration},
    )


if __name__ == "__main__":
    generate_motor_001()
    generate_pump_001()
    generate_conveyor_001()

"""Does the z-score-vs-baseline check the sensor tools use actually separate degraded components
from
healthy ones on real recorded data?

    docker compose run --rm backend python -m evaluation.sensor_fault_eval

Data: the UCI hydraulic test rig, one row per 60 s load cycle
(`scripts/download_real_sensor_data.py`
writes data/sensors/hydraulic_001.csv and hydraulic_001_labels.csv). For each of the four components
the labels say whether it was at its optimal setting in that cycle.

Method, per component and per metric:
- Cycles where the component is optimal are split at random (seed 7) into a baseline half and a
test half.
- Mean and standard deviation come from the baseline half only (the same arithmetic as
  `app.analytics.sensors.compare_to_baseline`).
- Score = |z| of the cycle's mean metric value. AUROC separates the test-half healthy cycles from
every
  cycle where the component is degraded; 95% CI from 500 bootstrap resamples of the test cycles.

Limits: the other three components vary independently of the one being tested, so their effect is
noise
here (a deliberately hard setting). Per-metric scores use one metric at a time; the Mahalanobis
column uses all
metrics together (covariance from the same baseline half). Cycles
carry a `stable_flag`; they are kept, not filtered.
"""

import csv
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

DATA = Path(__file__).resolve().parent.parent / "data" / "sensors"
SEED = 7
BOOTSTRAPS = 500

COMPONENTS = {
    "cooler_condition": 100,
    "valve_condition": 100,
    "pump_leakage": 0,
    "accumulator_pressure": 130,
}


def _load() -> tuple[list[str], np.ndarray, dict[str, np.ndarray]]:
    with (DATA / "hydraulic_001.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    metrics = [c for c in rows[0] if c != "timestamp"]
    values = np.array([[float(r[m]) for m in metrics] for r in rows])
    with (DATA / "hydraulic_001_labels.csv").open() as handle:
        label_rows = list(csv.DictReader(handle))
    labels = {c: np.array([int(r[c]) for r in label_rows]) for c in COMPONENTS}
    return metrics, values, labels


def _bootstrap_ci(
    y: np.ndarray, score: np.ndarray, rng: np.random.Generator
) -> tuple[float, float]:
    aucs = []
    for _ in range(BOOTSTRAPS):
        idx = rng.integers(0, len(y), len(y))
        if len(set(y[idx])) < 2:
            continue
        aucs.append(roc_auc_score(y[idx], score[idx]))
    return float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))


def main() -> int:
    if not (DATA / "hydraulic_001.csv").exists():
        print("run scripts/download_real_sensor_data.py first", file=sys.stderr)
        return 1
    compact = "--compact" in sys.argv
    metrics, values, labels = _load()
    rng = np.random.default_rng(SEED)

    if compact:
        print(f"{'component':<22}{'best single sensor':<28}{'all 7 sensors':<18}test cycles")
    else:
        print(
            "| Component | Best single metric | AUROC [95% CI] | Mahalanobis, all metrics "
            "| Test cycles (degraded / healthy) | Each metric |"
        )
        print("|---|---|---|---|---|---|")
    for component, optimal in COMPONENTS.items():
        healthy = np.flatnonzero(labels[component] == optimal)
        degraded = np.flatnonzero(labels[component] != optimal)
        shuffled = rng.permutation(healthy)
        baseline, healthy_test = shuffled[: len(shuffled) // 2], shuffled[len(shuffled) // 2 :]
        test = np.concatenate([healthy_test, degraded])
        y = np.concatenate([np.zeros(len(healthy_test)), np.ones(len(degraded))])

        mean = values[baseline].mean(axis=0)
        std = values[baseline].std(axis=0)
        results = {}
        for j, metric in enumerate(metrics):
            score = np.abs((values[test, j] - mean[j]) / std[j])
            results[metric] = (roc_auc_score(y, score), score)
        best = max(results, key=lambda m: results[m][0])
        auc, score = results[best]
        low, high = _bootstrap_ci(y, score, rng)
        cov_inv = np.linalg.pinv(np.cov(values[baseline], rowvar=False))
        delta = values[test] - mean
        maha = np.sqrt(np.einsum("ij,jk,ik->i", delta, cov_inv, delta))
        maha_auc = roc_auc_score(y, maha)
        maha_low, maha_high = _bootstrap_ci(y, maha, rng)
        everything = ", ".join(f"{m} {results[m][0]:.2f}" for m in metrics)
        if compact:
            single = f"{best} {auc:.2f}"
            print(
                f"{component:<22}{single:<28}{maha_auc:<18.2f}"
                f"{len(degraded)} / {len(healthy_test)}"
            )
            continue
        print(
            f"| {component} | {best} | {auc:.3f} [{low:.3f}, {high:.3f}] "
            f"| {maha_auc:.3f} [{maha_low:.3f}, {maha_high:.3f}] "
            f"| {len(degraded)} / {len(healthy_test)} | {everything} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

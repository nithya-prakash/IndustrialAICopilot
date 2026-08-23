"""Sensor time-series analytics: trend detection, anomaly detection
(statistical and ML-based), moving averages, and baseline comparison.

Statistical (z-score) anomaly detection is the default, not the Isolation
Forest option, even though the brief explicitly suggests "ML-based anomaly
detection where appropriate": a technician needs to know *why* a reading
was flagged, and "3.2 standard deviations from this equipment's own recent
mean" is a defensible, explainable answer in a way "the model scored it
-0.61" is not. Isolation Forest is offered as an opt-in for exactly the
cases where the anomaly pattern isn't a simple single-variable outlier —
see docs/architecture-decisions.md.
"""
import statistics
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sklearn.ensemble import IsolationForest


@dataclass
class SensorPoint:
    recorded_at: datetime
    value: float


@dataclass
class TrendResult:
    direction: str  # "increasing" | "decreasing" | "stable"
    slope_per_hour: float
    r_squared: float


@dataclass
class AnomalyPoint:
    recorded_at: datetime
    value: float
    score: float
    method: str


@dataclass
class StatisticalSummary:
    count: int
    mean: float
    median: float
    std_dev: float
    min_value: float
    max_value: float


def statistical_summary(points: list[SensorPoint]) -> StatisticalSummary | None:
    if not points:
        return None
    values = [p.value for p in points]
    return StatisticalSummary(
        count=len(values),
        mean=statistics.fmean(values),
        median=statistics.median(values),
        std_dev=statistics.pstdev(values) if len(values) > 1 else 0.0,
        min_value=min(values),
        max_value=max(values),
    )


def moving_average(points: list[SensorPoint], window: int) -> list[SensorPoint]:
    if window < 1 or len(points) < window:
        return []
    ordered = sorted(points, key=lambda p: p.recorded_at)
    values = [p.value for p in ordered]
    result = []
    for i in range(window - 1, len(values)):
        window_slice = values[i - window + 1 : i + 1]
        avg = statistics.fmean(window_slice)
        result.append(SensorPoint(recorded_at=ordered[i].recorded_at, value=avg))
    return result


def detect_trend(points: list[SensorPoint], min_r_squared: float = 0.1) -> TrendResult | None:
    """Linear regression of value against elapsed time. R^2 below
    min_r_squared means the fit doesn't reliably explain the data, so the
    series is reported as "stable" rather than asserting a direction the
    data doesn't actually support."""
    if len(points) < 3:
        return None

    ordered = sorted(points, key=lambda p: p.recorded_at)
    t0 = ordered[0].recorded_at
    hours = np.array([(p.recorded_at - t0).total_seconds() / 3600 for p in ordered])
    values = np.array([p.value for p in ordered])

    if np.allclose(hours, hours[0]):
        return None

    slope, intercept = np.polyfit(hours, values, 1)
    predicted = slope * hours + intercept
    ss_res = float(np.sum((values - predicted) ** 2))
    ss_tot = float(np.sum((values - values.mean()) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    if r_squared < min_r_squared:
        direction = "stable"
    else:
        direction = "increasing" if slope > 0 else "decreasing"

    return TrendResult(
        direction=direction, slope_per_hour=float(slope), r_squared=round(r_squared, 3)
    )


def detect_anomalies_statistical(
    points: list[SensorPoint], z_threshold: float = 3.0
) -> list[AnomalyPoint]:
    if len(points) < 3:
        return []
    values = [p.value for p in points]
    mean = statistics.fmean(values)
    std_dev = statistics.pstdev(values)
    if std_dev == 0:
        return []

    anomalies = []
    for p in points:
        z = (p.value - mean) / std_dev
        if abs(z) >= z_threshold:
            anomalies.append(
                AnomalyPoint(
                    recorded_at=p.recorded_at, value=p.value, score=round(z, 2), method="z_score"
                )
            )
    return anomalies


def detect_anomalies_isolation_forest(
    points: list[SensorPoint], contamination: float = 0.05, random_state: int = 42
) -> list[AnomalyPoint]:
    if len(points) < 10:
        return []

    values = np.array([[p.value] for p in points])
    model = IsolationForest(contamination=contamination, random_state=random_state)
    predictions = model.fit_predict(values)
    scores = model.score_samples(values)

    return [
        AnomalyPoint(
            recorded_at=p.recorded_at,
            value=p.value,
            score=round(float(score), 3),
            method="isolation_forest",
        )
        for p, pred, score in zip(points, predictions, scores, strict=True)
        if pred == -1
    ]


def compare_to_baseline(current_value: float, baseline_points: list[SensorPoint]) -> dict:
    summary = statistical_summary(baseline_points)
    if summary is None or summary.std_dev == 0:
        return {"baseline_available": False}

    deviation = current_value - summary.mean
    z_score = deviation / summary.std_dev
    return {
        "baseline_available": True,
        "baseline_mean": round(summary.mean, 3),
        "baseline_std_dev": round(summary.std_dev, 3),
        "deviation_from_baseline": round(deviation, 3),
        "z_score": round(z_score, 2),
        "outside_normal_range": abs(z_score) >= 3.0,
    }


def check_thresholds(
    points: list[SensorPoint], min_value: float | None, max_value: float | None
) -> list[SensorPoint]:
    violations = []
    for p in points:
        if min_value is not None and p.value < min_value:
            violations.append(p)
        elif max_value is not None and p.value > max_value:
            violations.append(p)
    return violations

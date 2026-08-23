from datetime import UTC, datetime, timedelta

from app.analytics.sensors import (
    SensorPoint,
    check_thresholds,
    compare_to_baseline,
    detect_anomalies_isolation_forest,
    detect_anomalies_statistical,
    detect_trend,
    moving_average,
    statistical_summary,
)

START = datetime(2026, 8, 1, tzinfo=UTC)


def _points(values: list[float], hours_apart: int = 1) -> list[SensorPoint]:
    return [
        SensorPoint(recorded_at=START + timedelta(hours=i * hours_apart), value=v)
        for i, v in enumerate(values)
    ]


def test_statistical_summary_basic() -> None:
    summary = statistical_summary(_points([10, 20, 30]))
    assert summary is not None
    assert summary.count == 3
    assert summary.mean == 20
    assert summary.median == 20
    assert summary.min_value == 10
    assert summary.max_value == 30


def test_statistical_summary_empty_returns_none() -> None:
    assert statistical_summary([]) is None


def test_moving_average_window_size() -> None:
    points = _points([1, 2, 3, 4, 5])
    result = moving_average(points, window=3)
    assert len(result) == 3
    assert result[0].value == 2  # mean(1,2,3)
    assert result[1].value == 3  # mean(2,3,4)
    assert result[2].value == 4  # mean(3,4,5)


def test_moving_average_insufficient_points_returns_empty() -> None:
    assert moving_average(_points([1, 2]), window=5) == []


def test_detect_trend_increasing_series() -> None:
    values = [50 + i * 2 for i in range(20)]
    trend = detect_trend(_points(values))
    assert trend is not None
    assert trend.direction == "increasing"
    assert trend.slope_per_hour > 0
    assert trend.r_squared > 0.9


def test_detect_trend_decreasing_series() -> None:
    values = [100 - i * 3 for i in range(20)]
    trend = detect_trend(_points(values))
    assert trend is not None
    assert trend.direction == "decreasing"
    assert trend.slope_per_hour < 0


def test_detect_trend_noisy_flat_series_is_stable() -> None:
    import random

    rng = random.Random(1)
    values = [50 + rng.uniform(-0.5, 0.5) for _ in range(20)]
    trend = detect_trend(_points(values))
    assert trend is not None
    assert trend.direction == "stable"


def test_detect_trend_too_few_points_returns_none() -> None:
    assert detect_trend(_points([1, 2])) is None


def test_detect_anomalies_statistical_finds_obvious_outlier() -> None:
    values = [50.0] * 20 + [500.0]  # last point is a massive spike
    anomalies = detect_anomalies_statistical(_points(values), z_threshold=3.0)
    assert len(anomalies) == 1
    assert anomalies[0].value == 500.0
    assert anomalies[0].method == "z_score"


def test_detect_anomalies_statistical_no_outliers_in_uniform_data() -> None:
    anomalies = detect_anomalies_statistical(_points([50.0] * 20))
    assert anomalies == []


def test_detect_anomalies_statistical_zero_std_dev_returns_empty() -> None:
    assert detect_anomalies_statistical(_points([10.0, 10.0, 10.0])) == []


def test_detect_anomalies_isolation_forest_finds_outlier() -> None:
    import random

    rng = random.Random(2)
    values = [50 + rng.uniform(-1, 1) for _ in range(30)]
    values[15] = 500.0
    anomalies = detect_anomalies_isolation_forest(_points(values), contamination=0.05)
    flagged_values = [a.value for a in anomalies]
    assert 500.0 in flagged_values


def test_detect_anomalies_isolation_forest_too_few_points_returns_empty() -> None:
    assert detect_anomalies_isolation_forest(_points([1, 2, 3])) == []


def test_check_thresholds_flags_values_above_max() -> None:
    violations = check_thresholds(_points([3.0, 5.0, 4.0, 6.0]), min_value=None, max_value=4.5)
    assert [p.value for p in violations] == [5.0, 6.0]


def test_check_thresholds_flags_values_below_min() -> None:
    violations = check_thresholds(_points([10.0, 2.0, 8.0]), min_value=5.0, max_value=None)
    assert [p.value for p in violations] == [2.0]


def test_check_thresholds_no_limits_returns_empty() -> None:
    assert check_thresholds(_points([1.0, 2.0]), min_value=None, max_value=None) == []


def test_compare_to_baseline_within_normal_range() -> None:
    baseline = _points([50.0 + (i % 3) for i in range(10)])
    result = compare_to_baseline(51.0, baseline)
    assert result["baseline_available"] is True
    assert result["outside_normal_range"] is False


def test_compare_to_baseline_flags_large_deviation() -> None:
    baseline = _points([50.0, 50.5, 49.5, 50.2, 49.8])
    result = compare_to_baseline(200.0, baseline)
    assert result["baseline_available"] is True
    assert result["outside_normal_range"] is True
    assert result["z_score"] > 3.0


def test_compare_to_baseline_no_baseline_data() -> None:
    result = compare_to_baseline(50.0, [])
    assert result == {"baseline_available": False}


def test_compare_to_baseline_zero_variance_baseline() -> None:
    result = compare_to_baseline(60.0, _points([50.0, 50.0, 50.0]))
    assert result == {"baseline_available": False}

from datetime import datetime, timezone

from app.analytics.anomalies import detect_all
from app.analytics.scoring import build_scorecard
from app.analytics.statistics import distribution, percentile, relative_change, stability_score
from app.analytics.trend import compare, trend
from app.analytics.types import MetricSample


def sample(task_id, iops, latency=100, timestamp=None):
    return MetricSample(task_id=task_id, timestamp=timestamp or datetime.now(timezone.utc), device_name="nvme1n1", test_name="rand_read_4k", values={"iops": iops, "bw_mib_s": iops / 100, "latency_avg_us": latency, "latency_p99_us": latency * 3, "cpu_user_pct": 10, "cpu_system_pct": 5})


def test_distribution_and_percentile_are_interpolated():
    summary = distribution([1, 2, 3, 4, 5])
    assert summary.count == 5
    assert summary.median == 3
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert relative_change(100, 110) == 10


def test_stability_and_scorecard_are_explainable():
    score = stability_score([100, 101, 99, 100])
    card = build_scorecard(sample(1, 200_000).values, "rand_read_4k", score)
    assert score > 95
    assert card.total > 0
    assert len(card.dimensions) == 4


def test_anomaly_detection_finds_zero_throughput():
    current = sample(3, 0)
    anomalies = detect_all(current, [sample(1, 100_000), sample(2, 101_000)])
    assert any(item.severity == "critical" for item in anomalies)


def test_trend_and_comparison_detect_direction():
    points = [sample(1, 100), sample(2, 120), sample(3, 140)]
    summary = trend(points, "iops")
    assert summary.direction == "improving"
    report = compare(points[0], points[-1])
    assert report.verdict == "性能改善"


def test_quality_rejects_missing_required_metric():
    from app.analytics.quality import evaluate
    gate = evaluate({"iops": 100.0, "bw_mib_s": None, "latency_avg_us": 10.0, "latency_p99_us": 20.0})
    assert not gate.usable
    assert gate.grade == "D"


def test_quality_accepts_consistent_complete_metric_set():
    from app.analytics.quality import evaluate
    gate = evaluate({"iops": 100.0, "bw_mib_s": 20.0, "latency_avg_us": 10.0, "latency_p99_us": 20.0})
    assert gate.usable
    assert gate.grade == "A"


def test_linear_forecast_reports_downward_slope():
    from app.analytics.forecasting import predict
    result = predict("iops", [100.0, 90.0, 80.0, 70.0])
    assert result.slope_per_run < 0
    assert result.next_value < 70


def test_moving_average_is_available_without_external_dependencies():
    from app.analytics.forecasting import moving_average
    assert moving_average([1, 3, 5], 2) == [1.0, 2.0, 4.0]


def test_recommendations_offer_baseline_when_no_issues():
    from app.analytics.quality import evaluate
    from app.analytics.recommendations import generate
    from app.analytics.scoring import build_scorecard
    metrics = {"iops": 100.0, "bw_mib_s": 10.0, "latency_avg_us": 10.0, "latency_p99_us": 20.0}
    items = generate(build_scorecard(metrics, "rand_read_4k", 100), evaluate(metrics), ())
    assert items

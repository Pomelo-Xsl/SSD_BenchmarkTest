"""同设备同负载历史趋势和双任务对比。"""
from __future__ import annotations
from collections import defaultdict
from app.analytics.statistics import linear_slope, relative_change
from app.analytics.types import ComparisonMetric, ComparisonReport, MetricSample, TrendPoint, TrendSummary, numeric_metrics


def comparable(samples: list[MetricSample], device_name: str, test_name: str) -> list[MetricSample]:
    return sorted((item for item in samples if item.device_name == device_name and item.test_name == test_name), key=lambda item: (item.timestamp is None, item.timestamp, item.task_id))


def trend(samples: list[MetricSample], metric: str) -> TrendSummary:
    values = [sample.value(metric) for sample in samples]
    usable = [value for value in values if value is not None]
    slope = linear_slope(values)
    baseline, latest = (usable[0], usable[-1]) if usable else (None, None)
    change = relative_change(baseline, latest)
    if change is None or abs(change) < 3:
        direction = "stable"
    elif metric.startswith("latency"):
        direction = "degrading" if change > 0 else "improving"
    else:
        direction = "improving" if change > 0 else "degrading"
    confidence = "high" if len(usable) >= 8 else "medium" if len(usable) >= 4 else "low"
    return TrendSummary(metric=metric, direction=direction, slope_per_run=slope, total_change_percent=change, baseline=baseline, latest=latest, confidence=confidence, points=tuple(TrendPoint(task_id=item.task_id, timestamp=item.timestamp, value=item.value(metric)) for item in samples))


def trends(samples: list[MetricSample]) -> tuple[TrendSummary, ...]:
    return tuple(trend(samples, metric) for metric in numeric_metrics())


def compare(baseline: MetricSample, candidate: MetricSample) -> ComparisonReport:
    notes: list[str] = []
    if baseline.device_name != candidate.device_name:
        notes.append("任务来自不同设备，结果仅供参考。")
    if baseline.test_name != candidate.test_name:
        notes.append("任务负载类型不同，不能作为严格性能基线。")
    metrics: list[ComparisonMetric] = []
    for metric in numeric_metrics():
        before, after = baseline.value(metric), candidate.value(metric)
        delta = after - before if before is not None and after is not None else None
        delta_percent = relative_change(before, after)
        if delta_percent is None:
            interpretation = "缺少可比数据"
        elif metric.startswith("latency"):
            interpretation = "改善" if delta_percent < -3 else "回归" if delta_percent > 3 else "持平"
        else:
            interpretation = "改善" if delta_percent > 3 else "回归" if delta_percent < -3 else "持平"
        metrics.append(ComparisonMetric(metric, before, after, delta, delta_percent, interpretation))
    regressions = sum(metric.interpretation == "回归" for metric in metrics)
    improvements = sum(metric.interpretation == "改善" for metric in metrics)
    verdict = "性能改善" if improvements > regressions else "存在性能回归" if regressions > improvements else "性能整体持平"
    return ComparisonReport(baseline.task_id, candidate.task_id, not notes, tuple(notes), tuple(metrics), verdict)


def group_by_device_and_test(samples: list[MetricSample]) -> dict[tuple[str, str], list[MetricSample]]:
    groups: dict[tuple[str, str], list[MetricSample]] = defaultdict(list)
    for sample in samples:
        groups[(sample.device_name, sample.test_name)].append(sample)
    return dict(groups)

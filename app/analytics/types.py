"""分析领域对象：所有对象均可安全序列化为 API/报告数据。"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable


@dataclass(frozen=True)
class MetricSample:
    task_id: int
    timestamp: datetime | None
    device_name: str
    test_name: str
    values: dict[str, float | None]

    def value(self, name: str) -> float | None:
        value = self.values.get(name)
        return float(value) if value is not None else None


@dataclass(frozen=True)
class Distribution:
    count: int
    minimum: float | None
    maximum: float | None
    mean: float | None
    median: float | None
    percentile_5: float | None
    percentile_25: float | None
    percentile_75: float | None
    percentile_95: float | None
    percentile_99: float | None
    standard_deviation: float | None
    coefficient_variation: float | None
    mad: float | None

    @property
    def spread(self) -> float | None:
        if self.minimum is None or self.maximum is None:
            return None
        return self.maximum - self.minimum


@dataclass(frozen=True)
class StabilityAssessment:
    metric: str
    score: float
    level: str
    coefficient_variation: float | None
    drift_percent: float | None
    reason: str


@dataclass(frozen=True)
class ScoreDimension:
    key: str
    title: str
    score: float
    weight: float
    weighted_score: float
    level: str
    explanation: str


@dataclass(frozen=True)
class ScoreCard:
    total: float
    grade: str
    summary: str
    dimensions: tuple[ScoreDimension, ...]


@dataclass(frozen=True)
class Anomaly:
    metric: str
    severity: str
    title: str
    detail: str
    observed: float | None = None
    expected: float | None = None
    task_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class TrendPoint:
    task_id: int
    timestamp: datetime | None
    value: float | None


@dataclass(frozen=True)
class TrendSummary:
    metric: str
    direction: str
    slope_per_run: float | None
    total_change_percent: float | None
    baseline: float | None
    latest: float | None
    confidence: str
    points: tuple[TrendPoint, ...]


@dataclass(frozen=True)
class ComparisonMetric:
    metric: str
    baseline: float | None
    candidate: float | None
    delta: float | None
    delta_percent: float | None
    interpretation: str


@dataclass(frozen=True)
class ComparisonReport:
    baseline_task_id: int
    candidate_task_id: int
    compatible: bool
    compatibility_notes: tuple[str, ...]
    metrics: tuple[ComparisonMetric, ...]
    verdict: str


@dataclass(frozen=True)
class AnalysisReport:
    task_id: int
    generated_at: datetime
    metrics: dict[str, float | None]
    scorecard: ScoreCard
    stability: tuple[StabilityAssessment, ...]
    anomalies: tuple[Anomaly, ...]
    comparable_history_count: int
    trends: tuple[TrendSummary, ...] = ()
    quality: Any | None = None
    forecasts: tuple[Any, ...] = ()
    recommendations: tuple[Any, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def serialise(value: Any) -> Any:
    """递归将 dataclass、datetime 和 tuple 转换为 JSON 兼容数据。"""
    if hasattr(value, "__dataclass_fields__"):
        return serialise(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): serialise(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [serialise(item) for item in value]
    return value


def numeric_metrics() -> tuple[str, ...]:
    return ("iops", "bw_mib_s", "latency_avg_us", "latency_p99_us", "cpu_user_pct", "cpu_system_pct")


def friendly_metric(metric: str) -> str:
    names = {
        "iops": "IOPS", "bw_mib_s": "带宽 (MiB/s)", "latency_avg_us": "平均延迟 (μs)",
        "latency_p99_us": "P99 延迟 (μs)", "cpu_user_pct": "用户 CPU (%)", "cpu_system_pct": "系统 CPU (%)",
    }
    return names.get(metric, metric)


def finite(values: Iterable[float | None]) -> list[float]:
    return [float(value) for value in values if value is not None]

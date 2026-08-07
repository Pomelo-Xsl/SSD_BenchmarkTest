"""将数据库结果映射为分析、趋势、异常与评分报告。"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Iterable
import json
from app.analytics.types import serialise
from app.services.task_service import TaskService
from app.analytics.anomalies import detect_all
from app.analytics.scoring import build_scorecard
from app.analytics.statistics import classify_stability, stability_score
from app.analytics.quality import evaluate
from app.analytics.forecasting import forecast_many
from app.analytics.recommendations import generate
from app.analytics.trend import comparable, compare, trends
from app.analytics.types import AnalysisReport, MetricSample, StabilityAssessment
from app.models import Result, Task


class BenchmarkAnalysisService:
    @staticmethod
    def sample(task: Task, result: Result) -> MetricSample:
        return MetricSample(task_id=task.id, timestamp=task.completed_at or task.created_at, device_name=task.device_name, test_name=task.test_name, values={"iops": result.iops, "bw_mib_s": result.bw_mib_s, "latency_avg_us": result.latency_avg_us, "latency_p99_us": result.latency_p99_us, "cpu_user_pct": result.cpu_user_pct, "cpu_system_pct": result.cpu_system_pct})

    @staticmethod
    def report(task: Task, result: Result, history: Iterable[tuple[Task, Result]]) -> AnalysisReport:
        current = BenchmarkAnalysisService.sample(task, result)
        all_history = [BenchmarkAnalysisService.sample(old_task, old_result) for old_task, old_result in history if old_task.id != task.id]
        peers = comparable(all_history, task.device_name, task.test_name)
        stability = []
        for metric in ("iops", "bw_mib_s", "latency_avg_us", "latency_p99_us"):
            values = [item.value(metric) for item in peers] + [current.value(metric)]
            score = stability_score(values)
            level, reason = classify_stability(values)
            stability.append(StabilityAssessment(metric=metric, score=round(score, 2), level=level, coefficient_variation=None, drift_percent=None, reason=reason))
        average_stability = sum(item.score for item in stability) / len(stability) if stability else 100
        scorecard = build_scorecard(current.values, task.test_name, average_stability)
        anomalies = detect_all(current, peers)
        trend_rows = trends(peers + [current])
        quality = evaluate(current.values, {"runtime_seconds": (json.loads(task.fio_options or "{}").get("runtime_seconds")), "elapsed_seconds": TaskService.elapsed_seconds(task)})
        metric_series = {metric: [sample.value(metric) for sample in peers + [current]] for metric in ("iops", "bw_mib_s", "latency_avg_us", "latency_p99_us")}
        forecasts = forecast_many(metric_series)
        recommendations = generate(scorecard, quality, anomalies, [serialise(item) for item in trend_rows])
        return AnalysisReport(task_id=task.id, generated_at=datetime.now(timezone.utc), metrics=current.values, scorecard=scorecard, stability=tuple(stability), anomalies=anomalies, comparable_history_count=len(peers), trends=trend_rows, quality=quality, forecasts=forecasts, recommendations=recommendations, metadata={"device_name": task.device_name, "test_name": task.test_name})

    @staticmethod
    def comparison(baseline_task: Task, baseline_result: Result, candidate_task: Task, candidate_result: Result):
        return compare(BenchmarkAnalysisService.sample(baseline_task, baseline_result), BenchmarkAnalysisService.sample(candidate_task, candidate_result))

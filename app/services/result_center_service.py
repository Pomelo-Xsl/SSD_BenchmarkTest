"""结果数据中心：快照持久化、基线评估、规则告警与历史聚合。"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from sqlalchemy.orm import Session
from app.analytics.quality import evaluate
from app.analytics.scoring import build_scorecard
from app.analytics.statistics import distribution
from app.models import AlertEvent, AlertRule, PerformanceBaseline, Result, ResultSnapshot, Task

METRICS = ("iops", "bw_mib_s", "latency_avg_us", "latency_p99_us", "cpu_user_pct", "cpu_system_pct")
VALID_OPERATORS = {"<", "<=", ">", ">=", "==", "!="}

@dataclass(frozen=True)
class AggregateMetric:
    metric: str
    count: int
    minimum: float | None
    maximum: float | None
    mean: float | None
    median: float | None
    percentile_95: float | None
    coefficient_variation: float | None

@dataclass(frozen=True)
class HistorySummary:
    device_name: str | None
    test_name: str | None
    from_time: datetime | None
    to_time: datetime | None
    total_snapshots: int
    metrics: tuple[AggregateMetric, ...]
    quality_mean: float | None
    score_mean: float | None

class ResultCenterService:
    @staticmethod
    def metrics(result: Result) -> dict[str, float | None]:
        return {key: getattr(result, key, None) for key in METRICS}

    @staticmethod
    def options(task: Task) -> dict[str, Any]:
        try: return json.loads(task.fio_options or "{}")
        except (TypeError, json.JSONDecodeError): return {}

    @classmethod
    def capture_snapshot(cls, db: Session, task: Task, result: Result) -> ResultSnapshot:
        """在任务完成时保存独立快照；重复调用会更新而不是生成重复历史。"""
        metrics, options = cls.metrics(result), cls.options(task)
        quality = evaluate(metrics, {"runtime_seconds": options.get("runtime_seconds")})
        stability = 100.0
        score = build_scorecard(metrics, task.test_name, stability)
        snapshot = db.query(ResultSnapshot).filter(ResultSnapshot.task_id == task.id).first()
        if snapshot is None:
            snapshot = ResultSnapshot(task_id=task.id, device_name=task.device_name, test_name=task.test_name, fio_options_json="{}", metrics_json="{}")
            db.add(snapshot)
        snapshot.device_name = task.device_name
        snapshot.test_name = task.test_name
        snapshot.fio_options_json = json.dumps(options, ensure_ascii=False, sort_keys=True)
        snapshot.metrics_json = json.dumps(metrics, ensure_ascii=False, sort_keys=True)
        snapshot.quality_score = quality.score
        snapshot.performance_score = score.total
        db.commit(); db.refresh(snapshot)
        return snapshot

    @staticmethod
    def snapshot_dict(snapshot: ResultSnapshot) -> dict[str, Any]:
        return {"id": snapshot.id, "task_id": snapshot.task_id, "device_name": snapshot.device_name, "test_name": snapshot.test_name, "fio_options": json.loads(snapshot.fio_options_json or "{}"), "metrics": json.loads(snapshot.metrics_json or "{}"), "quality_score": snapshot.quality_score, "performance_score": snapshot.performance_score, "captured_at": snapshot.captured_at}

    @classmethod
    def list_snapshots(cls, db: Session, device_name: str | None = None, test_name: str | None = None, limit: int = 100, offset: int = 0) -> list[ResultSnapshot]:
        query = db.query(ResultSnapshot)
        if device_name: query = query.filter(ResultSnapshot.device_name == device_name)
        if test_name: query = query.filter(ResultSnapshot.test_name == test_name)
        return query.order_by(ResultSnapshot.captured_at.desc(), ResultSnapshot.id.desc()).offset(max(offset, 0)).limit(max(1, min(limit, 500))).all()

    @classmethod
    def summarize(cls, snapshots: Iterable[ResultSnapshot], device_name: str | None = None, test_name: str | None = None) -> HistorySummary:
        rows = list(snapshots); values = [json.loads(item.metrics_json or "{}") for item in rows]
        items = []
        for metric in METRICS:
            dist = distribution([entry.get(metric) for entry in values])
            items.append(AggregateMetric(metric, dist.count, dist.minimum, dist.maximum, dist.mean, dist.median, dist.percentile_95, dist.coefficient_variation))
        quality = [item.quality_score for item in rows if item.quality_score is not None]
        score = [item.performance_score for item in rows if item.performance_score is not None]
        times = [item.captured_at for item in rows if item.captured_at]
        return HistorySummary(device_name, test_name, min(times) if times else None, max(times) if times else None, len(rows), tuple(items), round(sum(quality)/len(quality),2) if quality else None, round(sum(score)/len(score),2) if score else None)

    @staticmethod
    def create_baseline(db: Session, name: str, task: Task, result: Result, tolerance: dict[str, float] | None = None, notes: str | None = None) -> PerformanceBaseline:
        if db.query(PerformanceBaseline).filter(PerformanceBaseline.name == name).first():
            raise ValueError("基线名称已存在")
        baseline = PerformanceBaseline(name=name.strip(), device_name=task.device_name, test_name=task.test_name, source_task_id=task.id, fio_options_json=json.dumps(ResultCenterService.options(task), ensure_ascii=False), metrics_json=json.dumps(ResultCenterService.metrics(result), ensure_ascii=False), tolerance_json=json.dumps(tolerance or {}, ensure_ascii=False), notes=notes)
        db.add(baseline); db.commit(); db.refresh(baseline)
        return baseline

    @staticmethod
    def baseline_dict(baseline: PerformanceBaseline) -> dict[str, Any]:
        return {"id": baseline.id, "name": baseline.name, "device_name": baseline.device_name, "test_name": baseline.test_name, "source_task_id": baseline.source_task_id, "fio_options": json.loads(baseline.fio_options_json or "{}"), "metrics": json.loads(baseline.metrics_json or "{}"), "tolerance": json.loads(baseline.tolerance_json or "{}"), "enabled": baseline.enabled, "notes": baseline.notes, "created_at": baseline.created_at, "updated_at": baseline.updated_at}

    @staticmethod
    def compare_baseline(baseline: PerformanceBaseline, result: Result) -> dict[str, Any]:
        reference, tolerance, observed = json.loads(baseline.metrics_json or "{}"), json.loads(baseline.tolerance_json or "{}"), ResultCenterService.metrics(result)
        comparisons = []
        for metric in METRICS:
            before, after = reference.get(metric), observed.get(metric)
            if before in (None, 0) or after is None: continue
            delta_pct = (float(after)-float(before))/abs(float(before))*100
            threshold = float(tolerance.get(metric, 0))
            regression = delta_pct < -abs(threshold) if metric in {"iops", "bw_mib_s"} else delta_pct > abs(threshold)
            comparisons.append({"metric":metric,"baseline":before,"observed":after,"delta_percent":round(delta_pct,3),"tolerance_percent":threshold,"regression":regression})
        issues = [item for item in comparisons if item["regression"]]
        return {"baseline_id":baseline.id,"baseline_name":baseline.name,"compatible":baseline.device_name == result.task.device_name if hasattr(result,"task") else True,"comparisons":comparisons,"verdict":"存在性能回退" if issues else "满足基线容差","regression_count":len(issues)}

    @staticmethod
    def validate_rule(metric: str, operator: str, threshold: float) -> None:
        if metric not in set(METRICS) | {"quality_score", "performance_score"}: raise ValueError("不支持的告警指标")
        if operator not in VALID_OPERATORS: raise ValueError("operator 仅支持 <、<=、>、>=、==、!=")
        if not isinstance(threshold, (float, int)): raise ValueError("threshold 必须为数值")

    @staticmethod
    def compare(value: float, operator: str, threshold: float) -> bool:
        return {"<":value<threshold,"<=":value<=threshold,">":value>threshold,">=":value>=threshold,"==":value==threshold,"!=":value!=threshold}[operator]

    @classmethod
    def evaluate_rules(cls, db: Session, task: Task, result: Result, snapshot: ResultSnapshot | None = None) -> list[AlertEvent]:
        snapshot = snapshot or cls.capture_snapshot(db, task, result)
        metrics = cls.metrics(result) | {"quality_score": snapshot.quality_score, "performance_score": snapshot.performance_score}
        rules = db.query(AlertRule).filter(AlertRule.enabled.is_(True)).all(); created=[]
        for rule in rules:
            if rule.device_name and rule.device_name != task.device_name: continue
            if rule.test_name and rule.test_name != task.test_name: continue
            value = metrics.get(rule.metric)
            if value is None or not cls.compare(float(value), rule.operator, rule.threshold): continue
            existing = db.query(AlertEvent).filter(AlertEvent.rule_id==rule.id, AlertEvent.task_id==task.id).first()
            if existing: continue
            event = AlertEvent(rule_id=rule.id, task_id=task.id, device_name=task.device_name, severity=rule.severity, title=f"规则命中：{rule.name}", detail=f"{rule.metric}={value}，规则为 {rule.operator} {rule.threshold}", metric=rule.metric, observed_value=float(value), threshold=rule.threshold)
            db.add(event); created.append(event)
        if created: db.commit()
        return created

    @staticmethod
    def alert_dict(event: AlertEvent) -> dict[str, Any]:
        return {"id":event.id,"rule_id":event.rule_id,"task_id":event.task_id,"device_name":event.device_name,"severity":event.severity,"title":event.title,"detail":event.detail,"metric":event.metric,"observed_value":event.observed_value,"threshold":event.threshold,"status":event.status,"created_at":event.created_at,"acknowledged_at":event.acknowledged_at}

    @staticmethod
    def acknowledge(db: Session, event: AlertEvent) -> AlertEvent:
        if event.status != "acknowledged": event.status, event.acknowledged_at = "acknowledged", datetime.now(timezone.utc); db.commit(); db.refresh(event)
        return event

    @staticmethod
    def stale_alerts(db: Session, days: int = 30) -> list[AlertEvent]:
        cutoff=datetime.now(timezone.utc)-timedelta(days=max(1,days))
        return db.query(AlertEvent).filter(AlertEvent.status=="open", AlertEvent.created_at < cutoff).order_by(AlertEvent.created_at).all()

"""数据库实体：设备、任务与结果。"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base


class Device(Base):
    __tablename__ = "devices"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    path: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(255))
    serial: Mapped[Optional[str]] = mapped_column(String(255))
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    firmware: Mapped[Optional[str]] = mapped_column(String(100))
    temperature_c: Mapped[Optional[float]] = mapped_column(Float)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("test_batches.id"))
    device_name: Mapped[str] = mapped_column(ForeignKey("devices.name"), nullable=False)
    test_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    fio_options: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    fio_json_path: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class TestBatch(Base):
    """一组按顺序执行的 fio 测试。"""

    __tablename__ = "test_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_name: Mapped[str] = mapped_column(ForeignKey("devices.name"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Result(Base):
    __tablename__ = "results"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), unique=True, nullable=False)
    iops: Mapped[Optional[float]] = mapped_column(Float)
    bw_mib_s: Mapped[Optional[float]] = mapped_column(Float)
    latency_avg_us: Mapped[Optional[float]] = mapped_column(Float)
    latency_p99_us: Mapped[Optional[float]] = mapped_column(Float)
    cpu_user_pct: Mapped[Optional[float]] = mapped_column(Float)
    cpu_system_pct: Mapped[Optional[float]] = mapped_column(Float)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)


class BenchmarkTemplate(Base):
    """可复用的 fio 测试参数模板。"""

    __tablename__ = "benchmark_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500))
    test_name: Mapped[str] = mapped_column(String(50), nullable=False)
    fio_options: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AuditEvent(Base):
    """关键操作审计记录，便于追踪测试、格式化和删除行为。"""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[Optional[str]] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ResultSnapshot(Base):
    """完成时固化的标准化指标快照，用于跨任务历史分析。"""

    __tablename__ = "result_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), unique=True, nullable=False, index=True)
    device_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    test_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    fio_options_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    quality_score: Mapped[Optional[float]] = mapped_column(Float)
    performance_score: Mapped[Optional[float]] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PerformanceBaseline(Base):
    """经确认的性能基线；一个设备和测试类型可以维护多个版本。"""

    __tablename__ = "performance_baselines"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    device_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    test_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"))
    fio_options_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    tolerance_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AlertRule(Base):
    """针对指标阈值、基线偏差或质量分数的告警规则。"""

    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    device_name: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    test_name: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    operator: Mapped[str] = mapped_column(String(8), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AlertEvent(Base):
    """每次规则命中产生的持久化告警事件。"""

    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("alert_rules.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True, nullable=False)
    device_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[Optional[str]] = mapped_column(String(80))
    observed_value: Mapped[Optional[float]] = mapped_column(Float)
    threshold: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class DeviceHealthSnapshot(Base):
    """定期采集的 NVMe SMART 健康快照，用于寿命和温度趋势。"""

    __tablename__ = "device_health_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_name: Mapped[str] = mapped_column(ForeignKey("devices.name"), nullable=False, index=True)
    temperature_c: Mapped[Optional[float]] = mapped_column(Float)
    available_spare: Mapped[Optional[float]] = mapped_column(Float)
    percentage_used: Mapped[Optional[float]] = mapped_column(Float)
    media_errors: Mapped[Optional[int]] = mapped_column(Integer)
    error_log_entries: Mapped[Optional[int]] = mapped_column(Integer)
    unsafe_shutdowns: Mapped[Optional[int]] = mapped_column(Integer)
    power_on_hours: Mapped[Optional[int]] = mapped_column(Integer)
    health_score: Mapped[Optional[float]] = mapped_column(Float)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class NvmeLogArchive(Base):
    """归档 telemetry 与扩展 SMART 原始日志的元数据和文件位置。"""

    __tablename__ = "nvme_log_archives"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_name: Mapped[str] = mapped_column(ForeignKey("devices.name"), nullable=False, index=True)
    log_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    command_json: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    byte_size: Mapped[Optional[int]] = mapped_column(Integer)
    checksum_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ScheduledPlan(Base):
    """可持久化的周期测试计划；周期以分钟为单位，最小 1 分钟。"""

    __tablename__ = "scheduled_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    device_name: Mapped[str] = mapped_column(ForeignKey("devices.name"), nullable=False, index=True)
    tests_json: Mapped[str] = mapped_column(Text, nullable=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("test_batches.id"))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PlanRun(Base):
    """计划调度历史，记录每一轮是否成功创建批次。"""

    __tablename__ = "plan_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("scheduled_plans.id"), nullable=False, index=True)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("test_batches.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RetentionPolicy(Base):
    """结果、日志和健康快照的数据保留策略。"""

    __tablename__ = "retention_policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    retain_days: Mapped[int] = mapped_column(Integer, nullable=False)
    max_records: Mapped[Optional[int]] = mapped_column(Integer)
    archive_before_delete: Mapped[bool] = mapped_column(default=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_summary_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class RetentionRun(Base):
    """保留策略的预览或实际执行审计记录。"""

    __tablename__ = "retention_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("retention_policies.id"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    ran_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class BaselineRevision(Base):
    """性能基线的不可变版本快照，支持评审、回滚和追溯。"""

    __tablename__ = "baseline_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    baseline_id: Mapped[int] = mapped_column(ForeignKey("performance_baselines.id"), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    fio_options_json: Mapped[str] = mapped_column(Text, nullable=False)
    tolerance_json: Mapped[str] = mapped_column(Text, nullable=False)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    reviewer_note: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DiagnosticFinding(Base):
    """设备与测试结果的规则诊断结论及其关联证据。"""

    __tablename__ = "diagnostic_findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"), index=True)
    device_name: Mapped[str] = mapped_column(ForeignKey("devices.name"), nullable=False, index=True)
    rule_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

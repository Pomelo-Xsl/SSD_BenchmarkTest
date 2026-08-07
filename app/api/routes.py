"""REST API 路由，仅负责输入输出和 HTTP 错误映射。"""
import logging
import json
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.core.config import settings
from app.models import AlertEvent, AlertRule, AuditEvent, BenchmarkTemplate, Device, DeviceHealthSnapshot, DiagnosticFinding, NvmeLogArchive, PerformanceBaseline, PlanRun, Result, ResultSnapshot, RetentionPolicy, RetentionRun, ScheduledPlan, Task, TestBatch
from app.schemas.schemas import BatchCreate, BatchCreated, BatchResult, BatchTaskOut, DeviceFormatRequest, DeviceFormatResult, DeviceOut, TaskCreate, TaskDeleteManyRequest, TaskDeleteManyResult, TaskListItem, TemplateCreate, TemplateOut, TemplateUpdate, TestCreated, TestResult, AuditEventOut
from app.analytics import BenchmarkAnalysisService
from app.analytics.types import serialise
from app.services.audit_service import AuditService
from app.services.batch_service import BatchService
from app.services.device_service import DeviceService
from app.services.fio_service import FioOptions, FioService
from app.parsers.fio_parser import FioParser
from app.services.format_service import NvmeFormatService
from app.services.safety_service import SafetyService
from app.services.template_service import TemplateService
from app.services.report_service import ReportService
from app.services.result_center_service import ResultCenterService
from app.services.nvme_diagnostics_service import NvmeDiagnosticsService
from app.services.schedule_service import ScheduleService
from app.services.retention_service import RetentionService
from app.services.diagnostic_rule_service import DiagnosticRuleService
from app.services.mixed_workload_service import MixedWorkloadService
from app.services.performance_monitor_service import PerformanceMonitorService
from app.services.batch_comparison_service import BatchComparisonService
from app.services.platform_compatibility_service import PlatformCompatibilityService
from app.services.qd_scan_service import QdScanService
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/devices/{device_name}/diagnostics")
def run_device_diagnostics(device_name: str, task_id: Optional[int] = None, db: Session = Depends(get_db)) -> dict:
    device = db.get(Device, device_name)
    if not device: raise HTTPException(status_code=404, detail="设备不存在")
    task = db.get(Task, task_id) if task_id is not None else None
    if task and task.device_name != device_name: raise HTTPException(status_code=400, detail="任务不属于当前设备")
    result = db.query(Result).filter(Result.task_id == task_id).first() if task_id is not None else None
    health = db.query(DeviceHealthSnapshot).filter(DeviceHealthSnapshot.device_name == device_name).order_by(DeviceHealthSnapshot.id.desc()).first()
    findings = DiagnosticRuleService.evaluate(task, result, DiagnosticRuleService.health(health))
    rows = DiagnosticRuleService.persist(db, device_name, findings, task_id)
    return {"created": [DiagnosticRuleService.serialize(row) for row in rows], "finding_count": len(findings)}


@router.get("/diagnostics")
def list_diagnostics(device_name: Optional[str] = None, task_id: Optional[int] = None, status_filter: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    query = db.query(DiagnosticFinding)
    if device_name: query = query.filter(DiagnosticFinding.device_name == device_name)
    if task_id is not None: query = query.filter(DiagnosticFinding.task_id == task_id)
    if status_filter: query = query.filter(DiagnosticFinding.status == status_filter)
    return [DiagnosticRuleService.serialize(item) for item in query.order_by(DiagnosticFinding.id.desc()).limit(max(1, min(limit, 500))).all()]


@router.post("/diagnostics/{finding_id}/resolve")
def resolve_diagnostic(finding_id: int, db: Session = Depends(get_db)) -> dict:
    finding = db.get(DiagnosticFinding, finding_id)
    if not finding: raise HTTPException(status_code=404, detail="诊断记录不存在")
    finding = DiagnosticRuleService.resolve(db, finding)
    AuditService.record(db, "diagnostic.resolved", "diagnostic", f"关闭诊断记录 #{finding_id}", finding_id)
    return DiagnosticRuleService.serialize(finding)


@router.post("/retention-policies")
def create_retention_policy(payload: dict, db: Session = Depends(get_db)) -> dict:
    try:
        policy = RetentionService.create(db, str(payload["name"]), str(payload["resource_type"]), int(payload["retain_days"]), payload.get("max_records"), bool(payload.get("archive_before_delete", True)))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"无效保留策略：{exc}") from exc
    AuditService.record(db, "retention_policy.created", "retention_policy", f"创建数据保留策略：{policy.name}", policy.id)
    return RetentionService.serialize(policy)


@router.get("/retention-policies")
def list_retention_policies(db: Session = Depends(get_db)) -> list[dict]:
    return [RetentionService.serialize(item) for item in db.query(RetentionPolicy).order_by(RetentionPolicy.id.desc()).all()]


@router.get("/retention-policies/{policy_id}/preview")
def preview_retention_policy(policy_id: int, db: Session = Depends(get_db)) -> dict:
    policy = db.get(RetentionPolicy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="保留策略不存在")
    preview = RetentionService.preview(db, policy)
    return {"policy": RetentionService.serialize(policy), "cutoff": preview.cutoff, "candidates": preview.candidates, "candidate_ids": list(preview.candidate_ids), "reasons": preview.reasons}


@router.post("/retention-policies/{policy_id}/execute")
def execute_retention_policy(policy_id: int, confirm: bool = False, db: Session = Depends(get_db)) -> dict:
    policy = db.get(RetentionPolicy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="保留策略不存在")
    outcome = RetentionService.execute(db, policy, confirm)
    AuditService.record(db, "retention_policy.executed", "retention_policy", f"{'执行' if confirm else '预览'}数据保留策略：{policy.name}", policy.id, outcome)
    return outcome


@router.post("/qd-scans")
def create_qd_scan(payload: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    """创建 QD 扫描批次：每个 QD 一个任务，按队列顺序执行。"""
    try:
        plan = QdScanService.plan(str(payload["device_name"]), str(payload["test_name"]), payload.get("qd_values"), payload.get("runtime_seconds", 60), payload.get("ramp_time_seconds", 10), payload.get("numjobs", 1), str(payload.get("ioengine", "io_uring")), bool(payload.get("direct", True)))
        batch, tasks = QdScanService.create_batch(db, plan, bool(payload.get("confirm_destructive", False)))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"无效 QD 扫描：{exc}") from exc
    background_tasks.add_task(BatchService.execute, batch.id)
    AuditService.record(db, "qd_scan.created", "batch", f"创建 QD 扫描批次 #{batch.id}", batch.id, {"qd_values": plan.qd_values, "test_name": plan.test_name})
    return {"batch_id":batch.id,"task_ids":[task.id for task in tasks],"qd_values":list(plan.qd_values),"destructive":plan.destructive}


@router.get("/qd-scans/{batch_id}")
def get_qd_scan(batch_id: int, db: Session = Depends(get_db)) -> dict:
    tasks=db.query(Task).filter(Task.batch_id==batch_id).order_by(Task.id).all()
    if not tasks: raise HTTPException(status_code=404,detail="QD 扫描批次不存在")
    rows=[]
    for task in tasks:
        result=db.query(Result).filter(Result.task_id==task.id).first()
        rows.append({"task_id":task.id,"status":task.status,"fio_options":json.loads(task.fio_options or "{}"),"result":{"iops":result.iops,"bw_mib_s":result.bw_mib_s,"latency_avg_us":result.latency_avg_us,"latency_p99_us":result.latency_p99_us} if result else None})
    return QdScanService.summarize(rows) | {"batch_id":batch_id}


@router.get("/mixed-workloads/presets")
def mixed_workload_presets() -> list[dict]:
    return MixedWorkloadService.presets()


@router.post("/mixed-workloads/preview")
def preview_mixed_workload(payload: dict) -> dict:
    try:
        workload = MixedWorkloadService.create(str(payload.get("name", "mixed_workload")), str(payload.get("description", "")), list(payload["phases"]))
        return workload.profile() | {"write_ratio_percent": MixedWorkloadService.expected_write_ratio(workload), "fio_job": MixedWorkloadService.fio_job_sections(workload, str(payload.get("device_path", "/dev/nvmeXnY")), str(payload.get("ioengine", "io_uring")))}
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/performance-curve/aggregate")
def aggregate_performance_curve(payload: dict) -> dict:
    try:
        points = [PerformanceMonitorService.point(item) for item in payload.get("points", [])]
        return {"chart": PerformanceMonitorService.chart(points, int(payload.get("max_points", 240))), "windows": [item.__dict__ for item in PerformanceMonitorService.windows(points, int(payload.get("window_seconds", 30)))]}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"无效性能曲线：{exc}") from exc


@router.get("/comparisons/tasks")
def compare_tasks(task_ids: str, db: Session = Depends(get_db)) -> dict:
    ids = [int(item) for item in task_ids.split(",") if item.strip().isdigit()]
    pairs = db.query(Task, Result).join(Result, Result.task_id == Task.id).filter(Task.id.in_(ids), Task.status == "completed").all()
    rows = BatchComparisonService.rank(pairs)
    return {"items": [item.__dict__ for item in rows], "summary": BatchComparisonService.summary(rows)}


@router.get("/platform/compatibility")
def platform_compatibility() -> dict:
    return PlatformCompatibilityService.inspect()


@router.get("/scheduled-plans")
def list_scheduled_plans(db: Session = Depends(get_db)) -> list[dict]:
    """返回已配置的周期测试计划，供运维页面展示。"""
    plans = db.query(ScheduledPlan).order_by(ScheduledPlan.id.desc()).all()
    return [ScheduleService.serialize(plan) for plan in plans]


@router.post("/scheduled-plans")
def create_scheduled_plan(payload: dict, db: Session = Depends(get_db)) -> dict:
    """创建周期性 fio 批量测试计划。"""
    try:
        plan = ScheduleService.create(db, str(payload["name"]), str(payload["device_name"]), int(payload["interval_minutes"]), list(payload["tests"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"无效定时计划：{exc}") from exc
    AuditService.record(db, "scheduled_plan.created", "scheduled_plan", f"创建周期测试计划：{plan.name}", plan.id)
    return ScheduleService.serialize(plan)


@router.post("/scheduled-plans/{plan_id}/enabled")
def set_scheduled_plan_enabled(plan_id: int, payload: dict, db: Session = Depends(get_db)) -> dict:
    """启用或暂停一个周期测试计划。"""
    plan = db.get(ScheduledPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    plan.enabled = bool(payload.get("enabled", True))
    db.commit(); db.refresh(plan)
    AuditService.record(db, "scheduled_plan.updated", "scheduled_plan", f"{'启用' if plan.enabled else '暂停'}周期测试计划：{plan.name}", plan.id)
    return ScheduleService.serialize(plan)


@router.delete("/scheduled-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scheduled_plan(plan_id: int, db: Session = Depends(get_db)) -> Response:
    """删除周期测试计划及其调度历史。"""
    plan = db.get(ScheduledPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    db.query(PlanRun).filter(PlanRun.plan_id == plan_id).delete(synchronize_session=False)
    db.delete(plan); db.commit()
    AuditService.record(db, "scheduled_plan.deleted", "scheduled_plan", f"删除周期测试计划：{plan.name}", plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(db: Session = Depends(get_db)) -> list[dict]:
    """扫描并返回当前检测到的 NVMe SSD。"""
    try:
        return DeviceService.scan_devices(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/devices/{device_name}/format", response_model=DeviceFormatResult)
def format_device(device_name: str, payload: DeviceFormatRequest, db: Session = Depends(get_db)) -> DeviceFormatResult:
    """按固定 NVMe 参数格式化专用空盘；该操作不可恢复。"""
    device = db.get(Device, device_name)
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在，请先重新扫描")
    if payload.confirm_device_name != device.name:
        raise HTTPException(status_code=400, detail="二次确认失败：请输入完整且匹配的设备名")
    try:
        SafetyService.check_format(device.path)
        command, output = NvmeFormatService.run(device.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("NVMe format 失败: %s", device.name)
        raise HTTPException(status_code=500, detail=f"NVMe format 失败: {exc}") from exc
    AuditService.record(db, "device.formatted", "device", f"已执行 NVMe format: {device.name}", device.name, {"command": command})
    return DeviceFormatResult(device_name=device.name, command=command, output=output)


@router.post("/tests", response_model=TestCreated, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> Task:
    """创建任务后异步执行，立即返回任务 ID。"""
    try:
        device_name = payload.device_name or settings.default_device_name
        if not device_name:
            raise ValueError("未指定设备；请传入 device_name 或设置 SSD_BENCHMARK_DEFAULT_DEVICE_NAME")
        task = TaskService.create(
            db, device_name=device_name, test_name=payload.test_name,
            confirm_destructive=payload.confirm_destructive,
            fio_options=payload.fio_options.model_dump(exclude_none=True) if payload.fio_options else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AuditService.record(db, "task.created", "task", f"创建测试任务 #{task.id}", task.id, {"device_name": device_name, "test_name": payload.test_name})
    background_tasks.add_task(TaskService.execute, task.id)
    return TestCreated(id=task.id, status=task.status, fio_options=json.loads(task.fio_options or "{}"))


@router.post("/batches", response_model=BatchCreated, status_code=status.HTTP_201_CREATED)
def create_batch(payload: BatchCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> BatchCreated:
    """建立多个 fio 测试，并在后台按顺序执行。"""
    try:
        device_name = payload.device_name or settings.default_device_name
        if not device_name:
            raise ValueError("未指定设备；请传入 device_name 或设置 SSD_BENCHMARK_DEFAULT_DEVICE_NAME")
        tests = [
            {
                "test_name": item.test_name,
                "confirm_destructive": item.confirm_destructive,
                "fio_options": item.fio_options.model_dump(exclude_none=True) if item.fio_options else None,
            }
            for item in payload.tests
        ]
        batch, tasks = BatchService.create(db, device_name, tests)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(BatchService.execute, batch.id)
    return BatchCreated(id=batch.id, status=batch.status, task_ids=[task.id for task in tasks])


@router.get("/batches/{batch_id}", response_model=BatchResult)
def get_batch(batch_id: int, db: Session = Depends(get_db)) -> BatchResult:
    """查询批量测试队列及每一个子测试的状态。"""
    batch = db.get(TestBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批量测试不存在")
    tasks = db.query(Task).filter(Task.batch_id == batch_id).order_by(Task.id).all()
    return BatchResult(
        id=batch.id, device_name=batch.device_name, status=batch.status, error_message=batch.error_message,
        tasks=[BatchTaskOut(id=task.id, test_name=task.test_name, status=task.status,
                            progress_percent=TaskService.progress(task)[0], progress_phase=TaskService.progress(task)[1]) for task in tasks],
    )


@router.get("/tasks", response_model=list[TaskListItem])
def list_tasks(db: Session = Depends(get_db)) -> list[TaskListItem]:
    """返回全部测试任务，供结果页面统一罗列和快速查看。"""
    tasks = db.query(Task).order_by(Task.id.desc()).all()
    batch_ids = {task.batch_id for task in tasks if task.batch_id is not None}
    batches = {batch.id: batch for batch in db.query(TestBatch).filter(TestBatch.id.in_(batch_ids)).all()} if batch_ids else {}
    # 兼容旧数据：早期 QD 扫描批次只有审计事件，仍按 QD 扫描展示。
    qd_batch_ids = {int(event.target_id) for event in db.query(AuditEvent).filter(AuditEvent.event_type == "qd_scan.created").all() if str(event.target_id or "").isdigit()}
    return [
        TaskListItem(
            id=task.id, device_name=task.device_name, test_name=task.test_name, status=task.status,
            created_at=task.created_at, progress_percent=TaskService.progress(task)[0],
            progress_phase=TaskService.progress(task)[1], batch_id=task.batch_id,
            batch_type="qd_scan" if task.batch_id in qd_batch_ids or (batches.get(task.batch_id) and batches[task.batch_id].batch_type == "qd_scan") else None,
            qd_value=json.loads(task.fio_options or "{}").get("iodepth") if task.batch_id in qd_batch_ids or (batches.get(task.batch_id) and batches[task.batch_id].batch_type == "qd_scan") else None,
        )
        for task in tasks
    ]


@router.delete("/tasks", response_model=TaskDeleteManyResult)
def delete_tasks(payload: TaskDeleteManyRequest, db: Session = Depends(get_db)) -> TaskDeleteManyResult:
    """批量删除已结束任务及结果；只要包含运行/排队任务则整体拒绝。"""
    task_ids = list(dict.fromkeys(payload.task_ids))
    tasks = db.query(Task).filter(Task.id.in_(task_ids)).all()
    found_ids = {task.id for task in tasks}
    missing_ids = [task_id for task_id in task_ids if task_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"测试任务不存在: {', '.join(map(str, missing_ids))}")
    protected_ids = [task.id for task in tasks if task.status not in {"completed", "failed"}]
    if protected_ids:
        raise HTTPException(status_code=409, detail=f"任务仍在运行或排队中，暂不能删除: {', '.join(map(str, protected_ids))}")
    db.query(Result).filter(Result.task_id.in_(task_ids)).delete(synchronize_session=False)
    for task in tasks:
        db.delete(task)
    db.commit()
    AuditService.record(db, "tasks.deleted", "task", f"批量删除 {len(task_ids)} 个测试任务", ",".join(map(str, task_ids)), {"task_ids": task_ids})
    logger.info("已批量删除测试任务 %s", task_ids)
    return TaskDeleteManyResult(deleted_task_ids=task_ids)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db)) -> Response:
    """删除已结束任务及其结果；运行或排队中的任务不得删除。"""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="测试任务不存在")
    if task.status not in {"completed", "failed"}:
        raise HTTPException(status_code=409, detail="任务仍在运行或排队中，暂不能删除")
    db.query(Result).filter(Result.task_id == task_id).delete(synchronize_session=False)
    db.delete(task)
    db.commit()
    AuditService.record(db, "task.deleted", "task", f"删除测试任务 #{task_id}", task_id)
    logger.info("已删除测试任务 %s", task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _task_with_result(db: Session, task_id: int) -> tuple[Task, Result]:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="测试任务不存在")
    result = db.query(Result).filter(Result.task_id == task_id).first()
    if not result:
        raise HTTPException(status_code=409, detail="任务尚无可分析的完成结果")
    return task, result


@router.post("/devices/{device_name}/health")
def capture_device_health(device_name: str, db: Session = Depends(get_db)) -> dict:
    """主动采集 NVMe SMART JSON，保存健康快照并生成健康评分。"""
    device = db.get(Device, device_name)
    if not device: raise HTTPException(status_code=404, detail="设备不存在，请先扫描设备")
    try: snapshot = NvmeDiagnosticsService.capture_health(db, device)
    except Exception as exc: raise HTTPException(status_code=500, detail=f"SMART 采集失败：{exc}") from exc
    AuditService.record(db,"device.health_captured","device",f"采集 SMART 健康快照：{device.name}",device.name)
    return NvmeDiagnosticsService.health_dict(snapshot)


@router.get("/devices/{device_name}/health-history")
def device_health_history(device_name: str, limit: int = 100, db: Session = Depends(get_db)) -> dict:
    """查询某设备的健康快照与温度趋势。"""
    rows = db.query(DeviceHealthSnapshot).filter(DeviceHealthSnapshot.device_name == device_name).order_by(DeviceHealthSnapshot.captured_at.asc()).limit(max(1,min(limit,500))).all()
    return {"items":[NvmeDiagnosticsService.health_dict(row) for row in rows],"thermal_trend":serialise(NvmeDiagnosticsService.thermal_trend(rows))}


@router.post("/devices/{device_name}/logs/{log_type}")
def archive_nvme_log(device_name: str, log_type: str, db: Session = Depends(get_db)) -> dict:
    """采集 telemetry 或扩展 SMART 二进制日志并归档文件校验和。"""
    device = db.get(Device, device_name)
    if not device: raise HTTPException(status_code=404, detail="设备不存在，请先扫描设备")
    try: archive=NvmeDiagnosticsService.archive_log(db,device,log_type)
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc
    AuditService.record(db,"device.log_archived","device",f"归档 NVMe {log_type} 日志：{device.name}",device.name,{"archive_id":archive.id})
    return NvmeDiagnosticsService.archive_dict(archive)


@router.get("/devices/{device_name}/logs")
def list_nvme_logs(device_name: str, limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    rows=db.query(NvmeLogArchive).filter(NvmeLogArchive.device_name==device_name).order_by(NvmeLogArchive.id.desc()).limit(max(1,min(limit,500))).all()
    return [NvmeDiagnosticsService.archive_dict(row) for row in rows]


@router.get("/history")
def result_history(device_name: Optional[str] = None, test_name: Optional[str] = None, limit: int = 100, offset: int = 0, db: Session = Depends(get_db)) -> dict:
    """分页查询持久化结果快照，并返回该筛选范围的聚合统计。"""
    rows = ResultCenterService.list_snapshots(db, device_name, test_name, limit, offset)
    all_rows = ResultCenterService.list_snapshots(db, device_name, test_name, 500, 0)
    return {"items": [ResultCenterService.snapshot_dict(row) for row in rows], "summary": serialise(ResultCenterService.summarize(all_rows, device_name, test_name)), "limit": max(1, min(limit, 500)), "offset": max(offset, 0)}


@router.post("/baselines/from-task/{task_id}")
def create_baseline_from_task(task_id: int, name: str, tolerance_percent: float = 5.0, notes: Optional[str] = None, db: Session = Depends(get_db)) -> dict:
    """从一个已完成任务创建可复用性能基线。"""
    task, result = _task_with_result(db, task_id)
    try:
        baseline = ResultCenterService.create_baseline(db, name, task, result, {metric: tolerance_percent for metric in ("iops", "bw_mib_s", "latency_avg_us", "latency_p99_us")}, notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AuditService.record(db, "baseline.created", "baseline", f"从任务 #{task_id} 创建性能基线：{name}", baseline.id)
    return ResultCenterService.baseline_dict(baseline)


@router.get("/baselines")
def list_baselines(device_name: Optional[str] = None, test_name: Optional[str] = None, db: Session = Depends(get_db)) -> list[dict]:
    query = db.query(PerformanceBaseline)
    if device_name: query = query.filter(PerformanceBaseline.device_name == device_name)
    if test_name: query = query.filter(PerformanceBaseline.test_name == test_name)
    return [ResultCenterService.baseline_dict(row) for row in query.order_by(PerformanceBaseline.id.desc()).all()]


@router.get("/baselines/{baseline_id}/compare/{task_id}")
def compare_baseline(baseline_id: int, task_id: int, db: Session = Depends(get_db)) -> dict:
    baseline = db.get(PerformanceBaseline, baseline_id)
    if not baseline: raise HTTPException(status_code=404, detail="性能基线不存在")
    _, result = _task_with_result(db, task_id)
    return ResultCenterService.compare_baseline(baseline, result)


@router.post("/alert-rules")
def create_alert_rule(payload: dict, db: Session = Depends(get_db)) -> dict:
    """创建指标阈值告警规则。body 包含 name、metric、operator、threshold，可选 device_name/test_name。"""
    try:
        name, metric, operator, threshold = str(payload["name"]).strip(), str(payload["metric"]), str(payload["operator"]), float(payload["threshold"])
        ResultCenterService.validate_rule(metric, operator, threshold)
        if not name: raise ValueError("规则名称不能为空")
        if db.query(AlertRule).filter(AlertRule.name == name).first(): raise ValueError("规则名称已存在")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"无效告警规则：{exc}") from exc
    rule = AlertRule(name=name, metric=metric, operator=operator, threshold=threshold, severity=str(payload.get("severity", "warning")), device_name=payload.get("device_name"), test_name=payload.get("test_name"), description=payload.get("description"))
    db.add(rule); db.commit(); db.refresh(rule)
    AuditService.record(db, "alert_rule.created", "alert_rule", f"创建告警规则：{rule.name}", rule.id)
    return {"id":rule.id,"name":rule.name,"metric":rule.metric,"operator":rule.operator,"threshold":rule.threshold,"severity":rule.severity,"enabled":rule.enabled}


@router.get("/alert-rules")
def list_alert_rules(db: Session = Depends(get_db)) -> list[dict]:
    return [{"id":row.id,"name":row.name,"device_name":row.device_name,"test_name":row.test_name,"metric":row.metric,"operator":row.operator,"threshold":row.threshold,"severity":row.severity,"enabled":row.enabled,"description":row.description,"created_at":row.created_at} for row in db.query(AlertRule).order_by(AlertRule.id.desc()).all()]


@router.get("/alerts")
def list_alerts(status_filter: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    query = db.query(AlertEvent)
    if status_filter: query = query.filter(AlertEvent.status == status_filter)
    return [ResultCenterService.alert_dict(item) for item in query.order_by(AlertEvent.id.desc()).limit(max(1, min(limit, 500))).all()]


@router.post("/alerts/{event_id}/acknowledge")
def acknowledge_alert(event_id: int, db: Session = Depends(get_db)) -> dict:
    event = db.get(AlertEvent, event_id)
    if not event: raise HTTPException(status_code=404, detail="告警事件不存在")
    event = ResultCenterService.acknowledge(db, event)
    AuditService.record(db, "alert.acknowledged", "alert", f"确认告警 #{event_id}", event_id)
    return ResultCenterService.alert_dict(event)


@router.get("/analysis/compare")
def compare_analysis(baseline_task_id: int, candidate_task_id: int, db: Session = Depends(get_db)) -> dict:
    """对比两个已完成任务的性能变化。"""
    baseline_task, baseline_result = _task_with_result(db, baseline_task_id)
    candidate_task, candidate_result = _task_with_result(db, candidate_task_id)
    return serialise(BenchmarkAnalysisService.comparison(baseline_task, baseline_result, candidate_task, candidate_result))


@router.get("/analysis/{task_id}")
def task_analysis(task_id: int, db: Session = Depends(get_db)) -> dict:
    """生成评分、稳定性、异常和历史趋势分析。"""
    task, result = _task_with_result(db, task_id)
    pairs = db.query(Task, Result).join(Result, Result.task_id == Task.id).filter(Task.status == "completed").all()
    report = BenchmarkAnalysisService.report(task, result, pairs)
    return serialise(report)


@router.get("/reports/{task_id}")
def export_report(task_id: int, report_format: str = "json", db: Session = Depends(get_db)) -> Response:
    """导出某个完成任务的分析报告。"""
    task, result = _task_with_result(db, task_id)
    pairs = db.query(Task, Result).join(Result, Result.task_id == Task.id).filter(Task.status == "completed").all()
    analysis = serialise(BenchmarkAnalysisService.report(task, result, pairs))
    payload = {"task": {"id": task.id, "device_name": task.device_name, "test_name": task.test_name, "status": task.status}, "analysis": analysis}
    try:
        body, media_type = ReportService.render(payload, report_format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    headers = {"Content-Disposition": f'attachment; filename="task_{task_id}_report.{report_format}"'}
    return Response(content=body, media_type=media_type, headers=headers)


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(db: Session = Depends(get_db)) -> list[dict]:
    return [TemplateService.as_dict(item) for item in db.query(BenchmarkTemplate).order_by(BenchmarkTemplate.id.desc()).all()]


@router.post("/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)) -> dict:
    try:
        template = TemplateService.create(db, payload.name, payload.description, payload.test_name, payload.fio_options.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AuditService.record(db, "template.created", "template", f"创建 fio 模板：{template.name}", template.id)
    return TemplateService.as_dict(template)


@router.patch("/templates/{template_id}", response_model=TemplateOut)
def update_template(template_id: int, payload: TemplateUpdate, db: Session = Depends(get_db)) -> dict:
    template = db.get(BenchmarkTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    try:
        template = TemplateService.update(db, template, payload.name, payload.description, payload.test_name, payload.fio_options.model_dump(exclude_none=True) if payload.fio_options else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AuditService.record(db, "template.updated", "template", f"更新 fio 模板：{template.name}", template.id)
    return TemplateService.as_dict(template)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: int, db: Session = Depends(get_db)) -> Response:
    template = db.get(BenchmarkTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    name = template.name
    db.delete(template)
    db.commit()
    AuditService.record(db, "template.deleted", "template", f"删除 fio 模板：{name}", template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/audit-events", response_model=list[AuditEventOut])
def list_audit_events(limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    """返回最近审计事件，最多 500 条。"""
    limit = max(1, min(limit, 500))
    events = db.query(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit).all()
    return [{"id": event.id, "event_type": event.event_type, "target_type": event.target_type, "target_id": event.target_id, "message": event.message, "detail": AuditService.detail(event), "created_at": event.created_at} for event in events]


@router.get("/results/{task_id}", response_model=TestResult)
def get_result(task_id: int, db: Session = Depends(get_db)) -> TestResult:
    """查询测试状态；完成时同时返回性能结果，失败时返回错误。"""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="测试不存在")
    result = db.query(Result).filter(Result.task_id == task_id).first()
    metrics = None
    if result and result.latency_p99_us is None:
        # 历史 fio JSON 可能将 P99 放在 clat_ns；查询时一次性补算并回写。
        try:
            repaired = FioParser.parse_raw_json(result.raw_json)
            if repaired.latency_p99_us is not None:
                result.latency_p99_us = repaired.latency_p99_us
                db.commit()
        except (ValueError, json.JSONDecodeError, TypeError):
            logger.warning("任务 %s 的历史原始 fio JSON 无法补算 P99", task_id)
    if result:
        metrics = {
            "iops": result.iops,
            "bw_mib_s": result.bw_mib_s,
            "latency_avg_us": result.latency_avg_us,
            "latency_p99_us": result.latency_p99_us,
            "cpu_user_pct": result.cpu_user_pct,
            "cpu_system_pct": result.cpu_system_pct,
        }
    options_data = json.loads(task.fio_options or "{}")
    device = db.get(Device, task.device_name)
    if not device:
        raise HTTPException(status_code=404, detail="任务对应设备不存在")
    fio_command = FioService.build_command(
        device.path, task.test_name, settings.results_dir / f"task_{task.id}.json",
        FioOptions.from_mapping(options_data),
    )
    progress_percent, progress_phase, elapsed_seconds, total_seconds = TaskService.progress(task)
    batch = db.get(TestBatch, task.batch_id) if task.batch_id is not None else None
    legacy_qd = bool(task.batch_id is not None and db.query(AuditEvent).filter(AuditEvent.event_type == "qd_scan.created", AuditEvent.target_id == str(task.batch_id)).first())
    is_qd_scan = bool(batch and batch.batch_type == "qd_scan") or legacy_qd
    return TestResult(
        task_id=task.id, device_name=task.device_name, device_path=device.path,
        test_name=task.test_name, fio_command=fio_command, status=task.status,
        error_message=task.error_message, fio_options=options_data, progress_percent=progress_percent,
        progress_phase=progress_phase, elapsed_seconds=elapsed_seconds, total_seconds=total_seconds,
        result=metrics, batch_id=task.batch_id, batch_type="qd_scan" if is_qd_scan else None,
        qd_value=options_data.get("iodepth") if is_qd_scan else None,
    )

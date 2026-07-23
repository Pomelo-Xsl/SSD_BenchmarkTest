"""任务生命周期编排。"""
from __future__ import annotations
import logging
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.database.session import SessionLocal
from app.models import Device, Result, Task
from app.parsers.fio_parser import FioParser
from app.services.fio_service import FioOptions, FioService, TESTS
from app.services.safety_service import SafetyService

logger = logging.getLogger(__name__)


class TaskService:
    @staticmethod
    def create(
        db: Session, device_name: str, test_name: str, confirm_destructive: bool, fio_options: dict | None = None,
    ) -> Task:
        device = db.get(Device, device_name)
        if not device:
            raise LookupError("设备不存在，请先调用 GET /api/devices 扫描设备")
        if test_name not in TESTS:
            raise ValueError("不支持的测试类型")
        options = FioOptions.from_mapping(fio_options)
        if TaskService._is_destructive(test_name, options) and not confirm_destructive:
            raise ValueError("写入测试会破坏设备数据，必须将 confirm_destructive 设为 true")
        task = Task(device_name=device_name, test_name=test_name, status="queued", fio_options=json.dumps(options.as_dict()))
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def _is_destructive(test_name: str, options: FioOptions) -> bool:
        """仅纯 read/randread 属于只读；自定义 rw 的其他模式均按破坏性处理。"""
        rw = str(options.extra_options.get("rw", TESTS[test_name][0])).lower()
        return rw not in {"read", "randread"}

    @staticmethod
    def progress(task: Task, now: datetime | None = None) -> tuple[int, str, int, int]:
        """根据任务开始时间与 fio 配置估算可展示的实时进度。"""
        options = FioOptions.from_mapping(json.loads(task.fio_options or "{}"))
        total = options.runtime_seconds + options.ramp_time_seconds
        if task.status == "completed":
            return 100, "已完成", total, total
        if task.status == "failed":
            return 0, "执行失败", 0, total
        if task.status == "queued" or task.started_at is None:
            return 0, "排队中", 0, total
        started_at = task.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        current_time = now or datetime.now(timezone.utc)
        elapsed = max(0, min(total, int((current_time - started_at).total_seconds())))
        percent = min(99, int(elapsed / total * 100)) if total else 0
        phase = "预热中" if elapsed < options.ramp_time_seconds else "正式测试中"
        return percent, phase, elapsed, total

    @staticmethod
    def execute(task_id: int) -> None:
        """后台执行测试并可靠记录失败状态。"""
        db = SessionLocal()
        try:
            task = db.get(Task, task_id)
            if not task:
                return
            device = db.get(Device, task.device_name)
            if not device:
                raise RuntimeError("任务对应设备不存在")
            task.status, task.started_at = "running", datetime.now(timezone.utc)
            db.commit()
            SafetyService.check(device.path)
            options = FioOptions.from_mapping(json.loads(task.fio_options or "{}"))
            run = FioService.run(task.id, device.path, task.test_name, options)
            parsed = FioParser.parse(run.json_path)
            db.add(Result(task_id=task.id, **parsed.__dict__))
            task.status, task.fio_json_path, task.completed_at = "completed", str(run.json_path), datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:
            logger.exception("任务 %s 失败", task_id)
            if task := db.get(Task, task_id):
                task.status, task.error_message, task.completed_at = "failed", str(exc), datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

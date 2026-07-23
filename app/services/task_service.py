"""任务生命周期编排。"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.database.session import SessionLocal
from app.models import Device, Result, Task
from app.parsers.fio_parser import FioParser
from app.services.fio_service import FioService, TESTS
from app.services.safety_service import SafetyService

logger = logging.getLogger(__name__)


class TaskService:
    @staticmethod
    def create(db: Session, device_name: str, test_name: str, confirm_destructive: bool) -> Task:
        device = db.get(Device, device_name)
        if not device:
            raise LookupError("设备不存在，请先调用 GET /api/devices 扫描设备")
        if test_name not in TESTS:
            raise ValueError("不支持的测试类型")
        if "write" in test_name and not confirm_destructive:
            raise ValueError("写入测试会破坏设备数据，必须将 confirm_destructive 设为 true")
        task = Task(device_name=device_name, test_name=test_name, status="queued")
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

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
            run = FioService.run(task.id, device.path, task.test_name)
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

"""批量 fio 任务：同一块盘上的测试必须串行，避免互相影响结果。"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models import Device, Task, TestBatch
from app.services.task_service import TaskService


class BatchService:
    @staticmethod
    def create(db: Session, device_name: str, tests: list[dict]) -> tuple[TestBatch, list[Task]]:
        if not db.get(Device, device_name):
            raise LookupError("设备不存在，请先调用 GET /api/devices 扫描设备")
        batch = TestBatch(device_name=device_name, status="queued")
        db.add(batch)
        db.commit()
        db.refresh(batch)
        tasks = []
        try:
            for item in tests:
                tasks.append(TaskService.create(
                    db, device_name=device_name, test_name=item["test_name"],
                    confirm_destructive=item.get("confirm_destructive", False),
                    fio_options=item.get("fio_options"), batch_id=batch.id,
                ))
        except Exception:
            for task in tasks:
                db.delete(task)
            db.delete(batch)
            db.commit()
            raise
        return batch, tasks

    @staticmethod
    def execute(batch_id: int) -> None:
        """在一个后台工作流中顺序运行；任一项失败即停止余下项目。"""
        db = SessionLocal()
        try:
            batch = db.get(TestBatch, batch_id)
            if not batch:
                return
            batch.status, batch.started_at = "running", datetime.now(timezone.utc)
            db.commit()
            task_ids = [task_id for (task_id,) in db.query(Task.id).filter(Task.batch_id == batch_id).order_by(Task.id)]
            for task_id in task_ids:
                TaskService.execute(task_id)
                db.expire_all()
                task = db.get(Task, task_id)
                if not task or task.status != "completed":
                    batch = db.get(TestBatch, batch_id)
                    if batch:
                        batch.status = "failed"
                        batch.error_message = task.error_message if task else "批量任务中的子任务不存在"
                        batch.completed_at = datetime.now(timezone.utc)
                        db.commit()
                    return
            batch = db.get(TestBatch, batch_id)
            if batch:
                batch.status, batch.completed_at = "completed", datetime.now(timezone.utc)
                db.commit()
        except Exception as exc:
            batch = db.get(TestBatch, batch_id)
            if batch:
                batch.status, batch.error_message, batch.completed_at = "failed", str(exc), datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

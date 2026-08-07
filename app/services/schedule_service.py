"""无需外部依赖的持久化测试计划调度器。"""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy.orm import Session
from app.database.session import SessionLocal
from app.models import PlanRun, ScheduledPlan, TestBatch
from app.services.batch_service import BatchService

logger = logging.getLogger(__name__)

class ScheduleService:
    MIN_INTERVAL_MINUTES = 1
    MAX_INTERVAL_MINUTES = 43200

    @staticmethod
    def utcnow() -> datetime: return datetime.now(timezone.utc)

    @classmethod
    def validate(cls, name: str, interval_minutes: int, tests: list[dict[str,Any]]) -> None:
        if not name or not name.strip(): raise ValueError("计划名称不能为空")
        if not cls.MIN_INTERVAL_MINUTES <= int(interval_minutes) <= cls.MAX_INTERVAL_MINUTES: raise ValueError("周期必须为 1 到 43200 分钟")
        if not tests or len(tests)>32: raise ValueError("计划至少包含 1 个且最多包含 32 个测试项")
        for item in tests:
            if not item.get("test_name"): raise ValueError("每个计划测试项必须包含 test_name")

    @classmethod
    def create(cls, db: Session, name: str, device_name: str, interval_minutes: int, tests: list[dict[str,Any]]) -> ScheduledPlan:
        cls.validate(name,interval_minutes,tests)
        if db.query(ScheduledPlan).filter(ScheduledPlan.name==name.strip()).first(): raise ValueError("计划名称已存在")
        plan=ScheduledPlan(name=name.strip(),device_name=device_name,tests_json=json.dumps(tests,ensure_ascii=False),interval_minutes=int(interval_minutes),next_run_at=cls.utcnow()+timedelta(minutes=int(interval_minutes)))
        db.add(plan);db.commit();db.refresh(plan);return plan

    @staticmethod
    def tests(plan: ScheduledPlan) -> list[dict[str,Any]]:
        try: return json.loads(plan.tests_json or "[]")
        except json.JSONDecodeError: return []

    @classmethod
    def serialize(cls, plan: ScheduledPlan) -> dict[str,Any]:
        return {"id":plan.id,"name":plan.name,"device_name":plan.device_name,"tests":cls.tests(plan),"interval_minutes":plan.interval_minutes,"enabled":plan.enabled,"next_run_at":plan.next_run_at,"last_run_at":plan.last_run_at,"last_batch_id":plan.last_batch_id,"last_error":plan.last_error,"created_at":plan.created_at,"updated_at":plan.updated_at}

    @classmethod
    def due_plans(cls, db: Session, now: datetime | None = None) -> list[ScheduledPlan]:
        now=now or cls.utcnow()
        return db.query(ScheduledPlan).filter(ScheduledPlan.enabled.is_(True),ScheduledPlan.next_run_at <= now).order_by(ScheduledPlan.next_run_at).all()

    @classmethod
    def trigger(cls, db: Session, plan: ScheduledPlan, now: datetime | None = None) -> PlanRun:
        now=now or cls.utcnow(); run=PlanRun(plan_id=plan.id,status="running",scheduled_for=plan.next_run_at or now)
        db.add(run);db.commit();db.refresh(run)
        try:
            # 若上一个批次未结束，保留计划但本轮标为 skipped，避免同一设备并发测试。
            if plan.last_batch_id:
                batch=db.get(TestBatch,plan.last_batch_id)
                if batch and batch.status in {"queued","running"}:
                    run.status="skipped";run.message="上一轮计划测试仍在执行，已跳过本轮。";return run
            batch,tasks=BatchService.create(db,plan.device_name,cls.tests(plan))
            plan.last_batch_id=batch.id;plan.last_run_at=now;plan.last_error=None;run.batch_id=batch.id;run.status="created";run.message=f"已创建批量任务 #{batch.id}，共 {len(tasks)} 项。"
            return run
        except Exception as exc:
            plan.last_run_at=now;plan.last_error=str(exc);run.status="failed";run.message=str(exc);return run
        finally:
            plan.next_run_at=now+timedelta(minutes=plan.interval_minutes);db.commit();db.refresh(run)

    @classmethod
    def tick(cls) -> list[tuple[int,int]]:
        """执行一次调度检查，返回新创建的计划/批次 ID；执行 fio 工作流由调用方安排。"""
        db=SessionLocal();created=[]
        try:
            for plan in cls.due_plans(db):
                run=cls.trigger(db,plan)
                if run.status=="created" and run.batch_id: created.append((plan.id,run.batch_id))
            return created
        finally: db.close()

    @classmethod
    async def worker(cls, stop: asyncio.Event, interval_seconds: int=15) -> None:
        """生命周期后台协程；异常隔离，单次调度失败不会停止服务。"""
        while not stop.is_set():
            try:
                for _, batch_id in cls.tick():
                    asyncio.create_task(asyncio.to_thread(BatchService.execute, batch_id))
            except Exception: logger.exception("定时计划调度检查失败")
            try: await asyncio.wait_for(stop.wait(),timeout=max(1,interval_seconds))
            except asyncio.TimeoutError: pass

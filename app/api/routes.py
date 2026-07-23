"""REST API 路由，仅负责输入输出和 HTTP 错误映射。"""
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.core.config import settings
from app.models import Device, Result, Task
from app.schemas.schemas import DeviceOut, TaskCreate, TestCreated, TestResult
from app.services.device_service import DeviceService
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(db: Session = Depends(get_db)) -> list[dict]:
    """扫描并返回当前检测到的 NVMe SSD。"""
    try:
        return DeviceService.scan_devices(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/tests", response_model=TestCreated, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> Task:
    """创建任务后异步执行，立即返回任务 ID。"""
    try:
        device_name = payload.device_name or settings.default_device_name
        if not device_name:
            raise ValueError("未指定设备；请传入 device_name 或设置 SSD_BENCHMARK_DEFAULT_DEVICE_NAME")
        task = TaskService.create(db, device_name=device_name, test_name=payload.test_name,
                                  confirm_destructive=payload.confirm_destructive)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(TaskService.execute, task.id)
    return task


@router.get("/results/{task_id}", response_model=TestResult)
def get_result(task_id: int, db: Session = Depends(get_db)) -> TestResult:
    """查询测试状态；完成时同时返回性能结果，失败时返回错误。"""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="测试不存在")
    result = db.query(Result).filter(Result.task_id == task_id).first()
    metrics = None
    if result:
        metrics = {
            "iops": result.iops,
            "bw_mib_s": result.bw_mib_s,
            "latency_avg_us": result.latency_avg_us,
            "latency_p99_us": result.latency_p99_us,
            "cpu_user_pct": result.cpu_user_pct,
            "cpu_system_pct": result.cpu_system_pct,
        }
    return TestResult(task_id=task.id, status=task.status, error_message=task.error_message, result=metrics)

"""REST API 路由，仅负责输入输出和 HTTP 错误映射。"""
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.models import Device, Result, Task
from app.schemas.schemas import DeviceOut, ResultOut, TaskCreate, TaskOut
from app.services.device_service import DeviceService
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(db: Session = Depends(get_db)) -> list[Device]:
    """扫描并返回当前检测到的 NVMe SSD。"""
    try:
        return DeviceService.scan_devices(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/devices/{name}", response_model=DeviceOut)
def get_device(name: str, db: Session = Depends(get_db)) -> Device:
    device = db.get(Device, name)
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在；请先扫描")
    return device


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> Task:
    """创建任务后异步执行，立即返回任务 ID。"""
    try:
        task = TaskService.create(db, **payload.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(TaskService.execute, task.id)
    return task


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(get_db)) -> list[Task]:
    return list(db.scalars(select(Task).order_by(Task.id.desc())))


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)) -> Task:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/results/{task_id}", response_model=ResultOut)
def get_result(task_id: int, db: Session = Depends(get_db)) -> Result:
    result = db.scalar(select(Result).where(Result.task_id == task_id))
    if not result:
        raise HTTPException(status_code=404, detail="该任务尚无结果")
    return result

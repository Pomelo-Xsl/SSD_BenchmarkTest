"""REST API 路由，仅负责输入输出和 HTTP 错误映射。"""
import logging
import json
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.core.config import settings
from app.models import Device, Result, Task, TestBatch
from app.schemas.schemas import BatchCreate, BatchCreated, BatchResult, BatchTaskOut, DeviceOut, TaskCreate, TaskListItem, TestCreated, TestResult
from app.services.batch_service import BatchService
from app.services.device_service import DeviceService
from app.services.fio_service import FioOptions, FioService
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
        task = TaskService.create(
            db, device_name=device_name, test_name=payload.test_name,
            confirm_destructive=payload.confirm_destructive,
            fio_options=payload.fio_options.model_dump(exclude_none=True) if payload.fio_options else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    return [
        TaskListItem(
            id=task.id, device_name=task.device_name, test_name=task.test_name, status=task.status,
            created_at=task.created_at, progress_percent=TaskService.progress(task)[0],
            progress_phase=TaskService.progress(task)[1],
        )
        for task in tasks
    ]


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
    options_data = json.loads(task.fio_options or "{}")
    device = db.get(Device, task.device_name)
    if not device:
        raise HTTPException(status_code=404, detail="任务对应设备不存在")
    fio_command = FioService.build_command(
        device.path, task.test_name, settings.results_dir / f"task_{task.id}.json",
        FioOptions.from_mapping(options_data),
    )
    progress_percent, progress_phase, elapsed_seconds, total_seconds = TaskService.progress(task)
    return TestResult(
        task_id=task.id, device_name=task.device_name, device_path=device.path,
        test_name=task.test_name, fio_command=fio_command, status=task.status,
        error_message=task.error_message, fio_options=options_data, progress_percent=progress_percent,
        progress_phase=progress_phase, elapsed_seconds=elapsed_seconds, total_seconds=total_seconds,
        result=metrics,
    )

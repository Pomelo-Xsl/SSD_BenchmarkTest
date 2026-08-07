"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager
import asyncio
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from app.api.routes import router
from app.core.config import ensure_runtime_directories
from app.core.logging import configure_logging
from app.database.base import Base
from app.database.session import engine
from app.services.schedule_service import ScheduleService
import app.models  # noqa: F401，确保模型注册到 Base.metadata


def migrate_sqlite_schema() -> None:
    """为已有 MVP 数据库补齐新增字段，避免部署时丢失历史任务。"""
    if engine.dialect.name != "sqlite":
        return
    columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    if "fio_options" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN fio_options TEXT"))
    if "batch_id" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN batch_id INTEGER"))
    batch_columns = {column["name"] for column in inspect(engine).get_columns("test_batches")}
    if "batch_type" not in batch_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE test_batches ADD COLUMN batch_type VARCHAR(30) NOT NULL DEFAULT 'batch'"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    ensure_runtime_directories()
    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema()
    stop_scheduler = asyncio.Event()
    scheduler_task = asyncio.create_task(ScheduleService.worker(stop_scheduler))
    try:
        yield
    finally:
        stop_scheduler.set()
        await scheduler_task


app = FastAPI(title="NVMe SSD Benchmark MVP", version="1.0.0", lifespan=lifespan)
app.include_router(router)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """返回功能导航首页。"""
    return FileResponse(static_dir / "index.html")


def _ui_page(filename: str) -> FileResponse:
    return FileResponse(static_dir / filename)


@app.get("/devices", include_in_schema=False)
def devices_page() -> FileResponse:
    return _ui_page("devices.html")


@app.get("/tests", include_in_schema=False)
def tests_page() -> FileResponse:
    return _ui_page("tests.html")


@app.get("/qd-scan", include_in_schema=False)
def qd_scan_page() -> FileResponse:
    return _ui_page("qd_scan.html")


@app.get("/advanced", include_in_schema=False)
def advanced_page() -> FileResponse:
    """返回高级测试与运维功能入口。"""
    return _ui_page("advanced.html")


@app.get("/health-logs", include_in_schema=False)
def health_logs_page() -> FileResponse:
    return _ui_page("health_logs.html")


@app.get("/comparison", include_in_schema=False)
def comparison_page() -> FileResponse:
    return _ui_page("comparison.html")


@app.get("/operations", include_in_schema=False)
def operations_page() -> FileResponse:
    return _ui_page("operations.html")


@app.get("/queue", include_in_schema=False)
def queue_page() -> FileResponse:
    return _ui_page("queue.html")


@app.get("/tasks", include_in_schema=False)
def task_list_page() -> FileResponse:
    return _ui_page("tasks.html")


@app.get("/results", include_in_schema=False)
def results_page() -> FileResponse:
    return _ui_page("results.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

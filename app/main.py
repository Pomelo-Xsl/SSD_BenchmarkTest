"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager
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
import app.models  # noqa: F401，确保模型注册到 Base.metadata


def migrate_sqlite_schema() -> None:
    """为已有 MVP 数据库补齐新增字段，避免部署时丢失历史任务。"""
    if engine.dialect.name != "sqlite":
        return
    columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    if "fio_options" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN fio_options TEXT"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    ensure_runtime_directories()
    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema()
    yield


app = FastAPI(title="NVMe SSD Benchmark MVP", version="1.0.0", lifespan=lifespan)
app.include_router(router)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """返回面向非技术用户的测试操作界面。"""
    return FileResponse(static_dir / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

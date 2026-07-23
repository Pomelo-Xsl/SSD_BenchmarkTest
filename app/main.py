"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

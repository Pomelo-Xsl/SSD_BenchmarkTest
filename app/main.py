"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.routes import router
from app.core.config import ensure_runtime_directories
from app.core.logging import configure_logging
from app.database.base import Base
from app.database.session import engine
import app.models  # noqa: F401，确保模型注册到 Base.metadata


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    ensure_runtime_directories()
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="NVMe SSD Benchmark MVP", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

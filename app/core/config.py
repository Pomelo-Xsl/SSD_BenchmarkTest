"""应用配置。所有可变路径与参数均由环境变量管理。"""
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行期配置。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="SSD_BENCHMARK_", extra="ignore")
    database_url: str = "sqlite:///./benchmark.db"
    logs_dir: Path = Path("logs")
    results_dir: Path = Path("results")
    runtime_seconds: int = 60
    ramp_time_seconds: int = 10
    default_device_name: Optional[str] = None


settings = Settings()


def ensure_runtime_directories() -> None:
    """创建运行所需目录。"""
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.results_dir.mkdir(parents=True, exist_ok=True)

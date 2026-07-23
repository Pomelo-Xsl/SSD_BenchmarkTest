"""集中配置应用与 fio 日志。"""
import logging
from logging.handlers import RotatingFileHandler
from app.core.config import ensure_runtime_directories, settings


def configure_logging() -> None:
    """配置控制台、应用、错误与 fio 四类日志输出。"""
    ensure_runtime_directories()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    for filename, level in (("app.log", logging.INFO), ("error.log", logging.ERROR)):
        handler = RotatingFileHandler(settings.logs_dir / filename, maxBytes=2_000_000, backupCount=3)
        handler.setLevel(level)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

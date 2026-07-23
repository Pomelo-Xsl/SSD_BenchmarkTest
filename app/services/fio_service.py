"""fio 命令的唯一构建和执行入口。"""
from __future__ import annotations
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from app.core.config import settings

logger = logging.getLogger(__name__)

TESTS = {
    "seq_read_128k": ("read", "128k"),
    "seq_write_128k": ("write", "128k"),
    "rand_read_4k": ("randread", "4k"),
    "rand_write_4k": ("randwrite", "4k"),
}


@dataclass(frozen=True)
class FioRun:
    json_path: Path
    log_path: Path
    return_code: int


class FioService:
    """构建 fio 参数、执行测试，并保存完整 JSON 与日志。"""

    @staticmethod
    def build_command(device_path: str, test_name: str, output_path: Path) -> list[str]:
        try:
            rw, block_size = TESTS[test_name]
        except KeyError as exc:
            raise ValueError(f"不支持的测试类型: {test_name}") from exc
        return [
            "fio", f"--name={test_name}", f"--filename={device_path}", f"--rw={rw}", f"--bs={block_size}",
            "--ioengine=io_uring", "--direct=1", "--numjobs=1", "--iodepth=32",
            f"--runtime={settings.runtime_seconds}", f"--ramp_time={settings.ramp_time_seconds}", "--time_based",
            "--group_reporting", "--output-format=json+", f"--output={output_path}",
        ]

    @classmethod
    def run(cls, task_id: int, device_path: str, test_name: str) -> FioRun:
        """运行 fio。退出失败仍保留输出与日志，便于诊断。"""
        settings.results_dir.mkdir(parents=True, exist_ok=True)
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        json_path = settings.results_dir / f"task_{task_id}.json"
        log_path = settings.logs_dir / "fio.log"
        command = cls.build_command(device_path, test_name, json_path)
        logger.info("开始 fio 任务 %s，命令: %s", task_id, " ".join(command))
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=settings.runtime_seconds + settings.ramp_time_seconds + 120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            log_path.write_text(f"任务 {task_id} 执行异常: {exc}\n", encoding="utf-8")
            raise RuntimeError(f"fio 执行异常: {exc}") from exc
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n--- task {task_id}: {' '.join(command)} ---\n{completed.stdout}\n{completed.stderr}\n")
        if completed.returncode != 0:
            raise RuntimeError(f"fio 退出码 {completed.returncode}: {completed.stderr[-1000:]}")
        if not json_path.exists():
            raise RuntimeError("fio 未生成 JSON 输出")
        # 验证输出是合法 JSON，避免后续写入无效结果。
        json.loads(json_path.read_text(encoding="utf-8"))
        return FioRun(json_path=json_path, log_path=log_path, return_code=completed.returncode)

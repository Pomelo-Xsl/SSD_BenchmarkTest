"""fio 命令的唯一构建和执行入口。"""
from __future__ import annotations
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
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


@dataclass(frozen=True)
class FioOptions:
    """允许用户按任务调整的 fio 参数，已限制为安全的白名单。"""

    runtime_seconds: int
    ramp_time_seconds: int
    iodepth: int
    numjobs: int
    ioengine: str
    direct: bool
    extra_options: dict[str, Any]

    _STANDARD_OPTIONS = {"runtime_seconds", "ramp_time_seconds", "iodepth", "numjobs", "ioengine", "direct"}
    _PROTECTED_OPTIONS = {
        "name", "filename", "output", "output-format", "output_format", "time_based", "time-based",
        "exec_prerun", "exec_postrun", "prerun", "postrun",
    }

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None) -> "FioOptions":
        values = values or {}
        extra_options: dict[str, Any] = {}
        for key, value in values.items():
            if key in cls._STANDARD_OPTIONS:
                continue
            if key in cls._PROTECTED_OPTIONS or key.startswith("exec_"):
                raise ValueError(f"fio 参数 {key} 由系统保护，不能覆盖")
            if not key.replace("_", "").replace("-", "").isalnum() or not key[:1].isalpha():
                raise ValueError(f"无效的 fio 参数名称: {key}")
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError(f"fio 参数 {key} 仅支持字符串、数字或布尔值")
            extra_options[key] = value
        return cls(
            runtime_seconds=int(values.get("runtime_seconds", settings.runtime_seconds)),
            ramp_time_seconds=int(values.get("ramp_time_seconds", settings.ramp_time_seconds)),
            iodepth=int(values.get("iodepth", 32)),
            numjobs=int(values.get("numjobs", 1)),
            ioengine=str(values.get("ioengine", "io_uring")),
            direct=bool(values.get("direct", True)),
            extra_options=extra_options,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "runtime_seconds": self.runtime_seconds,
            "ramp_time_seconds": self.ramp_time_seconds,
            "iodepth": self.iodepth,
            "numjobs": self.numjobs,
            "ioengine": self.ioengine,
            "direct": self.direct,
            **self.extra_options,
        }


class FioService:
    """构建 fio 参数、执行测试，并保存完整 JSON 与日志。"""

    @staticmethod
    def build_command(device_path: str, test_name: str, output_path: Path, options: FioOptions) -> list[str]:
        try:
            rw, block_size = TESTS[test_name]
        except KeyError as exc:
            raise ValueError(f"不支持的测试类型: {test_name}") from exc
        command = [
            "fio", f"--name={test_name}", f"--filename={device_path}", f"--rw={rw}", f"--bs={block_size}",
            f"--ioengine={options.ioengine}", f"--direct={int(options.direct)}", f"--numjobs={options.numjobs}",
            f"--iodepth={options.iodepth}", f"--runtime={options.runtime_seconds}",
            f"--ramp_time={options.ramp_time_seconds}", "--time_based",
            "--group_reporting", "--output-format=json+", f"--output={output_path}",
        ]
        # 追加项位于默认测试模板之后，因此 fio 会采用用户为本次任务指定的覆盖值。
        for key, value in options.extra_options.items():
            formatted_value = int(value) if isinstance(value, bool) else value
            command.append(f"--{key}={formatted_value}")
        return command

    @classmethod
    def run(cls, task_id: int, device_path: str, test_name: str, options: FioOptions) -> FioRun:
        """运行 fio。退出失败仍保留输出与日志，便于诊断。"""
        settings.results_dir.mkdir(parents=True, exist_ok=True)
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        json_path = settings.results_dir / f"task_{task_id}.json"
        log_path = settings.logs_dir / "fio.log"
        command = cls.build_command(device_path, test_name, json_path, options)
        logger.info("开始 fio 任务 %s，命令: %s", task_id, " ".join(command))
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True,
                timeout=options.runtime_seconds + options.ramp_time_seconds + 120,
            )
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

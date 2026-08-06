"""受控的 NVMe format 命令执行服务。"""
from __future__ import annotations

import subprocess


class NvmeFormatService:
    """只执行系统固定的 NVMe format 参数，禁止前端传入额外命令参数。"""

    COMMAND_OPTIONS = ("-s", "0", "-l", "0", "-i", "0", "-p", "0", "-m", "1", "-f")

    @classmethod
    def build_command(cls, device_path: str) -> list[str]:
        return ["nvme", "format", device_path, *cls.COMMAND_OPTIONS]

    @classmethod
    def run(cls, device_path: str) -> tuple[list[str], str]:
        command = cls.build_command(device_path)
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
        output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
        return command, output or "NVMe format 已完成。"

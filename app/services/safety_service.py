"""所有 fio 执行前的不可绕过安全校验。"""
from __future__ import annotations
import json
import os
import shutil
import subprocess


class SafetyService:
    """防止在挂载盘、系统盘或非 NVMe 设备上执行测试。"""

    @staticmethod
    def check(device_path: str) -> None:
        errors: list[str] = []
        if os.geteuid() != 0:
            errors.append("需要 root 权限")
        if not os.path.exists(device_path):
            errors.append("设备不存在")
        if not os.path.basename(device_path).startswith("nvme"):
            errors.append("目标不是 NVMe 设备")
        for command in ("fio", "nvme", "lsblk"):
            if not shutil.which(command):
                errors.append(f"未安装 {command}")
        if not errors:
            errors.extend(SafetyService._block_device_errors(device_path))
        if errors:
            raise ValueError("; ".join(errors))

    @staticmethod
    def _block_device_errors(device_path: str) -> list[str]:
        try:
            raw = subprocess.run(["lsblk", "--json", "-o", "PATH,MOUNTPOINTS,PKNAME"], check=True, capture_output=True, text=True, timeout=10)
            nodes = json.loads(raw.stdout).get("blockdevices", [])
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            return [f"无法验证挂载状态: {exc}"]
        target = os.path.realpath(device_path)
        found = False
        mounted = False
        system_disk = False
        try:
            root_command = subprocess.run(
                ["findmnt", "-n", "-o", "SOURCE", "/"], check=True, capture_output=True, text=True, timeout=10
            )
            root_source = os.path.realpath(root_command.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            # 无法识别系统根设备时拒绝测试，而不是冒险继续。
            return ["无法识别系统根设备"]

        def walk(items: list[dict], parent_path: str | None = None) -> None:
            nonlocal found, mounted, system_disk
            for item in items:
                path = item.get("path")
                root_path = parent_path or path
                if path and os.path.realpath(path) == target:
                    found = True
                if root_path and os.path.realpath(root_path) == target:
                    if item.get("mountpoints") and any(item["mountpoints"]):
                        mounted = True
                    if root_source and (os.path.realpath(path or "") == root_source or os.path.realpath(root_path) == root_source):
                        system_disk = True
                walk(item.get("children", []), root_path)
        walk(nodes)
        errors = []
        if not found:
            errors.append("设备未被 lsblk 识别")
        if mounted:
            errors.append("设备或其分区已挂载")
        if system_disk:
            errors.append("目标是系统盘")
        return errors

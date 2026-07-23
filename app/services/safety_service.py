"""所有 fio 执行前的不可绕过安全校验。"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceSafetyStatus:
    """供 API 展示和执行前校验共用的设备安全状态。"""

    mounted: bool
    system_disk: bool
    has_partitions: bool
    safe_to_test: bool
    safety_message: str | None


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
            safety = SafetyService.inspect_device(device_path)
            if not safety.safe_to_test and safety.safety_message:
                errors.extend(safety.safety_message.split("；"))
        if errors:
            raise ValueError("; ".join(errors))

    @staticmethod
    def inspect_device(device_path: str) -> DeviceSafetyStatus:
        """读取系统块设备树，并判断指定整盘是否适合作为测试盘。"""
        try:
            raw = subprocess.run(
                ["lsblk", "--json", "-o", "PATH,TYPE,MOUNTPOINTS"], check=True, capture_output=True, text=True, timeout=10
            )
            nodes = json.loads(raw.stdout).get("blockdevices", [])
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            return DeviceSafetyStatus(False, False, False, False, f"无法验证设备状态: {exc}")
        root_source = SafetyService.root_source()
        return SafetyService.inspect_nodes(nodes, device_path, root_source)

    @staticmethod
    def root_source() -> str | None:
        """获取根文件系统来源；未知时拒绝执行高风险测试。"""
        try:
            root_command = subprocess.run(
                ["findmnt", "-n", "-o", "SOURCE", "/"], check=True, capture_output=True, text=True, timeout=10
            )
            return os.path.realpath(root_command.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            return None

    @staticmethod
    def inspect_nodes(nodes: list[dict], device_path: str, root_source: str | None) -> DeviceSafetyStatus:
        """基于已读取的 lsblk 树计算安全状态，避免扫描接口重复调用 lsblk。"""
        target = os.path.realpath(device_path)
        target_node: dict | None = None

        def find(items: list[dict]) -> None:
            nonlocal target_node
            for item in items:
                path = item.get("path")
                if path and os.path.realpath(path) == target:
                    target_node = item
                    return
                find(item.get("children", []))
                if target_node:
                    return

        find(nodes)
        if not target_node:
            return DeviceSafetyStatus(False, False, False, False, "设备未被 lsblk 识别")

        mounted = False
        system_disk = False
        has_partitions = False

        def inspect_subtree(item: dict, is_root: bool = False) -> None:
            nonlocal mounted, system_disk, has_partitions
            path = item.get("path")
            if item.get("mountpoints") and any(item["mountpoints"]):
                mounted = True
            if root_source and path and os.path.realpath(path) == root_source:
                system_disk = True
            if not is_root and item.get("type") == "part":
                has_partitions = True
            for child in item.get("children", []):
                inspect_subtree(child)

        inspect_subtree(target_node, is_root=True)
        errors: list[str] = []
        if mounted:
            errors.append("设备或其分区已挂载")
        if system_disk:
            errors.append("目标是系统盘")
        if has_partitions:
            errors.append("设备含有现有分区")
        if root_source is None:
            errors.append("无法识别系统根设备")
        return DeviceSafetyStatus(mounted, system_disk, has_partitions, not errors, "；".join(errors) or None)

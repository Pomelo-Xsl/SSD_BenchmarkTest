"""NVMe 设备发现及信息收集。"""
from __future__ import annotations
import json
import logging
import shutil
import subprocess
from sqlalchemy.orm import Session
from app.models import Device

logger = logging.getLogger(__name__)


class DeviceService:
    """通过 lsblk 与 nvme-cli 读取设备元数据。"""

    @staticmethod
    def _command_json(command: list[str]) -> dict:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
        return json.loads(completed.stdout)

    @classmethod
    def scan_devices(cls, db: Session) -> list[Device]:
        """扫描块设备；nvme-cli 不存在时仍返回 lsblk 中的基础信息。"""
        try:
            data = cls._command_json(["lsblk", "--json", "--bytes", "-o", "NAME,PATH,TYPE,SIZE,MODEL,SERIAL,MOUNTPOINTS"])
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            logger.exception("扫描 lsblk 失败")
            raise RuntimeError(f"无法扫描设备: {exc}") from exc
        devices: list[Device] = []
        for item in data.get("blockdevices", []):
            name = str(item.get("name", ""))
            if item.get("type") != "disk" or not name.startswith("nvme"):
                continue
            firmware, temperature = cls._nvme_details(str(item.get("path", "")))
            device = db.get(Device, name) or Device(name=name, path=str(item["path"]))
            device.path = str(item["path"])
            device.model = item.get("model")
            device.serial = item.get("serial")
            device.size_bytes = int(item["size"]) if item.get("size") is not None else None
            device.firmware, device.temperature_c = firmware, temperature
            db.add(device)
            devices.append(device)
        db.commit()
        for device in devices:
            db.refresh(device)
        return devices

    @staticmethod
    def _nvme_details(path: str) -> tuple[str | None, float | None]:
        if not shutil.which("nvme"):
            return None, None
        try:
            info = DeviceService._command_json(["nvme", "id-ctrl", path, "-o", "json"])
            smart = DeviceService._command_json(["nvme", "smart-log", path, "-o", "json"])
            temperature = smart.get("temperature")
            # nvme-cli JSON 通常以摄氏温度提供；保留其原始单位。
            return info.get("fr"), float(temperature) if temperature is not None else None
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
            logger.warning("读取 %s 的 NVMe 详情失败", path, exc_info=True)
            return None, None

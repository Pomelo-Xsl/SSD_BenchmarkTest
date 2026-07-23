"""NVMe 设备发现及信息收集。"""
from __future__ import annotations
import json
import logging
import shutil
import subprocess
from sqlalchemy.orm import Session
from app.models import Device
from app.services.safety_service import SafetyService

logger = logging.getLogger(__name__)


class DeviceService:
    """通过 lsblk 与 nvme-cli 读取设备元数据。"""

    @staticmethod
    def _command_json(command: list[str]) -> dict:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
        return json.loads(completed.stdout)

    @classmethod
    def scan_devices(cls, db: Session) -> list[dict]:
        """扫描块设备；nvme-cli 不存在时仍返回 lsblk 中的基础信息。"""
        try:
            data = cls._command_json(["lsblk", "--json", "--bytes", "-o", "NAME,PATH,TYPE,SIZE,MODEL,SERIAL,MOUNTPOINTS"])
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            logger.exception("扫描 lsblk 失败")
            raise RuntimeError(f"无法扫描设备: {exc}") from exc
        devices: list[Device] = []
        root_source = SafetyService.root_source()
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
        response: list[dict] = []
        for device in devices:
            db.refresh(device)
            safety = SafetyService.inspect_nodes(data.get("blockdevices", []), device.path, root_source)
            response.append({
                "name": device.name,
                "path": device.path,
                "model": device.model,
                "serial": device.serial,
                "size_bytes": device.size_bytes,
                "firmware": device.firmware,
                "temperature_c": device.temperature_c,
                "scanned_at": device.scanned_at,
                "mounted": safety.mounted,
                "system_disk": safety.system_disk,
                "has_partitions": safety.has_partitions,
                "safe_to_test": safety.safe_to_test,
                "safety_message": safety.safety_message,
            })
        return response

    @staticmethod
    def _nvme_details(path: str) -> tuple[str | None, float | None]:
        if not shutil.which("nvme"):
            return None, None
        try:
            info = DeviceService._command_json(["nvme", "id-ctrl", path, "-o", "json"])
            smart = DeviceService._command_json(["nvme", "smart-log", path, "-o", "json"])
            temperature = smart.get("temperature")
            temperature_value = float(temperature) if temperature is not None else None
            # NVMe SMART 标准温度单位为开尔文；兼容部分工具已返回摄氏温度的情况。
            if temperature_value is not None and temperature_value > 200:
                temperature_value -= 273.15
            return info.get("fr"), temperature_value
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
            logger.warning("读取 %s 的 NVMe 详情失败", path, exc_info=True)
            return None, None

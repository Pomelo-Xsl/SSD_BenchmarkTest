"""NVMe 设备发现及信息收集。"""
from __future__ import annotations
import json
import logging
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.orm import Session
from app.models import Device
from app.services.safety_service import SafetyService

logger = logging.getLogger(__name__)


class DeviceService:
    """通过 lsblk 与 nvme-cli 读取设备元数据。"""

    @staticmethod
    def _command_json(command: list[str], timeout: int = 15) -> dict:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
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
        nvme_items = [
            item for item in data.get("blockdevices", [])
            if item.get("type") == "disk" and str(item.get("name", "")).startswith("nvme")
        ]
        # SMART 与固件查询可能被个别控制器拖慢；并行执行并将每条命令限制为 3 秒。
        details = cls._nvme_details_for_paths([str(item.get("path", "")) for item in nvme_items])
        for item in nvme_items:
            name = str(item.get("name", ""))
            firmware, temperature = details.get(str(item.get("path", "")), (None, None))
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

    @classmethod
    def _nvme_details_for_paths(cls, paths: list[str]) -> dict[str, tuple[str | None, float | None]]:
        """并行读取固件与 SMART；单块异常不会阻塞整个设备扫描。"""
        valid_paths = [path for path in paths if path]
        details = {path: {"firmware": None, "temperature": None} for path in valid_paths}
        if not valid_paths or not shutil.which("nvme"):
            return {path: (None, None) for path in valid_paths}

        futures = {}
        # id-ctrl 与 smart-log 都是独立的 nvme-cli 调用，可同时执行。
        with ThreadPoolExecutor(max_workers=min(8, max(2, len(valid_paths) * 2))) as executor:
            for path in valid_paths:
                futures[executor.submit(cls._command_json, ["nvme", "id-ctrl", path, "-o", "json"], 3)] = (path, "id")
                futures[executor.submit(cls._command_json, ["nvme", "smart-log", path, "-o", "json"], 3)] = (path, "smart")
            for future in as_completed(futures):
                path, kind = futures[future]
                try:
                    payload = future.result()
                    if kind == "id":
                        details[path]["firmware"] = payload.get("fr")
                    else:
                        temperature = payload.get("temperature")
                        value = float(temperature) if temperature is not None else None
                        # NVMe SMART 规范通常以开尔文表示温度。
                        details[path]["temperature"] = value - 273.15 if value is not None and value > 200 else value
                except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
                    logger.warning("读取 %s 的 NVMe %s 信息失败，已跳过详细信息", path, kind)

        return {path: (item["firmware"], item["temperature"]) for path, item in details.items()}

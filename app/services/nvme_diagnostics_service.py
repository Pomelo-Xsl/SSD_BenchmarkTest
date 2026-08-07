"""NVMe SMART、Telemetry 与扩展日志的安全采集、解析和健康分析。"""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import Device, DeviceHealthSnapshot, NvmeLogArchive

@dataclass(frozen=True)
class SmartHealth:
    temperature_c: float | None
    available_spare: float | None
    percentage_used: float | None
    media_errors: int | None
    error_log_entries: int | None
    unsafe_shutdowns: int | None
    power_on_hours: int | None
    health_score: float
    grade: str
    warnings: tuple[str, ...]

@dataclass(frozen=True)
class ThermalTrend:
    samples: int
    minimum_c: float | None
    maximum_c: float | None
    average_c: float | None
    slope_c_per_sample: float | None
    state: str
    advice: str

class NvmeDiagnosticsService:
    LOG_COMMANDS = {
        "telemetry": lambda path, target: ["nvme", "telemetry-log", path, "-o", str(target)],
        "telemetry_critical": lambda path, target: ["nvme", "telemetry-log", path, "-c", "-o", str(target)],
        "extended_smart_c0": lambda path, target: ["nvme", "get-log", path, "-i", "0xC0", "-l", "1024", "-b", "-o", str(target)],
        "extended_smart_ca": lambda path, target: ["nvme", "get-log", path, "-i", "0xCA", "-l", "348", "-b", "-o", str(target)],
    }

    @staticmethod
    def controller_path(device_path: str) -> str:
        """将 Linux NVMe 命名空间路径转换为控制器路径。

        SMART 命令通常可接受 ``/dev/nvmeXnY``，但 telemetry-log 和
        get-log 应发送到控制器 ``/dev/nvmeX``。保留非标准路径，避免对
        其他平台的设备命名做错误猜测。
        """
        match = re.fullmatch(r"(/dev/nvme\d+)n\d+", device_path)
        return match.group(1) if match else device_path

    @staticmethod
    def _number(value: Any) -> float | None:
        if value is None: return None
        if isinstance(value, (int,float)): return float(value)
        match=re.search(r"-?\d+(?:\.\d+)?",str(value))
        return float(match.group()) if match else None

    @classmethod
    def _first(cls, payload: dict[str,Any], *names: str) -> float | None:
        normalized={str(k).lower().replace(" ","_"):v for k,v in payload.items()}
        for name in names:
            if name in normalized:
                return cls._number(normalized[name])
        return None

    @classmethod
    def parse_smart(cls, payload: dict[str, Any]) -> SmartHealth:
        temperature=cls._first(payload,"temperature","temperature_celsius")
        if temperature and temperature>200: temperature=temperature-273
        spare=cls._first(payload,"avail_spare","available_spare")
        used=cls._first(payload,"percent_used","percentage_used")
        media=cls._first(payload,"media_errors","media_and_data_integrity_errors")
        errors=cls._first(payload,"num_err_log_entries","error_log_entries")
        unsafe=cls._first(payload,"unsafe_shutdowns")
        hours=cls._first(payload,"power_on_hours")
        warnings=[]; score=100.0
        if temperature is not None:
            if temperature>=80: warnings.append("盘温达到或超过 80°C，建议立即降载并检查散热。"); score-=35
            elif temperature>=70: warnings.append("盘温偏高（≥70°C），建议检查机箱风道。"); score-=18
            elif temperature>=60: warnings.append("盘温接近高温阈值，建议持续监测。"); score-=7
        if spare is not None and spare<10: warnings.append("可用备用空间低于 10%，设备接近寿命阈值。"); score-=30
        elif spare is not None and spare<20: warnings.append("可用备用空间低于 20%，建议关注磨损趋势。"); score-=12
        if used is not None and used>=100: warnings.append("百分比已用达到 100%，建议尽快替换设备。"); score-=35
        elif used is not None and used>=80: warnings.append("百分比已用达到 80%，建议制定更换计划。"); score-=15
        if media and media>0: warnings.append(f"检测到 {int(media)} 个介质/数据完整性错误。"); score-=min(30,10+media)
        if errors and errors>0: warnings.append(f"错误日志累计 {int(errors)} 条，请结合内核日志复核。"); score-=min(15,errors/10)
        score=max(0.,round(score,2)); grade="A" if score>=90 else "B" if score>=75 else "C" if score>=60 else "D"
        return SmartHealth(temperature,spare,used,int(media) if media is not None else None,int(errors) if errors is not None else None,int(unsafe) if unsafe is not None else None,int(hours) if hours is not None else None,score,grade,tuple(warnings))

    @classmethod
    def collect_smart(cls, device_path: str, timeout: int=10) -> dict[str,Any]:
        command=["nvme","smart-log",device_path,"-o","json"]
        completed=subprocess.run(command,capture_output=True,text=True,timeout=timeout,check=False)
        if completed.returncode: raise RuntimeError(completed.stderr.strip() or "nvme smart-log 执行失败")
        try: return json.loads(completed.stdout)
        except json.JSONDecodeError as exc: raise RuntimeError("nvme smart-log 未返回 JSON 数据") from exc

    @classmethod
    def capture_health(cls, db: Session, device: Device) -> DeviceHealthSnapshot:
        raw=cls.collect_smart(device.path); health=cls.parse_smart(raw)
        item=DeviceHealthSnapshot(device_name=device.name,temperature_c=health.temperature_c,available_spare=health.available_spare,percentage_used=health.percentage_used,media_errors=health.media_errors,error_log_entries=health.error_log_entries,unsafe_shutdowns=health.unsafe_shutdowns,power_on_hours=health.power_on_hours,health_score=health.health_score,raw_json=json.dumps(raw,ensure_ascii=False))
        db.add(item); db.commit(); db.refresh(item); return item

    @staticmethod
    def health_dict(item: DeviceHealthSnapshot) -> dict[str,Any]:
        health=NvmeDiagnosticsService.parse_smart(json.loads(item.raw_json))
        return {"id":item.id,"device_name":item.device_name,"temperature_c":item.temperature_c,"available_spare":item.available_spare,"percentage_used":item.percentage_used,"media_errors":item.media_errors,"error_log_entries":item.error_log_entries,"unsafe_shutdowns":item.unsafe_shutdowns,"power_on_hours":item.power_on_hours,"health_score":item.health_score,"grade":health.grade,"warnings":list(health.warnings),"captured_at":item.captured_at}

    @staticmethod
    def thermal_trend(rows: Iterable[DeviceHealthSnapshot]) -> ThermalTrend:
        values=[float(row.temperature_c) for row in rows if row.temperature_c is not None]
        if not values: return ThermalTrend(0,None,None,None,None,"unknown","暂无温度数据，请先采集 SMART 快照。")
        slope=0.0 if len(values)<2 else (values[-1]-values[0])/(len(values)-1)
        maximum=max(values); average=sum(values)/len(values)
        if maximum>=70: state,advice="hot","检测到高温历史，建议改善散热后再执行长时间压力测试。"
        elif slope>=2: state,advice="rising","温度在连续快照中持续上升，建议缩短测试间隔并监控风扇。"
        else: state,advice="stable","温度趋势稳定。"
        return ThermalTrend(len(values),min(values),maximum,round(average,2),round(slope,3),state,advice)

    @classmethod
    def archive_log(cls, db: Session, device: Device, log_type: str, timeout: int=120) -> NvmeLogArchive:
        if log_type not in cls.LOG_COMMANDS: raise ValueError("log_type 仅支持 telemetry、telemetry_critical、extended_smart_c0、extended_smart_ca")
        target_dir=settings.logs_dir / "nvme" / device.name; target_dir.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); target=target_dir/f"{log_type}_{stamp}.bin"
        # Telemetry/扩展日志属于控制器级日志，不能使用具体 namespace 路径。
        command=cls.LOG_COMMANDS[log_type](cls.controller_path(device.path),target)
        archive=NvmeLogArchive(device_name=device.name,log_type=log_type,command_json=json.dumps(command),file_path=str(target),status="running")
        db.add(archive);db.commit();db.refresh(archive)
        try:
            completed=subprocess.run(command,capture_output=True,text=True,timeout=timeout,check=False)
            if completed.returncode: raise RuntimeError(completed.stderr.strip() or "nvme 命令执行失败")
            data=target.read_bytes() if target.exists() else completed.stdout.encode()
            archive.byte_size=len(data);archive.checksum_sha256=hashlib.sha256(data).hexdigest();archive.status="completed"
        except Exception as exc:
            archive.status="failed";archive.error_message=str(exc)
        db.commit();db.refresh(archive);return archive

    @staticmethod
    def archive_dict(item: NvmeLogArchive) -> dict[str,Any]:
        return {"id":item.id,"device_name":item.device_name,"log_type":item.log_type,"command":json.loads(item.command_json),"file_path":item.file_path,"byte_size":item.byte_size,"checksum_sha256":item.checksum_sha256,"status":item.status,"error_message":item.error_message,"created_at":item.created_at}

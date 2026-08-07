"""SSD 设备能力画像与测试场景适配建议。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any,Mapping
@dataclass(frozen=True)
class DeviceProfile:
    name:str;capacity_tib:float|None;temperature_c:float|None;health_score:float|None;recommended_profiles:tuple[str,...];risk_level:str;notes:tuple[str,...]
class DeviceProfileService:
    @staticmethod
    def profile(device:Mapping[str,Any],health:Mapping[str,Any]|None=None)->DeviceProfile:
        size=device.get("size_bytes");capacity=round(float(size)/(1024**4),2) if size else None;temperature=(health or {}).get("temperature_c",device.get("temperature_c"));score=(health or {}).get("health_score");notes=[];profiles=["web_service","database_oltp","virtualization"]
        if capacity is not None and capacity<1:notes.append("容量较小，不建议执行长时间全盘写压测。")
        if temperature is not None and float(temperature)>=60:notes.append("当前温度偏高，建议先改善散热。");profiles=["web_service"]
        if score is not None and float(score)<70:notes.append("健康评分偏低，建议只执行只读诊断测试。");profiles=[]
        risk="high" if score is not None and score<60 else "medium" if notes else "low"
        return DeviceProfile(str(device.get("name","unknown")),capacity,temperature,score,tuple(profiles),risk,tuple(notes))

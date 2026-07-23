"""API 输入输出的数据模型。"""
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    path: str
    model: Optional[str]
    serial: Optional[str]
    size_bytes: Optional[int]
    firmware: Optional[str]
    temperature_c: Optional[float]
    scanned_at: Optional[datetime]


class TaskCreate(BaseModel):
    device_name: str = Field(description="如 nvme1n1")
    test_name: Literal["seq_read_128k", "seq_write_128k", "rand_read_4k", "rand_write_4k"]
    confirm_destructive: bool = Field(False, description="写测试必须明确设为 true")


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_name: str
    test_name: str
    status: str
    error_message: Optional[str]
    fio_json_path: Optional[str]
    created_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class ResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    task_id: int
    iops: Optional[float]
    bw_mib_s: Optional[float]
    latency_avg_us: Optional[float]
    latency_p99_us: Optional[float]
    cpu_user_pct: Optional[float]
    cpu_system_pct: Optional[float]

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
    device_name: Optional[str] = Field(default=None, description="可省略；将使用配置中的默认设备")
    test_name: Literal["seq_read_128k", "seq_write_128k", "rand_read_4k", "rand_write_4k"]
    confirm_destructive: bool = Field(False, description="写测试必须明确设为 true")


class TestCreated(BaseModel):
    """创建测试后立即返回的任务信息。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str


class TestResult(BaseModel):
    """统一返回测试状态和完成后的性能数据，客户端只需轮询一个接口。"""

    task_id: int
    status: str
    error_message: Optional[str] = None
    result: Optional[dict[str, Optional[float]]] = None

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
    mounted: bool
    system_disk: bool
    has_partitions: bool
    safe_to_test: bool
    safety_message: Optional[str]


class TaskCreate(BaseModel):
    device_name: Optional[str] = Field(default=None, description="可省略；将使用配置中的默认设备")
    test_name: Literal["seq_read_128k", "seq_write_128k", "rand_read_4k", "rand_write_4k"]
    confirm_destructive: bool = Field(False, description="写测试必须明确设为 true")
    fio_options: Optional["FioOptionsRequest"] = Field(default=None, description="可选的 fio 参数覆盖值")


class FioOptionsRequest(BaseModel):
    """可按任务调整的 fio 参数；未填写的字段使用服务默认值。"""

    model_config = ConfigDict(extra="allow")

    runtime_seconds: Optional[int] = Field(default=None, ge=1, le=86400, description="正式测试时长（秒）")
    ramp_time_seconds: Optional[int] = Field(default=None, ge=0, le=3600, description="预热时长（秒）")
    iodepth: Optional[int] = Field(default=None, ge=1, le=1024, description="I/O 队列深度")
    numjobs: Optional[int] = Field(default=None, ge=1, le=128, description="并发 fio 任务数")
    ioengine: Optional[str] = Field(default=None, min_length=1, max_length=100, description="fio I/O 引擎")
    direct: Optional[bool] = Field(default=None, description="是否绕过系统页缓存")


class TestCreated(BaseModel):
    """创建测试后立即返回的任务信息。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    fio_options: dict[str, object]


class TestResult(BaseModel):
    """统一返回测试状态和完成后的性能数据，客户端只需轮询一个接口。"""

    task_id: int
    status: str
    error_message: Optional[str] = None
    fio_options: dict[str, object]
    progress_percent: int
    progress_phase: str
    elapsed_seconds: int
    total_seconds: int
    result: Optional[dict[str, Optional[float]]] = None

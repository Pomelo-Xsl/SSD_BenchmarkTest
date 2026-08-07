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


class DeviceFormatRequest(BaseModel):
    """格式化必须输入完整设备名进行二次确认。"""

    confirm_device_name: str = Field(min_length=1, max_length=100)


class DeviceFormatResult(BaseModel):
    device_name: str
    command: list[str]
    output: str



class TaskCreate(BaseModel):
    device_name: Optional[str] = Field(default=None, description="可省略；将使用配置中的默认设备")
    test_name: Literal["seq_read_128k", "seq_write_128k", "rand_read_4k", "rand_write_4k", "mixed_rw_4k"]
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


class TemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    test_name: Literal["seq_read_128k", "seq_write_128k", "rand_read_4k", "rand_write_4k", "mixed_rw_4k"]
    fio_options: FioOptionsRequest = Field(default_factory=FioOptionsRequest)


class TemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    test_name: Optional[Literal["seq_read_128k", "seq_write_128k", "rand_read_4k", "rand_write_4k", "mixed_rw_4k"]] = None
    fio_options: Optional[FioOptionsRequest] = None


class TemplateOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    test_name: str
    fio_options: dict[str, object]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AuditEventOut(BaseModel):
    id: int
    event_type: str
    target_type: str
    target_id: Optional[str] = None
    message: str
    detail: dict[str, object]
    created_at: Optional[datetime] = None




class BatchTestItem(BaseModel):
    """批量队列中的一个 fio 测试。"""

    test_name: Literal["seq_read_128k", "seq_write_128k", "rand_read_4k", "rand_write_4k", "mixed_rw_4k"]
    confirm_destructive: bool = Field(False, description="写测试必须明确设为 true")
    fio_options: Optional[FioOptionsRequest] = None


class BatchCreate(BaseModel):
    device_name: Optional[str] = Field(default=None, description="可省略；将使用配置中的默认设备")
    tests: list[BatchTestItem] = Field(min_length=1, max_length=32, description="按列表顺序逐个执行")


class BatchTaskOut(BaseModel):
    id: int
    test_name: str
    status: str
    progress_percent: int
    progress_phase: str


class BatchCreated(BaseModel):
    id: int
    status: str
    task_ids: list[int]


class BatchResult(BaseModel):
    id: int
    device_name: str
    status: str
    error_message: Optional[str] = None
    tasks: list[BatchTaskOut]


class TaskDeleteManyRequest(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=100)


class TaskDeleteManyResult(BaseModel):
    deleted_task_ids: list[int]



class TaskListItem(BaseModel):
    """结果页任务列表中的一条任务摘要。"""

    id: int
    device_name: str
    test_name: str
    status: str
    created_at: Optional[datetime] = None
    progress_percent: int
    progress_phase: str
    batch_id: Optional[int] = None
    batch_type: Optional[str] = None
    qd_value: Optional[int] = None


class TestResult(BaseModel):
    """统一返回测试状态和完成后的性能数据，客户端只需轮询一个接口。"""

    task_id: int
    device_name: str
    device_path: str
    test_name: str
    fio_command: list[str]
    status: str
    error_message: Optional[str] = None
    fio_options: dict[str, object]
    progress_percent: int
    progress_phase: str
    elapsed_seconds: int
    total_seconds: int
    result: Optional[dict[str, Optional[float]]] = None
    batch_id: Optional[int] = None
    batch_type: Optional[str] = None
    qd_value: Optional[int] = None

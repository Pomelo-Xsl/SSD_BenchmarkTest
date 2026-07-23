"""数据库实体：设备、任务与结果。"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base


class Device(Base):
    __tablename__ = "devices"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    path: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(255))
    serial: Mapped[Optional[str]] = mapped_column(String(255))
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    firmware: Mapped[Optional[str]] = mapped_column(String(100))
    temperature_c: Mapped[Optional[float]] = mapped_column(Float)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("test_batches.id"))
    device_name: Mapped[str] = mapped_column(ForeignKey("devices.name"), nullable=False)
    test_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    fio_options: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    fio_json_path: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class TestBatch(Base):
    """一组按顺序执行的 fio 测试。"""

    __tablename__ = "test_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_name: Mapped[str] = mapped_column(ForeignKey("devices.name"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Result(Base):
    __tablename__ = "results"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), unique=True, nullable=False)
    iops: Mapped[Optional[float]] = mapped_column(Float)
    bw_mib_s: Mapped[Optional[float]] = mapped_column(Float)
    latency_avg_us: Mapped[Optional[float]] = mapped_column(Float)
    latency_p99_us: Mapped[Optional[float]] = mapped_column(Float)
    cpu_user_pct: Mapped[Optional[float]] = mapped_column(Float)
    cpu_system_pct: Mapped[Optional[float]] = mapped_column(Float)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)

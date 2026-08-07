"""测试过程实时采样、曲线降采样和性能窗口聚合。"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Iterable

@dataclass(frozen=True)
class PerformancePoint:
    timestamp: datetime
    elapsed_seconds: int
    iops: float | None
    bandwidth_mib_s: float | None
    latency_us: float | None
    cpu_percent: float | None
    queue_depth: int | None

@dataclass(frozen=True)
class PerformanceWindow:
    start_seconds: int
    end_seconds: int
    points: int
    iops_average: float | None
    iops_peak: float | None
    bandwidth_average: float | None
    latency_average: float | None
    latency_peak: float | None

class PerformanceMonitorService:
    @staticmethod
    def point(payload: dict) -> PerformancePoint:
        now = payload.get("timestamp") or datetime.now(timezone.utc)
        if isinstance(now, str): now = datetime.fromisoformat(now.replace("Z","+00:00"))
        return PerformancePoint(now, max(0,int(payload.get("elapsed_seconds",0))), PerformanceMonitorService.number(payload.get("iops")), PerformanceMonitorService.number(payload.get("bandwidth_mib_s")), PerformanceMonitorService.number(payload.get("latency_us")), PerformanceMonitorService.number(payload.get("cpu_percent")), int(payload["queue_depth"]) if payload.get("queue_depth") is not None else None)
    @staticmethod
    def number(value): return float(value) if value is not None else None
    @staticmethod
    def downsample(points: Iterable[PerformancePoint], max_points: int=240) -> tuple[PerformancePoint,...]:
        rows=tuple(sorted(points,key=lambda x:x.elapsed_seconds))
        if len(rows)<=max_points:return rows
        step=len(rows)/max_points;return tuple(rows[min(len(rows)-1,int(index*step))] for index in range(max_points))
    @staticmethod
    def windows(points: Iterable[PerformancePoint], seconds: int=30) -> tuple[PerformanceWindow,...]:
        buckets={}
        for point in points:buckets.setdefault(point.elapsed_seconds//max(1,seconds),[]).append(point)
        result=[]
        for key,rows in sorted(buckets.items()):
            def values(field):return [getattr(row,field) for row in rows if getattr(row,field) is not None]
            iops=values("iops");bandwidth=values("bandwidth_mib_s");latency=values("latency_us")
            result.append(PerformanceWindow(key*seconds,(key+1)*seconds-1,len(rows),round(mean(iops),3) if iops else None,max(iops) if iops else None,round(mean(bandwidth),3) if bandwidth else None,round(mean(latency),3) if latency else None,max(latency) if latency else None))
        return tuple(result)
    @staticmethod
    def chart(points: Iterable[PerformancePoint], max_points: int=240) -> dict:
        rows=PerformanceMonitorService.downsample(points,max_points)
        return {"labels":[item.elapsed_seconds for item in rows],"series":{"iops":[item.iops for item in rows],"bandwidth_mib_s":[item.bandwidth_mib_s for item in rows],"latency_us":[item.latency_us for item in rows],"cpu_percent":[item.cpu_percent for item in rows]}}

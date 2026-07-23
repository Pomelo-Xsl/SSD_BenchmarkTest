"""fio JSON+ 报告解析为稳定的业务指标。"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParsedResult:
    iops: float | None
    bw_mib_s: float | None
    latency_avg_us: float | None
    latency_p99_us: float | None
    cpu_user_pct: float | None
    cpu_system_pct: float | None
    raw_json: str


class FioParser:
    """适配 fio JSON/JSON+ 中 read 与 write 两种统计结构。"""

    @staticmethod
    def parse(json_path: Path) -> ParsedResult:
        raw_json = json_path.read_text(encoding="utf-8")
        payload = json.loads(raw_json)
        jobs = payload.get("jobs", [])
        if not jobs:
            raise ValueError("fio 输出缺少 jobs")
        job = jobs[0]
        stats = job.get("read", {}) if job.get("read", {}).get("io_bytes", 0) else job.get("write", {})
        latency = stats.get("lat_ns", stats.get("clat_ns", {}))
        percentiles = latency.get("percentile", {})
        p99 = percentiles.get("99.000000") or percentiles.get("99.00")
        return ParsedResult(
            iops=FioParser._number(stats.get("iops")),
            bw_mib_s=FioParser._number(stats.get("bw_bytes"), divisor=1024 * 1024) if stats.get("bw_bytes") is not None else FioParser._number(stats.get("bw"), divisor=1024),
            latency_avg_us=FioParser._number(latency.get("mean"), divisor=1000),
            latency_p99_us=FioParser._number(p99, divisor=1000),
            cpu_user_pct=FioParser._number(job.get("usr_cpu")),
            cpu_system_pct=FioParser._number(job.get("sys_cpu")),
            raw_json=raw_json,
        )

    @staticmethod
    def _number(value: object, divisor: float = 1) -> float | None:
        return float(value) / divisor if value is not None else None

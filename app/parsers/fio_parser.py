"""fio JSON/JSON+ 报告解析为稳定的业务指标。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


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
    """适配 fio 不同版本的 read/write、latency 与 percentile 输出结构。"""

    @staticmethod
    def parse(json_path: Path) -> ParsedResult:
        return FioParser.parse_raw_json(json_path.read_text(encoding="utf-8"))

    @staticmethod
    def parse_raw_json(raw_json: str) -> ParsedResult:
        """解析已保存的原始 JSON，供历史结果延迟补算复用。"""
        payload = json.loads(raw_json)
        jobs = payload.get("jobs", [])
        if not jobs:
            raise ValueError("fio 输出缺少 jobs")
        job = jobs[0]
        stats = job.get("read", {}) if job.get("read", {}).get("io_bytes", 0) else job.get("write", {})
        average_us = FioParser._average_latency_us(stats)
        p99_us = FioParser._percentile_latency_us(stats, 99.0)
        return ParsedResult(
            iops=FioParser._number(stats.get("iops")),
            bw_mib_s=FioParser._number(stats.get("bw_bytes"), divisor=1024 * 1024) if stats.get("bw_bytes") is not None else FioParser._number(stats.get("bw"), divisor=1024),
            latency_avg_us=average_us,
            latency_p99_us=p99_us,
            cpu_user_pct=FioParser._number(job.get("usr_cpu")),
            cpu_system_pct=FioParser._number(job.get("sys_cpu")),
            raw_json=raw_json,
        )

    @staticmethod
    def _average_latency_us(stats: Mapping[str, Any]) -> float | None:
        # 保持原有优先级：总延迟优先，缺失时再读取完成延迟。
        for key, divisor in (("lat_ns", 1000), ("clat_ns", 1000), ("lat_us", 1), ("clat_us", 1)):
            value = stats.get(key)
            if isinstance(value, Mapping) and value.get("mean") is not None:
                return FioParser._number(value.get("mean"), divisor=divisor)
        return None

    @staticmethod
    def _percentile_latency_us(stats: Mapping[str, Any], percentile: float) -> float | None:
        """从 lat/clat 的 ns 或 us 区块中查找目标分位数。

        fio 3.x 常把 percentile 放进 clat_ns，而有的版本则在 lat_ns、
        lat_us 或 clat_us 中输出，因此不能只读取单一节点。
        """
        candidates = (
            ("lat_ns", 1000), ("clat_ns", 1000),
            ("lat_us", 1), ("clat_us", 1),
        )
        accepted = {f"{percentile:.6f}", f"{percentile:.3f}", f"{percentile:.2f}", str(int(percentile))}
        for key, divisor in candidates:
            latency = stats.get(key)
            if not isinstance(latency, Mapping):
                continue
            percentiles = latency.get("percentile", {})
            if not isinstance(percentiles, Mapping):
                continue
            for label, value in percentiles.items():
                try:
                    matched = str(label) in accepted or abs(float(label) - percentile) < 0.0001
                except (TypeError, ValueError):
                    matched = False
                if matched and value is not None:
                    return FioParser._number(value, divisor=divisor)
        return None

    @staticmethod
    def _number(value: object, divisor: float = 1) -> float | None:
        return float(value) / divisor if value is not None else None

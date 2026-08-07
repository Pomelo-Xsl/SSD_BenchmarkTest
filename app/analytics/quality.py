"""fio 结果数据质量校验与准入判断。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping

@dataclass(frozen=True)
class QualityCheck:
    key: str
    title: str
    status: str
    severity: str
    detail: str
    observed: Any = None
    expected: Any = None

@dataclass(frozen=True)
class QualityGate:
    score: float
    grade: str
    usable: bool
    checks: tuple[QualityCheck, ...]
    summary: str

REQUIRED_METRICS = ("iops", "bw_mib_s", "latency_avg_us", "latency_p99_us")

def _metric_checks(metrics: Mapping[str, float | None]) -> list[QualityCheck]:
    checks = []
    for key in REQUIRED_METRICS:
        value = metrics.get(key)
        checks.append(QualityCheck(
            f"metric.{key}", f"{key} 指标完整性", "pass" if value is not None else "fail",
            "info" if value is not None else "error",
            "已取得有效指标。" if value is not None else "结果缺少该关键指标，无法作为完整基准。", value))
    return checks

def _range_checks(metrics: Mapping[str, float | None]) -> list[QualityCheck]:
    checks = []
    for key in REQUIRED_METRICS:
        value = metrics.get(key)
        if value is None:
            continue
        good = float(value) >= 0
        checks.append(QualityCheck(
            f"range.{key}", f"{key} 合法范围", "pass" if good else "fail",
            "info" if good else "error", "数值处于合法范围。" if good else "性能指标不应为负值，结果文件可能损坏。", value, ">= 0"))
    for key in ("cpu_user_pct", "cpu_system_pct"):
        value = metrics.get(key)
        if value is None:
            continue
        high = float(value) > 100
        checks.append(QualityCheck(
            f"range.{key}", f"{key} 合理范围", "warn" if high else "pass",
            "warning" if high else "info",
            "CPU 占用超过单核 100%，可能由多线程或统计口径造成，请结合 numjobs 判断。" if high else "CPU 指标正常。", value, "0-100（单线程参考）"))
    return checks

def _relationship_checks(metrics: Mapping[str, float | None]) -> list[QualityCheck]:
    avg, p99 = metrics.get("latency_avg_us"), metrics.get("latency_p99_us")
    if avg is None or p99 is None:
        return []
    good = float(p99) >= float(avg)
    return [QualityCheck(
        "relationship.latency", "延迟分位关系", "pass" if good else "warn", "info" if good else "warning",
        "P99 延迟不低于平均延迟，统计关系合理。" if good else "P99 小于平均延迟，可能为 fio 版本或统计口径差异。",
        {"average": avg, "p99": p99})]

def _runtime_check(metadata: Mapping[str, Any]) -> list[QualityCheck]:
    requested, observed = metadata.get("runtime_seconds"), metadata.get("elapsed_seconds")
    if not requested or observed is None:
        return []
    ratio = float(observed) / max(float(requested), 1.0)
    if ratio >= .9:
        status, severity, detail = "pass", "info", "测试运行时长满足请求时长的 90% 以上。"
    elif ratio >= .5:
        status, severity, detail = "warn", "warning", "测试时长明显偏短，结果可供参考但不建议用于正式验收。"
    else:
        status, severity, detail = "fail", "error", "测试时长不足请求时长的一半，建议重新测试。"
    return [QualityCheck("runtime.coverage", "运行时长覆盖", status, severity, detail, observed, requested)]

def evaluate(metrics: Mapping[str, float | None], metadata: Mapping[str, Any] | None = None) -> QualityGate:
    """检查指标完整性、数值边界、延迟关系和运行时间覆盖率。"""
    checks = _metric_checks(metrics) + _range_checks(metrics) + _relationship_checks(metrics) + _runtime_check(metadata or {})
    penalties = {"error": 22.0, "warning": 7.0, "info": 0.0}
    score = max(0., min(100., 100. - sum(penalties[item.severity] for item in checks if item.status != "pass")))
    failures, warnings = [item for item in checks if item.status == "fail"], [item for item in checks if item.status == "warn"]
    if failures:
        grade, usable, summary = "D", False, f"发现 {len(failures)} 项关键数据问题，当前结果不建议用于基准结论。"
    elif warnings:
        grade, usable, summary = "B", True, f"结果可用，但有 {len(warnings)} 项提醒需要人工复核。"
    else:
        grade, usable, summary = "A", True, "数据完整且通过基础一致性校验，可用于性能分析。"
    return QualityGate(round(score, 2), grade, usable, tuple(checks), summary)

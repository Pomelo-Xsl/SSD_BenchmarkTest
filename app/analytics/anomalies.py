"""测试结果异常、回归与风险提示检测。"""
from __future__ import annotations
from app.analytics.statistics import percentile, relative_change, robust_z_score
from app.analytics.types import Anomaly, MetricSample


def detect_absolute_anomalies(sample: MetricSample) -> list[Anomaly]:
    result: list[Anomaly] = []
    p99 = sample.value("latency_p99_us")
    avg = sample.value("latency_avg_us")
    if p99 is not None and avg is not None and avg > 0 and p99 / avg > 15:
        result.append(Anomaly("latency_p99_us", "warning", "尾延迟放大", f"P99 延迟是平均延迟的 {p99 / avg:.1f} 倍，建议检查 GC、温度与队列深度。", p99, avg, (sample.task_id,)))
    cpu = (sample.value("cpu_user_pct") or 0) + (sample.value("cpu_system_pct") or 0)
    if cpu >= 95:
        result.append(Anomaly("cpu_total_pct", "warning", "CPU 接近饱和", f"测试期间 CPU 合计占用 {cpu:.1f}%，结果可能受处理器限制。", cpu, 95, (sample.task_id,)))
    if (sample.value("iops") or 0) <= 0 or (sample.value("bw_mib_s") or 0) <= 0:
        result.append(Anomaly("throughput", "critical", "吞吐结果异常", "IOPS 或带宽为零，建议检查 fio 输出、设备权限和 I/O 引擎。", sample.value("iops"), 1, (sample.task_id,)))
    return result


def detect_history_outliers(sample: MetricSample, history: list[MetricSample]) -> list[Anomaly]:
    issues: list[Anomaly] = []
    for metric in ("iops", "bw_mib_s", "latency_avg_us", "latency_p99_us"):
        values = [item.value(metric) for item in history]
        current = sample.value(metric)
        if current is None or len([value for value in values if value is not None]) < 4:
            continue
        z = robust_z_score(current, values)
        if z is not None and abs(z) >= 3.5:
            direction = "偏高" if z > 0 else "偏低"
            issues.append(Anomaly(metric, "warning", f"历史离群：{metric}", f"当前值相对可比历史结果明显{direction}（稳健 Z 分数 {z:.2f}）。", current, percentile(values, 50), (sample.task_id,)))
    return issues


def detect_regressions(sample: MetricSample, baseline: MetricSample | None) -> list[Anomaly]:
    if baseline is None:
        return []
    issues: list[Anomaly] = []
    for metric, worse_when_higher in (("iops", False), ("bw_mib_s", False), ("latency_avg_us", True), ("latency_p99_us", True)):
        change = relative_change(baseline.value(metric), sample.value(metric))
        if change is None:
            continue
        regressed = change < -10 if not worse_when_higher else change > 20
        if regressed:
            direction = "下降" if not worse_when_higher else "上升"
            issues.append(Anomaly(metric, "warning", f"性能回归：{metric}", f"相对基线任务 #{baseline.task_id} {direction} {abs(change):.1f}%。", sample.value(metric), baseline.value(metric), (baseline.task_id, sample.task_id)))
    return issues


def detect_all(sample: MetricSample, history: list[MetricSample]) -> tuple[Anomaly, ...]:
    baseline = history[-1] if history else None
    return tuple(detect_absolute_anomalies(sample) + detect_history_outliers(sample, history) + detect_regressions(sample, baseline))

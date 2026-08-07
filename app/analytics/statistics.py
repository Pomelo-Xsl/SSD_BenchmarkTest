"""无第三方依赖的统计计算工具。"""
from __future__ import annotations
import math
from collections.abc import Iterable
from app.analytics.types import Distribution, finite


def _sorted(values: Iterable[float | None]) -> list[float]:
    return sorted(value for value in finite(values) if math.isfinite(value))


def mean(values: Iterable[float | None]) -> float | None:
    items = _sorted(values)
    return sum(items) / len(items) if items else None


def median(values: Iterable[float | None]) -> float | None:
    items = _sorted(values)
    if not items:
        return None
    midpoint = len(items) // 2
    return items[midpoint] if len(items) % 2 else (items[midpoint - 1] + items[midpoint]) / 2


def percentile(values: Iterable[float | None], percent: float) -> float | None:
    items = _sorted(values)
    if not items:
        return None
    if percent <= 0:
        return items[0]
    if percent >= 100:
        return items[-1]
    index = (len(items) - 1) * percent / 100
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return items[lower]
    return items[lower] + (items[upper] - items[lower]) * (index - lower)


def variance(values: Iterable[float | None], sample: bool = True) -> float | None:
    items = _sorted(values)
    minimum_count = 2 if sample else 1
    if len(items) < minimum_count:
        return None
    avg = sum(items) / len(items)
    denominator = len(items) - 1 if sample else len(items)
    return sum((value - avg) ** 2 for value in items) / denominator


def standard_deviation(values: Iterable[float | None], sample: bool = True) -> float | None:
    value = variance(values, sample=sample)
    return math.sqrt(value) if value is not None else None


def coefficient_variation(values: Iterable[float | None]) -> float | None:
    avg = mean(values)
    deviation = standard_deviation(values)
    if avg is None or deviation is None or avg == 0:
        return None
    return abs(deviation / avg) * 100


def median_absolute_deviation(values: Iterable[float | None]) -> float | None:
    items = _sorted(values)
    centre = median(items)
    if centre is None:
        return None
    return median(abs(value - centre) for value in items)


def interquartile_range(values: Iterable[float | None]) -> float | None:
    first, third = percentile(values, 25), percentile(values, 75)
    return third - first if first is not None and third is not None else None


def robust_z_score(value: float, values: Iterable[float | None]) -> float | None:
    centre = median(values)
    mad = median_absolute_deviation(values)
    if centre is None or mad is None or mad == 0:
        return None
    return 0.6745 * (value - centre) / mad


def linear_slope(values: Iterable[float | None]) -> float | None:
    items = _sorted(values)
    if len(items) < 2:
        return None
    xs = list(range(len(items)))
    x_avg, y_avg = sum(xs) / len(xs), sum(items) / len(items)
    denominator = sum((x - x_avg) ** 2 for x in xs)
    if denominator == 0:
        return None
    return sum((x - x_avg) * (y - y_avg) for x, y in zip(xs, items)) / denominator


def relative_change(baseline: float | None, candidate: float | None) -> float | None:
    if baseline is None or candidate is None or baseline == 0:
        return None
    return (candidate - baseline) / abs(baseline) * 100


def distribution(values: Iterable[float | None]) -> Distribution:
    items = _sorted(values)
    return Distribution(
        count=len(items), minimum=items[0] if items else None, maximum=items[-1] if items else None,
        mean=mean(items), median=median(items), percentile_5=percentile(items, 5),
        percentile_25=percentile(items, 25), percentile_75=percentile(items, 75),
        percentile_95=percentile(items, 95), percentile_99=percentile(items, 99),
        standard_deviation=standard_deviation(items), coefficient_variation=coefficient_variation(items),
        mad=median_absolute_deviation(items),
    )


def stability_score(values: Iterable[float | None]) -> float:
    cv = coefficient_variation(values)
    if cv is None:
        return 100.0
    return max(0.0, min(100.0, 100 - cv * 2.5))


def classify_stability(values: Iterable[float | None]) -> tuple[str, str]:
    cv = coefficient_variation(values)
    if cv is None:
        return "未知", "样本数量不足，无法判断波动。"
    if cv <= 3:
        return "优秀", "波动极低，结果高度稳定。"
    if cv <= 8:
        return "良好", "波动处于正常范围。"
    if cv <= 15:
        return "关注", "存在明显波动，建议增加样本复测。"
    return "不稳定", "波动较大，建议检查温度、负载与后台进程。"


def clamp(value: float | None, low: float = 0, high: float = 100) -> float:
    if value is None or not math.isfinite(value):
        return low
    return max(low, min(high, value))

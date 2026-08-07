"""无需额外依赖的性能趋势预测。"""
from __future__ import annotations
from dataclasses import dataclass
from math import sqrt
from typing import Iterable

@dataclass(frozen=True)
class ForecastPoint:
    sequence: int
    value: float
    lower_bound: float | None
    upper_bound: float | None

@dataclass(frozen=True)
class Forecast:
    metric: str
    method: str
    history_count: int
    next_value: float | None
    slope_per_run: float | None
    residual_stddev: float | None
    confidence: str
    message: str
    points: tuple[ForecastPoint, ...]

def clean(values: Iterable[float | None]) -> list[float]:
    return [float(item) for item in values if item is not None]

def moving_average(values: Iterable[float | None], window: int = 3) -> list[float]:
    data, window = clean(values), max(1, int(window))
    return [sum(data[max(0, i-window+1):i+1]) / len(data[max(0, i-window+1):i+1]) for i in range(len(data))]

def exponential_smoothing(values: Iterable[float | None], alpha: float = .35) -> list[float]:
    data = clean(values)
    if not data: return []
    alpha = max(.01, min(float(alpha), 1.))
    smoothed = [data[0]]
    for value in data[1:]: smoothed.append(alpha*value+(1-alpha)*smoothed[-1])
    return smoothed

def linear_regression(values: Iterable[float | None]) -> tuple[float | None, float | None, float | None]:
    data, count = clean(values), len(clean(values))
    if not count: return None, None, None
    if count == 1: return data[0], 0., 0.
    x_mean, y_mean = (count-1)/2, sum(data)/count
    denominator = sum((i-x_mean)**2 for i in range(count))
    slope = sum((i-x_mean)*(v-y_mean) for i, v in enumerate(data)) / denominator
    intercept = y_mean-slope*x_mean
    residuals = [v-(intercept+slope*i) for i,v in enumerate(data)]
    return intercept, slope, sqrt(sum(x*x for x in residuals)/max(count-2,1))

def confidence_level(count: int, residual: float | None, predicted: float | None) -> str:
    if count < 3: return "低"
    if predicted in (None, 0) or residual is None: return "中"
    ratio = abs(residual / predicted)
    return "高" if count >= 8 and ratio < .08 else "中" if ratio < .25 else "低"

def predict(metric: str, values: Iterable[float | None], horizon: int = 3, interval: float = 1.96) -> Forecast:
    data = clean(values); horizon = max(1, min(int(horizon), 30))
    intercept, slope, residual = linear_regression(data)
    if intercept is None or slope is None:
        return Forecast(metric, "linear_regression", 0, None, None, None, "低", "没有可用历史数据，无法预测。", ())
    points = []
    for index in range(1, horizon+1):
        value = intercept+slope*(len(data)-1+index)
        margin = interval*residual if residual is not None else None
        points.append(ForecastPoint(len(data)+index, round(value,6), round(value-margin,6) if margin is not None else None, round(value+margin,6) if margin is not None else None))
    if len(data) < 3: message = "历史样本不足 3 条，预测仅作为参考。"
    elif slope > 0: message = "趋势线向上，后续轮次预计高于当前平均水平。"
    elif slope < 0: message = "趋势线向下，建议检查是否存在持续退化。"
    else: message = "趋势基本平稳。"
    return Forecast(metric, "linear_regression", len(data), points[0].value, round(slope,6), round(residual or 0.,6), confidence_level(len(data), residual, points[0].value), message, tuple(points))

def forecast_many(series: dict[str, Iterable[float | None]], horizon: int = 3) -> tuple[Forecast, ...]:
    return tuple(predict(metric, values, horizon) for metric, values in series.items())

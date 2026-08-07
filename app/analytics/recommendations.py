"""将评分、质量和异常转换为可执行操作建议。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Mapping
from app.analytics.types import Anomaly, ScoreCard
from app.analytics.quality import QualityGate

@dataclass(frozen=True)
class Recommendation:
    priority: str
    category: str
    title: str
    rationale: str
    actions: tuple[str, ...]
    related_metrics: tuple[str, ...] = ()

def _quality(quality: QualityGate) -> list[Recommendation]:
    if quality.usable: return []
    failed = tuple(item.title for item in quality.checks if item.status == "fail")
    return [Recommendation("high", "data_quality", "先修复数据质量问题", quality.summary, ("确认 fio 命令是否完整执行并保留原始 JSON 输出。", "检查任务日志、设备连接和内核错误信息。", "修复后以相同参数重新运行至少三次。"), failed)]

def _score(scorecard: ScoreCard) -> list[Recommendation]:
    result=[]
    for dimension in scorecard.dimensions:
        if dimension.score >= 70: continue
        if dimension.key == "latency": actions=("降低 iodepth 或 numjobs，观察延迟是否回落。", "检查设备温度、PCIe 链路以及宿主机 CPU 竞争。", "使用相同 bs 与 rw 组合进行三轮复测。")
        elif dimension.key == "stability": actions=("固定运行时长、预热时间和队列深度。", "避免测试期间存在其他高 I/O 业务。", "收集至少 5 轮同条件结果后再判断。")
        else: actions=("确认 direct=1 与目标测试场景一致。", "依次调整 bs、iodepth、numjobs 定位瓶颈。", "检查 PCIe 代际与链路宽度是否符合设备规格。")
        result.append(Recommendation("medium",dimension.key,f"优化{dimension.title}",dimension.explanation,actions,(dimension.key,)))
    return result

def _anomalies(anomalies: Iterable[Anomaly]) -> list[Recommendation]:
    result=[]
    for anomaly in anomalies:
        if anomaly.severity == "info": continue
        if "延迟" in anomaly.title: actions=("记录当时设备温度与系统负载。", "比对 P99 延迟与历史中位值。", "缩小队列深度后复测以区分设备与负载问题。")
        else: actions=("确认测试盘未被挂载且不存在后台 I/O。", "核对 bs、rw、iodepth、numjobs 是否和基线相同。", "检查固件、PCIe 链路及 NVMe SMART 告警。")
        result.append(Recommendation("high" if anomaly.severity == "error" else "medium","anomaly",anomaly.title,anomaly.detail,actions,(anomaly.metric,)))
    return result

def generate(scorecard: ScoreCard, quality: QualityGate, anomalies: Iterable[Anomaly], trends: Iterable[Mapping[str, object]]=()) -> tuple[Recommendation,...]:
    candidates = _quality(quality)+_anomalies(anomalies)+_score(scorecard)
    priority={"high":0,"medium":1,"low":2}; result=[]; seen=set()
    for item in sorted(candidates,key=lambda x:priority.get(x.priority,3)):
        key=(item.category,item.title)
        if key not in seen: result.append(item); seen.add(key)
        if len(result)==8: break
    if not result: result.append(Recommendation("low","baseline","当前结果表现稳定","未发现需要立即处理的数据质量问题或明显异常。",("将当前任务作为基线保留。","后续使用同一模板定期复测并观察趋势。")))
    return tuple(result)

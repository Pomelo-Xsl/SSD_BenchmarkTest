"""按负载类型生成可解释的 SSD 性能评分。"""
from __future__ import annotations
from app.analytics.statistics import clamp
from app.analytics.types import ScoreCard, ScoreDimension


class ScorePolicy:
    """评分阈值可在未来由配置或设备类别覆盖。"""
    READ_IOPS_REFERENCE = 200_000
    WRITE_IOPS_REFERENCE = 120_000
    READ_BW_REFERENCE = 6_000
    WRITE_BW_REFERENCE = 4_000
    LATENCY_REFERENCE_US = 1_000
    P99_REFERENCE_US = 5_000
    CPU_REFERENCE_PERCENT = 75

    @classmethod
    def throughput_score(cls, iops: float | None, bw: float | None, test_name: str) -> tuple[float, str]:
        is_write = "write" in test_name
        iops_ref = cls.WRITE_IOPS_REFERENCE if is_write else cls.READ_IOPS_REFERENCE
        bw_ref = cls.WRITE_BW_REFERENCE if is_write else cls.READ_BW_REFERENCE
        iops_score = clamp((iops or 0) / iops_ref * 100)
        bw_score = clamp((bw or 0) / bw_ref * 100)
        score = iops_score * .55 + bw_score * .45
        return score, f"IOPS 参考值 {iops_ref:,.0f}，带宽参考值 {bw_ref:,.0f} MiB/s。"

    @classmethod
    def latency_score(cls, average: float | None, p99: float | None) -> tuple[float, str]:
        avg_score = clamp(100 - max(0, (average or cls.LATENCY_REFERENCE_US) / cls.LATENCY_REFERENCE_US - 1) * 40)
        p99_score = clamp(100 - max(0, (p99 or cls.P99_REFERENCE_US) / cls.P99_REFERENCE_US - 1) * 45)
        score = avg_score * .4 + p99_score * .6
        return score, "P99 延迟权重更高，用于反映尾延迟风险。"

    @classmethod
    def efficiency_score(cls, cpu_user: float | None, cpu_system: float | None) -> tuple[float, str]:
        total = max(0, (cpu_user or 0) + (cpu_system or 0))
        score = clamp(100 - max(0, total - cls.CPU_REFERENCE_PERCENT) * 1.5)
        return score, f"总 CPU 占用 {total:.2f}%（超过 {cls.CPU_REFERENCE_PERCENT}% 会扣分）。"

    @staticmethod
    def stability_dimension(score: float) -> tuple[float, str]:
        return clamp(score), "根据同一设备、同一负载的历史结果波动计算。"


def score_level(score: float) -> str:
    if score >= 90:
        return "优秀"
    if score >= 75:
        return "良好"
    if score >= 60:
        return "合格"
    if score >= 40:
        return "待优化"
    return "风险"


def grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "E"


def build_scorecard(metrics: dict[str, float | None], test_name: str, stability: float = 100) -> ScoreCard:
    throughput, throughput_note = ScorePolicy.throughput_score(metrics.get("iops"), metrics.get("bw_mib_s"), test_name)
    latency, latency_note = ScorePolicy.latency_score(metrics.get("latency_avg_us"), metrics.get("latency_p99_us"))
    efficiency, efficiency_note = ScorePolicy.efficiency_score(metrics.get("cpu_user_pct"), metrics.get("cpu_system_pct"))
    stable, stable_note = ScorePolicy.stability_dimension(stability)
    raw = (("throughput", "吞吐性能", throughput, .40, throughput_note), ("latency", "延迟表现", latency, .30, latency_note), ("stability", "结果稳定性", stable, .20, stable_note), ("efficiency", "资源效率", efficiency, .10, efficiency_note))
    dimensions = tuple(ScoreDimension(key=key, title=title, score=round(score, 2), weight=weight, weighted_score=round(score * weight, 2), level=score_level(score), explanation=note) for key, title, score, weight, note in raw)
    total = round(sum(item.weighted_score for item in dimensions), 2)
    level = score_level(total)
    return ScoreCard(total=total, grade=grade(total), summary=f"综合评分 {total:.2f}/100，等级 {level}（{grade(total)}）。", dimensions=dimensions)

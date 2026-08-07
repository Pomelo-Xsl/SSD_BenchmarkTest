"""可复用性能 SLA 策略、评估和违约归因。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
@dataclass(frozen=True)
class SlaPolicy:
    name:str;min_iops:float|None=None;min_bw_mib_s:float|None=None;max_p99_latency_us:float|None=None;max_temperature_c:float|None=None
@dataclass(frozen=True)
class SlaVerdict:
    policy:str;passed:bool;checks:tuple[dict,...];summary:str
class SlaPolicyService:
    @staticmethod
    def evaluate(policy:SlaPolicy,metrics:Mapping[str,float|None],temperature:float|None=None)->SlaVerdict:
        rules=(("iops",policy.min_iops,"min"),("bw_mib_s",policy.min_bw_mib_s,"min"),("latency_p99_us",policy.max_p99_latency_us,"max"),("temperature_c",policy.max_temperature_c,"max"));checks=[]
        for key,target,mode in rules:
            if target is None:continue
            observed=temperature if key=="temperature_c" else metrics.get(key);passed=observed is not None and (observed>=target if mode=="min" else observed<=target);checks.append({"metric":key,"observed":observed,"target":target,"mode":mode,"passed":passed})
        passed=all(row["passed"] for row in checks);return SlaVerdict(policy.name,passed,tuple(checks),"满足全部 SLA 指标。" if passed else "存在 SLA 指标未达标，请查看具体检查项。")

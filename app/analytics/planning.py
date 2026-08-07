"""SSD 容量、耐久度和性能基线规划算法。

算法只用于辅助运维决策；参数应以设备规格书、实际写入量和工作负载要求为准。
"""
from __future__ import annotations
from dataclasses import dataclass
from math import ceil
from typing import Iterable, Mapping

MIB=1024*1024
GIB=1024*MIB
TIB=1024*GIB

@dataclass(frozen=True)
class CapacityPlan:
    raw_capacity_bytes: int
    reserved_percent: float
    usable_capacity_bytes: int
    working_set_bytes: int
    headroom_bytes: int
    headroom_percent: float
    state: str
    message: str

@dataclass(frozen=True)
class EndurancePlan:
    capacity_tib: float
    assumed_dwpd: float
    host_write_tib_per_day: float
    write_amplification: float
    effective_nand_write_tib_per_day: float
    estimated_lifetime_days: float | None
    estimated_lifetime_years: float | None
    state: str
    message: str

@dataclass(frozen=True)
class TestTimePlan:
    runtime_seconds: int
    ramp_seconds: int
    repeats: int
    estimated_total_seconds: int
    estimated_data_mib: float | None
    expected_completion_minutes: float
    message: str

@dataclass(frozen=True)
class BaselineDecision:
    compatible: bool
    confidence: str
    reasons: tuple[str,...]
    required_matches: tuple[str,...]
    differing_options: tuple[str,...]

@dataclass(frozen=True)
class ServiceLevelAssessment:
    target_iops: float | None
    target_bw_mib_s: float | None
    max_latency_p99_us: float | None
    observed_iops: float | None
    observed_bw_mib_s: float | None
    observed_latency_p99_us: float | None
    passed: bool
    checks: tuple[dict[str,object],...]

def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower,min(upper,value))

def bytes_for(value: float, unit: str) -> int:
    names={"b":1,"kb":1000,"mb":1000**2,"gb":1000**3,"tb":1000**4,"kib":1024,"mib":MIB,"gib":GIB,"tib":TIB}
    key=unit.lower()
    if key not in names: raise ValueError("容量单位仅支持 B、KB、MB、GB、TB、KiB、MiB、GiB、TiB")
    return int(float(value)*names[key])

def human_bytes(value: int | float | None) -> str:
    if value is None: return "—"
    amount=float(value)
    for unit,divisor in (("TiB",TIB),("GiB",GIB),("MiB",MIB),("KiB",1024)):
        if abs(amount)>=divisor: return f"{amount/divisor:.2f} {unit}"
    return f"{amount:.0f} B"

def plan_capacity(raw_capacity_bytes: int, working_set_bytes: int, reserved_percent: float=10.0) -> CapacityPlan:
    if raw_capacity_bytes<=0 or working_set_bytes<0: raise ValueError("容量必须为非负，设备容量必须大于 0")
    reserved=clamp(float(reserved_percent),0,80)
    usable=int(raw_capacity_bytes*(100-reserved)/100)
    headroom=usable-working_set_bytes
    headroom_pct=(headroom/usable*100) if usable else 0
    if headroom<0: state,message="insufficient","工作集超过预留后的可用容量，可能导致空间耗尽、GC 放大和性能失真。"
    elif headroom_pct<10: state,message="tight","可用余量低于 10%，建议缩小工作集或提高设备容量。"
    elif headroom_pct<25: state,message="caution","可用余量有限，长时间写压测前建议检查磨损和温度。"
    else: state,message="healthy","容量余量充足。"
    return CapacityPlan(raw_capacity_bytes,reserved,usable,working_set_bytes,headroom,round(headroom_pct,2),state,message)

def estimate_endurance(capacity_bytes: int, dwpd: float, host_write_tib_per_day: float, write_amplification: float=1.0, used_percent: float=0.0) -> EndurancePlan:
    if capacity_bytes<=0 or dwpd<=0 or host_write_tib_per_day<0 or write_amplification<=0: raise ValueError("容量、DWPD 和写入放大系数必须大于 0")
    capacity_tib=capacity_bytes/TIB; effective=host_write_tib_per_day*write_amplification
    remaining=max(0.,1-clamp(used_percent,0,100)/100)
    budget=capacity_tib*dwpd*365*5*remaining
    days=(budget/effective) if effective>0 else None
    years=(days/365) if days is not None else None
    if days is None: state,message="idle","当前没有主机写入量，无法估算消耗速度。"
    elif years<1: state,message="critical","按当前写入量，预计剩余寿命不足一年。"
    elif years<2: state,message="warning","按当前写入量，建议在两年内制定替换计划。"
    else: state,message="healthy","按假设参数，耐久度余量可接受。"
    return EndurancePlan(round(capacity_tib,3),float(dwpd),float(host_write_tib_per_day),float(write_amplification),round(effective,3),round(days,1) if days is not None else None,round(years,2) if years is not None else None,state,message)

def estimate_test_time(runtime_seconds: int, ramp_seconds: int, repeats: int=3, bw_mib_s: float | None=None) -> TestTimePlan:
    runtime=max(1,int(runtime_seconds));ramp=max(0,int(ramp_seconds));repeats=max(1,int(repeats))
    total=(runtime+ramp)*repeats
    data=(float(bw_mib_s)*runtime*repeats) if bw_mib_s is not None and bw_mib_s>=0 else None
    message="已按预热与正式测试时长估算。若使用批量队列，应叠加各测试项时长。"
    return TestTimePlan(runtime,ramp,repeats,total,round(data,2) if data is not None else None,round(total/60,2),message)

def baseline_compatibility(reference: Mapping[str,object], candidate: Mapping[str,object], required: Iterable[str]=( "rw","bs","iodepth","numjobs","ioengine","direct")) -> BaselineDecision:
    required=tuple(required);different=[];reasons=[]
    for key in required:
        if reference.get(key)!=candidate.get(key): different.append(key)
    if different: reasons.append("关键 fio 参数不同："+"、".join(different))
    if reference.get("runtime_seconds") and candidate.get("runtime_seconds") and int(candidate["runtime_seconds"])<int(reference["runtime_seconds"])*.8: reasons.append("候选测试时长明显短于基线，统计可信度较低。")
    if not reasons: confidence="high";reasons.append("关键 fio 参数一致，可进行直接性能对比。")
    elif len(different)<=1: confidence="medium";reasons.append("可做趋势参考，但不建议直接作为验收结论。")
    else: confidence="low";reasons.append("参数差异较大，建议创建独立基线。")
    return BaselineDecision(not different,confidence,tuple(reasons),required,tuple(different))

def assess_service_level(metrics: Mapping[str,float|None], target_iops: float|None=None, target_bw_mib_s: float|None=None, max_latency_p99_us: float|None=None) -> ServiceLevelAssessment:
    checks=[]
    def check(key:str,title:str,observed:float|None,target:float|None,mode:str)->None:
        if target is None: return
        passed=observed is not None and (observed>=target if mode=="min" else observed<=target)
        checks.append({"metric":key,"title":title,"observed":observed,"target":target,"mode":mode,"passed":passed})
    check("iops","IOPS 下限",metrics.get("iops"),target_iops,"min")
    check("bw_mib_s","带宽下限",metrics.get("bw_mib_s"),target_bw_mib_s,"min")
    check("latency_p99_us","P99 延迟上限",metrics.get("latency_p99_us"),max_latency_p99_us,"max")
    return ServiceLevelAssessment(target_iops,target_bw_mib_s,max_latency_p99_us,metrics.get("iops"),metrics.get("bw_mib_s"),metrics.get("latency_p99_us"),all(item["passed"] for item in checks),tuple(checks))

def recommend_repeats(coefficient_variation: float|None, minimum:int=3, maximum:int=10)->int:
    if coefficient_variation is None:return minimum
    if coefficient_variation<.03:return minimum
    if coefficient_variation<.08:return min(maximum,5)
    if coefficient_variation<.15:return min(maximum,7)
    return maximum

def confidence_interval(mean:float|None,stddev:float|None,count:int,z:float=1.96)->tuple[float|None,float|None]:
    if mean is None or stddev is None or count<2:return None,None
    margin=z*stddev/(count**.5);return round(mean-margin,6),round(mean+margin,6)

def percentile_rank(value:float|None, samples:Iterable[float|None])->float|None:
    data=sorted(float(x) for x in samples if x is not None)
    if value is None or not data:return None
    return round(sum(x<=value for x in data)/len(data)*100,2)

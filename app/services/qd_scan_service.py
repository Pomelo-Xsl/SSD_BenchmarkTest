"""队列深度（QD）扫描：为同一负载构建不同 iodepth 的串行批次。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Iterable
from sqlalchemy.orm import Session
from app.services.batch_service import BatchService
from app.services.fio_service import TESTS

@dataclass(frozen=True)
class QdScanPlan:
    device_name: str
    test_name: str
    qd_values: tuple[int, ...]
    runtime_seconds: int
    ramp_time_seconds: int
    numjobs: int
    ioengine: str
    direct: bool
    destructive: bool

class QdScanService:
    DEFAULT_QDS=(1,2,4,8,16,32,64)
    @staticmethod
    def destructive(test_name:str)->bool:
        return TESTS[test_name][0] not in {"read","randread"}
    @classmethod
    def plan(cls,device_name:str,test_name:str,qd_values:Iterable[int]|None=None,runtime_seconds:int=60,ramp_time_seconds:int=10,numjobs:int=1,ioengine:str="io_uring",direct:bool=True)->QdScanPlan:
        if test_name not in TESTS:raise ValueError("不支持的测试类型")
        qds=tuple(sorted(set(int(x) for x in (qd_values or cls.DEFAULT_QDS))))
        if not qds or len(qds)>16 or any(x<1 or x>1024 for x in qds):raise ValueError("QD 列表需包含 1-16 个 1 到 1024 的整数")
        if not 1<=int(runtime_seconds)<=86400 or not 0<=int(ramp_time_seconds)<=3600:raise ValueError("测试或预热时长不合法")
        return QdScanPlan(device_name,test_name,qds,int(runtime_seconds),int(ramp_time_seconds),int(numjobs),ioengine,bool(direct),cls.destructive(test_name))
    @classmethod
    def create_batch(cls,db:Session,plan:QdScanPlan,confirm_destructive:bool):
        if plan.destructive and not confirm_destructive:raise ValueError("写入型 QD 扫描会破坏数据，必须确认 confirm_destructive=true")
        tests=[]
        for qd in plan.qd_values:
            tests.append({"test_name":plan.test_name,"confirm_destructive":confirm_destructive,"fio_options":{"runtime_seconds":plan.runtime_seconds,"ramp_time_seconds":plan.ramp_time_seconds,"iodepth":qd,"numjobs":plan.numjobs,"ioengine":plan.ioengine,"direct":plan.direct}})
        return BatchService.create(db, plan.device_name, tests, batch_type="qd_scan")
    @staticmethod
    def summarize(items:list[dict[str,Any]])->dict[str,Any]:
        rows=[]
        for item in items:
            options=item.get("fio_options") or {};result=item.get("result") or {}
            rows.append({"task_id":item.get("task_id"),"qd":options.get("iodepth"),"status":item.get("status"),"iops":result.get("iops"),"bw_mib_s":result.get("bw_mib_s"),"latency_avg_us":result.get("latency_avg_us"),"latency_p99_us":result.get("latency_p99_us")})
        return {"points":sorted(rows,key=lambda x:x["qd"] or 0),"best_iops_qd":max((row for row in rows if row["iops"] is not None),key=lambda x:x["iops"],default=None),"best_bandwidth_qd":max((row for row in rows if row["bw_mib_s"] is not None),key=lambda x:x["bw_mib_s"],default=None)}

"""多批次 SSD 测试结果的归一化对标和排名。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from app.models import Result,Task
@dataclass(frozen=True)
class RankingRow:
    task_id:int;device_name:str;test_name:str;score:float;iops:float|None;bandwidth:float|None;latency:float|None;rank:int
class BatchComparisonService:
    @staticmethod
    def score(result:Result)->float:
        iops=min(40,(result.iops or 0)/100000*40);bw=min(35,(result.bw_mib_s or 0)/3000*35);latency=max(0,25-(result.latency_p99_us or 100000)/10000*25);return round(iops+bw+latency,2)
    @classmethod
    def rank(cls,pairs:Iterable[tuple[Task,Result]])->list[RankingRow]:
        sorted_rows=sorted(pairs,key=lambda pair:cls.score(pair[1]),reverse=True);return [RankingRow(task.id,task.device_name,task.test_name,cls.score(result),result.iops,result.bw_mib_s,result.latency_p99_us,index+1) for index,(task,result) in enumerate(sorted_rows)]
    @staticmethod
    def summary(rows:Iterable[RankingRow])->dict:
        rows=list(rows);return {"count":len(rows),"winner":rows[0].__dict__ if rows else None,"devices":sorted({row.device_name for row in rows}),"tests":sorted({row.test_name for row in rows})}

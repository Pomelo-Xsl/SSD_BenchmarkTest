"""统一 SMART、fio 和告警信息的规则诊断引擎。"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from sqlalchemy.orm import Session
from app.models import DeviceHealthSnapshot, DiagnosticFinding, Result, Task

@dataclass(frozen=True)
class RuleFinding:
    rule_key:str; severity:str; category:str; title:str; evidence:dict[str,Any]; recommendations:tuple[str,...]

class DiagnosticRuleService:
    @staticmethod
    def health(snapshot:DeviceHealthSnapshot|None)->dict[str,Any]:
        if snapshot is None:return {}
        return {"temperature_c":snapshot.temperature_c,"available_spare":snapshot.available_spare,"percentage_used":snapshot.percentage_used,"media_errors":snapshot.media_errors,"error_log_entries":snapshot.error_log_entries,"health_score":snapshot.health_score}
    @classmethod
    def evaluate(cls,task:Task|None,result:Result|None,health:Mapping[str,Any])->tuple[RuleFinding,...]:
        rows=[];temp=health.get("temperature_c");errors=health.get("media_errors");used=health.get("percentage_used")
        if temp is not None and temp>=70: rows.append(RuleFinding("thermal.high","high","thermal","SSD 温度过高",{"temperature_c":temp},("停止长时间写压测并检查散热。","确认风扇、气流和散热片接触正常。")))
        if errors is not None and errors>0: rows.append(RuleFinding("media.errors","critical","reliability","检测到 NVMe 介质错误",{"media_errors":errors},("立即备份数据并采集 telemetry 日志。","检查 SMART 与内核 NVMe 错误记录。")))
        if used is not None and used>=80: rows.append(RuleFinding("endurance.used","warning","endurance","SSD 寿命消耗较高",{"percentage_used":used},("建立替换计划。","降低写放大并持续跟踪 percentage_used。")))
        if result:
            if result.latency_p99_us and result.latency_avg_us and result.latency_p99_us>result.latency_avg_us*10: rows.append(RuleFinding("latency.tail","warning","performance","尾延迟明显放大",{"latency_avg_us":result.latency_avg_us,"latency_p99_us":result.latency_p99_us},("降低队列深度并排除后台 I/O 干扰。","在低负载窗口复测。")))
            if result.iops is not None and result.iops<=0: rows.append(RuleFinding("performance.zero_iops","critical","execution","fio 结果 IOPS 为零",{"iops":result.iops,"task_id":task.id if task else None},("检查 fio 输出和设备路径。","确认测试未被权限或安全检查中断。")))
        return tuple(rows)
    @classmethod
    def persist(cls,db:Session,device_name:str,findings:Iterable[RuleFinding],task_id:int|None=None)->list[DiagnosticFinding]:
        created=[]
        for item in findings:
            exists=db.query(DiagnosticFinding).filter(DiagnosticFinding.task_id==task_id,DiagnosticFinding.rule_key==item.rule_key,DiagnosticFinding.status=="open").first()
            if exists:continue
            row=DiagnosticFinding(task_id=task_id,device_name=device_name,rule_key=item.rule_key,severity=item.severity,category=item.category,title=item.title,evidence_json=json.dumps(item.evidence,ensure_ascii=False),recommendation_json=json.dumps(item.recommendations,ensure_ascii=False))
            db.add(row);created.append(row)
        if created:db.commit()
        return created
    @staticmethod
    def serialize(item:DiagnosticFinding)->dict[str,Any]:
        return {"id":item.id,"task_id":item.task_id,"device_name":item.device_name,"rule_key":item.rule_key,"severity":item.severity,"category":item.category,"title":item.title,"evidence":json.loads(item.evidence_json),"recommendations":json.loads(item.recommendation_json),"status":item.status,"created_at":item.created_at,"resolved_at":item.resolved_at}
    @staticmethod
    def resolve(db:Session,item:DiagnosticFinding)->DiagnosticFinding:
        item.status="resolved";item.resolved_at=datetime.now(timezone.utc);db.commit();db.refresh(item);return item

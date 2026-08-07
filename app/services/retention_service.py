"""历史数据保留、归档预览与受控清理服务。

所有清理先进行预览；实际删除须由调用方显式传入 confirm=True。原始日志只会复制到
归档目录后再删除，且数据库执行记录会保留。
"""
from __future__ import annotations
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import DeviceHealthSnapshot, NvmeLogArchive, ResultSnapshot, RetentionPolicy, RetentionRun

RESOURCE_MODELS={"result_snapshots":ResultSnapshot,"health_snapshots":DeviceHealthSnapshot,"nvme_logs":NvmeLogArchive}

@dataclass(frozen=True)
class RetentionPreview:
    policy_id:int
    resource_type:str
    cutoff:datetime
    candidates:int
    candidate_ids:tuple[int,...]
    reasons:dict[str,int]

class RetentionService:
    @staticmethod
    def now()->datetime:return datetime.now(timezone.utc)

    @classmethod
    def validate(cls,resource_type:str,retain_days:int,max_records:int|None)->None:
        if resource_type not in RESOURCE_MODELS:raise ValueError("resource_type 仅支持 result_snapshots、health_snapshots、nvme_logs")
        if not 1<=int(retain_days)<=36500:raise ValueError("retain_days 必须为 1 到 36500")
        if max_records is not None and not 1<=int(max_records)<=1000000:raise ValueError("max_records 必须为 1 到 1000000")

    @classmethod
    def create(cls,db:Session,name:str,resource_type:str,retain_days:int,max_records:int|None=None,archive_before_delete:bool=True)->RetentionPolicy:
        cls.validate(resource_type,retain_days,max_records)
        if db.query(RetentionPolicy).filter(RetentionPolicy.name==name.strip()).first():raise ValueError("策略名称已存在")
        item=RetentionPolicy(name=name.strip(),resource_type=resource_type,retain_days=int(retain_days),max_records=max_records,archive_before_delete=bool(archive_before_delete))
        db.add(item);db.commit();db.refresh(item);return item

    @staticmethod
    def serialize(policy:RetentionPolicy)->dict[str,Any]:
        return {"id":policy.id,"name":policy.name,"resource_type":policy.resource_type,"retain_days":policy.retain_days,"max_records":policy.max_records,"archive_before_delete":policy.archive_before_delete,"enabled":policy.enabled,"last_run_at":policy.last_run_at,"last_summary":json.loads(policy.last_summary_json or "{}"),"created_at":policy.created_at,"updated_at":policy.updated_at}

    @classmethod
    def preview(cls,db:Session,policy:RetentionPolicy,now:datetime|None=None)->RetentionPreview:
        now=now or cls.now();model=RESOURCE_MODELS[policy.resource_type];cutoff=now-timedelta(days=policy.retain_days)
        time_col=model.created_at if policy.resource_type=="nvme_logs" else model.captured_at
        old_rows=db.query(model).filter(time_col<cutoff).order_by(time_col).all();ids={row.id for row in old_rows};reasons={"age":len(old_rows),"count":0}
        if policy.max_records:
            all_rows=db.query(model).order_by(time_col.desc()).all()
            overflow=all_rows[policy.max_records:]
            ids.update(row.id for row in overflow);reasons["count"]=len(overflow)
        return RetentionPreview(policy.id,policy.resource_type,cutoff,len(ids),tuple(sorted(ids)),reasons)

    @staticmethod
    def _archive_log(item:NvmeLogArchive)->bool:
        source=Path(item.file_path)
        if not source.exists():return False
        target=settings.logs_dir/"archive"/item.device_name/source.name
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);return target.exists()

    @classmethod
    def execute(cls,db:Session,policy:RetentionPolicy,confirm:bool=False)->dict[str,Any]:
        preview=cls.preview(db,policy);mode="execute" if confirm else "preview";archived=deleted=0
        if confirm:
            model=RESOURCE_MODELS[policy.resource_type]
            rows=db.query(model).filter(model.id.in_(preview.candidate_ids)).all() if preview.candidate_ids else []
            for row in rows:
                if isinstance(row,NvmeLogArchive) and policy.archive_before_delete:
                    if cls._archive_log(row):archived+=1
                    else:continue
                db.delete(row);deleted+=1
            db.commit()
        summary={"resource_type":preview.resource_type,"cutoff":preview.cutoff.isoformat(),"candidates":preview.candidates,"candidate_ids":list(preview.candidate_ids),"reasons":preview.reasons,"archived":archived,"deleted":deleted}
        run=RetentionRun(policy_id=policy.id,mode=mode,candidates=preview.candidates,archived=archived,deleted=deleted,summary_json=json.dumps(summary,ensure_ascii=False))
        db.add(run);policy.last_run_at=cls.now();policy.last_summary_json=json.dumps(summary,ensure_ascii=False);db.commit();db.refresh(run)
        return {"run_id":run.id,"mode":mode,**summary}

    @classmethod
    def candidates_for_all(cls,db:Session)->list[dict[str,Any]]:
        return [{"policy":cls.serialize(policy),"preview":{"candidates":preview.candidates,"candidate_ids":list(preview.candidate_ids),"cutoff":preview.cutoff,"reasons":preview.reasons}} for policy in db.query(RetentionPolicy).filter(RetentionPolicy.enabled.is_(True)).all() for preview in [cls.preview(db,policy)]]

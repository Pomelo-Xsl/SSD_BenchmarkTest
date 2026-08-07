"""性能基线版本、审批和回滚服务。"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.orm import Session
from app.models import BaselineRevision, PerformanceBaseline

class BaselineReviewService:
    VALID={"draft","approved","rejected"}
    @staticmethod
    def data(revision:BaselineRevision)->dict[str,Any]:
        return {"id":revision.id,"baseline_id":revision.baseline_id,"revision_number":revision.revision_number,"metrics":json.loads(revision.metrics_json),"fio_options":json.loads(revision.fio_options_json),"tolerance":json.loads(revision.tolerance_json),"change_reason":revision.change_reason,"approval_status":revision.approval_status,"reviewer_note":revision.reviewer_note,"reviewed_at":revision.reviewed_at,"created_at":revision.created_at}
    @classmethod
    def snapshot(cls,db:Session,baseline:PerformanceBaseline,reason:str)->BaselineRevision:
        latest=db.query(BaselineRevision).filter(BaselineRevision.baseline_id==baseline.id).order_by(BaselineRevision.revision_number.desc()).first()
        revision=BaselineRevision(baseline_id=baseline.id,revision_number=(latest.revision_number if latest else 0)+1,metrics_json=baseline.metrics_json,fio_options_json=baseline.fio_options_json,tolerance_json=baseline.tolerance_json,change_reason=reason.strip() or "保存基线快照")
        db.add(revision);db.commit();db.refresh(revision);return revision
    @classmethod
    def review(cls,db:Session,revision:BaselineRevision,status:str,note:str|None=None)->BaselineRevision:
        if status not in cls.VALID-{"draft"}:raise ValueError("审批状态仅支持 approved 或 rejected")
        revision.approval_status=status;revision.reviewer_note=note;revision.reviewed_at=datetime.now(timezone.utc);db.commit();db.refresh(revision);return revision
    @classmethod
    def rollback(cls,db:Session,baseline:PerformanceBaseline,revision:BaselineRevision)->PerformanceBaseline:
        if revision.baseline_id!=baseline.id:raise ValueError("版本不属于该基线")
        if revision.approval_status!="approved":raise ValueError("仅已批准版本可回滚")
        baseline.metrics_json=revision.metrics_json;baseline.fio_options_json=revision.fio_options_json;baseline.tolerance_json=revision.tolerance_json;db.commit();db.refresh(baseline);return baseline

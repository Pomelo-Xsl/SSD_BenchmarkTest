"""关键操作审计服务。"""
from __future__ import annotations
import json
from typing import Any
from sqlalchemy.orm import Session
from app.models import AuditEvent


class AuditService:
    @staticmethod
    def record(db: Session, event_type: str, target_type: str, message: str, target_id: str | int | None = None, detail: dict[str, Any] | None = None, commit: bool = True) -> AuditEvent:
        event = AuditEvent(event_type=event_type, target_type=target_type, target_id=str(target_id) if target_id is not None else None, message=message, detail_json=json.dumps(detail, ensure_ascii=False, sort_keys=True) if detail else None)
        db.add(event)
        if commit:
            db.commit()
            db.refresh(event)
        return event

    @staticmethod
    def detail(event: AuditEvent) -> dict[str, Any]:
        try:
            return json.loads(event.detail_json or "{}")
        except json.JSONDecodeError:
            return {"raw": event.detail_json}

# utils_audit.py
import json
from flask import g
from compliance.models import db, AuditLog

def audit(action: str, entity: str, entity_id=None, **meta):
    """
    Write an immutable audit row. Use small, stable strings for action/entity.
    Example:
      audit("approve_access", "lab_access", f"{engineer_id}:{lab_id}", status="active")
    """
    row = AuditLog(
        actor_user_id=getattr(g, "user_id", None),
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        meta_json=json.dumps(meta, separators=(",", ":"), ensure_ascii=False) if meta else None,
    )
    db.session.add(row)
    db.session.commit()
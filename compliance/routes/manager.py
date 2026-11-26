from flask import Blueprint, request, redirect, url_for, flash, jsonify
from datetime import date, datetime
from typing import Optional

from compliance.models import (
    db,
    Engineer, Course, Lab, Completion,
    LabRequirement, Document, DocumentAck,
    LabAccess, LabMetrics
)
from compliance.auth_utils import require_roles
from compliance.utils_audit import audit

bp = Blueprint("manager", __name__, url_prefix="/manager")


# ---------------------------
# Helpers
# ---------------------------

def _add_months(d: date, months: int) -> date:
    """Add `months` months to a date (simple month math; ok for compliance windows)."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    # clamp day
    day = min(d.day, [31,
                      29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day)


def _latest_completion(engineer_id: int, course_id: int) -> Optional[Completion]:
    return (
        Completion.query
        .filter_by(engineer_id=engineer_id, course_id=course_id)
        .order_by(Completion.date_taken.desc())
        .first()
    )


def _is_training_current(engineer_id: int, course: Course, override_months: Optional[int],
                         grace_days: int, asof: date) -> bool:
    """
    Returns True if the engineer has a non-expired completion for `course` (considering
    LabRequirement override months if present, else course.valid_months), including lab grace days.
    """
    months = override_months if override_months is not None else course.valid_months
    if not months or months <= 0:
        # If no validity configured at all, treat as not current (manager should define it)
        return False

    comp = _latest_completion(engineer_id, course.id)
    if not comp:
        return False

    due = _add_months(comp.date_taken, months)
    # apply grace days at the lab level
    due_grace = due.toordinal() + grace_days
    return asof.toordinal() <= due_grace


def _has_required_acks(engineer_id: int, lab_id: int) -> bool:
    """All mandatory documents for the lab must be acknowledged at the current version."""
    docs = Document.query.filter_by(lab_id=lab_id, mandatory=True).all()
    if not docs:
        return True
    for d in docs:
        ack = (
            DocumentAck.query
            .filter_by(engineer_id=engineer_id, document_id=d.id, version=d.version)
            .first()
        )
        if not ack:
            return False
    return True


def is_compliant_for_lab(engineer_id: int, lab_id: int, asof: Optional[date] = None) -> bool:
    """
    Compliance = all required courses are current AND all mandatory docs acknowledged.
    """
    asof = asof or date.today()
    lab = Lab.query.get(lab_id)
    if not lab:
        return False

    # Training requirements
    reqs = LabRequirement.query.filter_by(lab_id=lab_id).all()
    for r in reqs:
        course = Course.query.get(r.course_id)
        if not course:
            return False
        if not _is_training_current(engineer_id, course, r.valid_months, lab.grace_days, asof):
            return False

    # Document acknowledgements
    if not _has_required_acks(engineer_id, lab_id):
        return False

    return True


def _ensure_access_state(engineer_id: int, lab_id: int, desired_status: str) -> LabAccess:
    """
    Idempotently set/ensure a single LabAccess row for (engineer, lab) with `desired_status`.
    Removes conflicting states if present.
    """
    # If the exact state exists, return it
    existing = LabAccess.query.filter_by(engineer_id=engineer_id, lab_id=lab_id, status=desired_status).first()
    if existing:
        return existing

    # Otherwise, remove other states for this pair
    LabAccess.query.filter_by(engineer_id=engineer_id, lab_id=lab_id).delete()

    row = LabAccess(engineer_id=engineer_id, lab_id=lab_id, status=desired_status, effective_at=datetime.utcnow())
    db.session.add(row)
    return row


# ---------------------------
# Routes
# ---------------------------

@bp.post("/approve")
@require_roles("manager", "admin")
def approve():
    """
    Manager approval: if the engineer is compliant for the lab, mark ACTIVE; else keep PENDING.
    Accepts form fields: engineer_id, lab_id
    """
    try:
        engineer_id = int(request.form.get("engineer_id", "").strip())
        lab_id = int(request.form.get("lab_id", "").strip())
    except Exception:
        flash("Invalid parameters.", "danger")
        return redirect(url_for("views.home"))

    if is_compliant_for_lab(engineer_id, lab_id):
        _ensure_access_state(engineer_id, lab_id, "active")
        db.session.commit()
        audit("approve_access", "lab_access", f"{engineer_id}:{lab_id}", status="active", mode="manual")
        flash("Access approved (active).", "success")
    else:
        _ensure_access_state(engineer_id, lab_id, "pending")
        db.session.commit()
        audit("approve_access", "lab_access", f"{engineer_id}:{lab_id}", status="pending", reason="not_compliant")
        flash("Engineer not compliant yet; kept as pending.", "warning")

    return redirect(url_for("views.home"))


@bp.post("/revoke")
@require_roles("manager", "admin")
def revoke():
    """
    Explicitly revoke access regardless of compliance.
    Accepts form fields: engineer_id, lab_id
    """
    try:
        engineer_id = int(request.form.get("engineer_id", "").strip())
        lab_id = int(request.form.get("lab_id", "").strip())
    except Exception:
        flash("Invalid parameters.", "danger")
        return redirect(url_for("views.home"))

    _ensure_access_state(engineer_id, lab_id, "revoked")
    db.session.commit()
    audit("revoke_access", "lab_access", f"{engineer_id}:{lab_id}", status="revoked", mode="manual")
    flash("Access revoked.", "info")
    return redirect(url_for("views.home"))


@bp.post("/autocheck")
@require_roles("manager", "admin")
def autocheck():
    """
    Automatic compliance engine:
      - If PENDING and now compliant => ACTIVE
      - If ACTIVE and now NOT compliant => REVOKED
      - REVOKED stays revoked unless manually approved later
    Returns to home with a flash summary.
    """
    changed_active = 0
    changed_revoked = 0

    # Evaluate all engineer/lab relationships that are pending or active
    pairs = (
        db.session.query(LabAccess.engineer_id, LabAccess.lab_id, LabAccess.status)
        .filter(LabAccess.status.in_(["pending", "active"]))
        .all()
    )

    asof = date.today()
    for eng_id, lab_id, status in pairs:
        compliant = is_compliant_for_lab(eng_id, lab_id, asof)

        if status == "pending" and compliant:
            _ensure_access_state(eng_id, lab_id, "active")
            changed_active += 1
            audit("auto_activate", "lab_access", f"{eng_id}:{lab_id}")
        elif status == "active" and not compliant:
            _ensure_access_state(eng_id, lab_id, "revoked")
            changed_revoked += 1
            audit("auto_revoke", "lab_access", f"{eng_id}:{lab_id}", reason="out_of_compliance")

    db.session.commit()
    flash(f"Autocheck done. Activated: {changed_active}, Revoked: {changed_revoked}.", "success")
    return redirect(url_for("views.home"))


@bp.post("/metrics/save")
@require_roles("manager", "admin")
def metrics_save():
    """
    Save a daily metrics snapshot for a lab (utilization/condition/activity in %).
    Accepts form fields: lab_id, utilization, condition, activity, asof(optional YYYY-MM-DD)
    """
    try:
        lab_id = int(request.form.get("lab_id", "").strip())
        util = int(request.form.get("utilization", "0"))
        cond = int(request.form.get("condition", "0"))
        act  = int(request.form.get("activity", "0"))
        asof_str = (request.form.get("asof") or "").strip()
        asof = date.fromisoformat(asof_str) if asof_str else date.today()
    except Exception:
        flash("Invalid metrics parameters.", "danger")
        return redirect(url_for("views.home"))

    # clamp to 0..100
    util = max(0, min(util, 100))
    cond = max(0, min(cond, 100))
    act  = max(0, min(act, 100))

    # Upsert per-day metrics
    row = LabMetrics.query.filter_by(lab_id=lab_id, asof=asof).first()
    if not row:
        row = LabMetrics(lab_id=lab_id, asof=asof, utilization=util, condition=cond, activity=act)
        db.session.add(row)
    else:
        row.utilization = util
        row.condition = cond
        row.activity = act

    db.session.commit()
    audit("save_metrics", "lab_metrics", f"{lab_id}:{asof.isoformat()}",
          utilization=util, condition=cond, activity=act)
    flash("Metrics saved.", "success")
    return redirect(url_for("views.home"))


# Optional JSON endpoints for automation/scripts

@bp.get("/compliance/status")
@require_roles("manager", "admin")
def api_compliance_status():
    """
    Quick JSON view of compliance for all (engineer, lab) pairs that have a LabAccess row.
    """
    rows = LabAccess.query.order_by(LabAccess.engineer_id, LabAccess.lab_id).all()
    out = []
    asof = date.today()
    for r in rows:
        out.append({
            "engineer_id": r.engineer_id,
            "lab_id": r.lab_id,
            "status": r.status,
            "compliant_now": is_compliant_for_lab(r.engineer_id, r.lab_id, asof),
            "effective_at": r.effective_at.isoformat() if r.effective_at else None,
        })
    return jsonify(out)



@bp.get("/dashboard")
@require_roles("manager", "admin")
def dashboard():
    """
    Manager dashboard showing:
    - Pending approvals with compliance indicators
    - Compliance status for active access
    - Expiring training (30-day window)
    - Quick access to reports
    """
    from flask import render_template
    
    # Get all pending requests with compliance check
    pending = LabAccess.query.filter_by(status="pending").all()
    pending_requests = []
    
    engineers_dict = {e.id: e for e in Engineer.query.all()}
    labs_dict = {l.id: l for l in Lab.query.all()}
    courses_dict = {c.id: c for c in Course.query.all()}
    
    today = date.today()
    
    for req in pending:
        eng = engineers_dict.get(req.engineer_id)
        lab = labs_dict.get(req.lab_id)
        
        if not eng or not lab:
            continue
        
        # Check compliance
        compliant = is_compliant_for_lab(req.engineer_id, req.lab_id, today)
        
        # Get specific issues
        training_issues = []
        doc_issues = []
        
        if not compliant:
            # Check training
            reqs = LabRequirement.query.filter_by(lab_id=req.lab_id).all()
            for r in reqs:
                course = courses_dict.get(r.course_id)
                if course and not _is_training_current(
                    req.engineer_id, course, r.valid_months, lab.grace_days, today
                ):
                    training_issues.append(course.code)
            
            # Check documents
            if not _has_required_acks(req.engineer_id, req.lab_id):
                docs = Document.query.filter_by(lab_id=req.lab_id, mandatory=True).all()
                for doc in docs:
                    ack = DocumentAck.query.filter_by(
                        engineer_id=req.engineer_id,
                        document_id=doc.id,
                        version=doc.version
                    ).first()
                    if not ack:
                        doc_issues.append(f"{doc.title} v{doc.version}")
        
        pending_requests.append({
            "engineer_id": req.engineer_id,
            "engineer_name": eng.name,
            "lab_id": req.lab_id,
            "lab_name": lab.name,
            "lab_code": lab.code,
            "requested_at": req.effective_at,
            "is_compliant": compliant,
            "training_issues": training_issues,
            "doc_issues": doc_issues
        })
    
    # Get compliance status for all active access
    active = LabAccess.query.filter_by(status="active").all()
    compliance_status = []
    
    for acc in active:
        eng = engineers_dict.get(acc.engineer_id)
        lab = labs_dict.get(acc.lab_id)
        
        if not eng or not lab:
            continue
        
        compliant = is_compliant_for_lab(acc.engineer_id, acc.lab_id, today)
        
        training_issues = []
        doc_issues = []
        
        if not compliant:
            reqs = LabRequirement.query.filter_by(lab_id=acc.lab_id).all()
            for r in reqs:
                course = courses_dict.get(r.course_id)
                if course and not _is_training_current(
                    acc.engineer_id, course, r.valid_months, lab.grace_days, today
                ):
                    training_issues.append(course.code)
            
            if not _has_required_acks(acc.engineer_id, acc.lab_id):
                docs = Document.query.filter_by(lab_id=acc.lab_id, mandatory=True).all()
                for doc in docs:
                    ack = DocumentAck.query.filter_by(
                        engineer_id=acc.engineer_id,
                        document_id=doc.id,
                        version=doc.version
                    ).first()
                    if not ack:
                        doc_issues.append(f"{doc.title} v{doc.version}")
        
        compliance_status.append({
            "engineer_id": acc.engineer_id,
            "engineer_name": eng.name,
            "lab_id": acc.lab_id,
            "lab_name": lab.name,
            "access_status": acc.status,
            "is_compliant": compliant,
            "training_issues": training_issues,
            "doc_issues": doc_issues
        })
    
    # Get expiring training (30 days)
    expiring_soon = []
    
    # Get all completions
    all_completions = Completion.query.all()
    
    # Track latest completion per engineer/course
    latest_comps = {}
    for comp in all_completions:
        key = (comp.engineer_id, comp.course_id)
        if key not in latest_comps or comp.date_taken > latest_comps[key].date_taken:
            latest_comps[key] = comp
    
    for (eng_id, course_id), comp in latest_comps.items():
        course = courses_dict.get(course_id)
        eng = engineers_dict.get(eng_id)
        
        if not course or not eng or not course.valid_months or course.valid_months <= 0:
            continue
        
        due = _add_months(comp.date_taken, course.valid_months)
        days_left = (due - today).days
        
        if days_left <= 30:  # Include expired and expiring
            expiring_soon.append({
                "engineer_id": eng_id,
                "engineer_name": eng.name,
                "course_id": course_id,
                "course_name": course.name,
                "course_code": course.code,
                "date_taken": comp.date_taken,
                "due_date": due,
                "days_left": days_left
            })
    
    # Sort by days_left (most critical first)
    expiring_soon.sort(key=lambda x: x["days_left"])
    
    # Calculate counts
    active_count = len(active)
    pending_count = len(pending)
    expiring_count = len(expiring_soon)
    non_compliant_count = sum(1 for item in compliance_status if not item["is_compliant"])
    
    # Identify critical: active but non-compliant
    non_compliant_active = [item for item in compliance_status if not item["is_compliant"]]
    for item in non_compliant_active:
        item["issues"] = item["training_issues"] + item["doc_issues"]
    
    return render_template(
        "manager_dashboard.html",
        pending_requests=pending_requests,
        compliance_status=compliance_status,
        expiring_soon=expiring_soon,
        active_count=active_count,
        pending_count=pending_count,
        expiring_count=expiring_count,
        non_compliant_count=non_compliant_count,
        non_compliant_active=non_compliant_active
    )

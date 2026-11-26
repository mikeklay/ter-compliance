from __future__ import annotations

from datetime import datetime
from flask import Blueprint, request, redirect, url_for, flash, render_template, g
from compliance.models import db, LabAccess, Engineer, Lab, User, Document, DocumentAck
from compliance.auth_utils import require_roles
from compliance.utils_audit import audit

bp = Blueprint("engineer", __name__, url_prefix="/engineer")


def _to_int(v: str | None) -> int | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(str(v).strip())
    except ValueError:
        return None


@bp.post("/request-access")
@require_roles("engineer", "manager", "admin")
def request_access():
    """
    Engineers (or managers/admins on their behalf) request access to a lab.
    This creates a 'pending' LabAccess row. Managers can later approve/revoke.
    """
    engineer_id = _to_int(request.form.get("engineer_id"))
    lab_id = _to_int(request.form.get("lab_id"))

    if not engineer_id or not lab_id:
        flash("Engineer ID and Lab ID are required and must be numbers.", "warning")
        return redirect(url_for("views.home"))

    eng = Engineer.query.get(engineer_id)
    lab = Lab.query.get(lab_id)
    if not eng:
        flash(f"Engineer {engineer_id} not found.", "warning")
        return redirect(url_for("views.home"))
    if not lab:
        flash(f"Lab {lab_id} not found.", "warning")
        return redirect(url_for("views.home"))

    la = LabAccess(
        engineer_id=engineer_id,
        lab_id=lab_id,
        status="pending",
        reason_code="requested",
        effective_at=datetime.utcnow(),
    )
    db.session.add(la)
    db.session.commit()

    audit("request_access", "lab_access", f"{engineer_id}:{lab_id}", status="pending")
    flash(f"Access request submitted for {eng.name} → {lab.name}.", "success")
    return redirect(url_for("views.home"))


@bp.post("/cancel-request")
@require_roles("engineer", "manager", "admin")
def cancel_request():
    """
    Mark the latest pending request as revoked by user.
    """
    engineer_id = _to_int(request.form.get("engineer_id"))
    lab_id = _to_int(request.form.get("lab_id"))

    if not engineer_id or not lab_id:
        flash("Engineer ID and Lab ID are required and must be numbers.", "warning")
        return redirect(url_for("views.home"))

    row = (
        LabAccess.query
        .filter_by(engineer_id=engineer_id, lab_id=lab_id, status="pending")
        .order_by(LabAccess.effective_at.desc())
        .first()
    )
    if not row:
        flash("No pending request found to cancel.", "warning")
        return redirect(url_for("views.home"))

    row.status = "revoked"
    row.reason_code = "user_cancelled"
    row.effective_at = datetime.utcnow()
    db.session.commit()

    audit("cancel_request", "lab_access", f"{engineer_id}:{lab_id}", status="revoked")
    flash("Pending request cancelled.", "success")
    return redirect(url_for("views.home"))


# ------------------------------------------------------------------------------
# Engineer Self-Service Document Acknowledgment
# ------------------------------------------------------------------------------

@bp.post("/acknowledge/<int:document_id>")
@require_roles("engineer", "manager", "admin")
def acknowledge_document(document_id):
    """
    Engineer acknowledges a document (must be linked to an Engineer record).
    Creates a DocumentAck record for the current version.
    """
    # Get the authenticated user
    user = User.query.get(g.user_id)
    if not user or not user.engineer_id:
        flash("You must be linked to an engineer record to acknowledge documents.", "danger")
        return redirect(url_for("engineer.documents"))
    
    # Get the document
    doc = Document.query.get_or_404(document_id)
    
    # Check if already acknowledged this version
    existing = DocumentAck.query.filter_by(
        engineer_id=user.engineer_id,
        document_id=document_id,
        version=doc.version
    ).first()
    
    if existing:
        flash(f"You already acknowledged {doc.title} v{doc.version} on {existing.acked_at.strftime('%Y-%m-%d')}", "info")
    else:
        ack = DocumentAck(
            engineer_id=user.engineer_id,
            document_id=document_id,
            version=doc.version,
            acked_at=datetime.utcnow()
        )
        db.session.add(ack)
        db.session.commit()
        
        audit("engineer_acknowledge", "document_ack", 
              f"{user.engineer_id}:{document_id}:{doc.version}",
              document_title=doc.title)
        
        flash(f"✓ Successfully acknowledged {doc.title} v{doc.version}", "success")
    
    return redirect(url_for("engineer.documents"))


@bp.get("/documents")
@require_roles("engineer", "manager", "admin")
def documents():
    """
    Show engineer their required documents and acknowledgment status.
    Only shows mandatory documents for labs they have pending/active access to.
    """
    user = User.query.get(g.user_id)
    if not user or not user.engineer_id:
        flash("You must be linked to an engineer record to view documents.", "danger")
        return redirect(url_for("views.home"))
    
    engineer = Engineer.query.get(user.engineer_id)
    
    # Find labs this engineer has pending or active access to
    access_records = LabAccess.query.filter_by(
        engineer_id=user.engineer_id
    ).filter(
        LabAccess.status.in_(["pending", "active"])
    ).all()
    
    lab_ids = [a.lab_id for a in access_records]
    labs_dict = {l.id: l for l in Lab.query.filter(Lab.id.in_(lab_ids)).all()} if lab_ids else {}
    
    # Get all mandatory documents for those labs
    documents_query = Document.query.filter(
        Document.lab_id.in_(lab_ids),
        Document.mandatory == True
    ).order_by(Document.lab_id, Document.title).all() if lab_ids else []
    
    # Get all acknowledgments for this engineer
    doc_acks = DocumentAck.query.filter_by(
        engineer_id=user.engineer_id
    ).all()
    
    ack_map = {(a.document_id, a.version): a for a in doc_acks}
    
    # Build document list with status
    doc_list = []
    for doc in documents_query:
        acked = ack_map.get((doc.id, doc.version))
        lab = labs_dict.get(doc.lab_id)
        doc_list.append({
            "doc": doc,
            "lab": lab,
            "acked": acked,
            "needs_ack": not acked,
            "is_current_version": True
        })
    
    # Count statistics
    total_docs = len(doc_list)
    acknowledged_count = sum(1 for d in doc_list if d["acked"])
    pending_count = total_docs - acknowledged_count
    
    return render_template(
        "engineer_documents.html",
        engineer=engineer,
        documents=doc_list,
        total_docs=total_docs,
        acknowledged_count=acknowledged_count,
        pending_count=pending_count,
        access_records=access_records,
        labs_dict=labs_dict
    )


@bp.get("/dashboard")
@require_roles("engineer", "manager", "admin")
def dashboard():
    """
    Engineer dashboard showing:
    - Access requests status
    - Training status
    - Documents requiring acknowledgment
    """
    from compliance.models import Completion, Course, LabRequirement
    from datetime import date, timedelta
    
    user = User.query.get(g.user_id)
    if not user or not user.engineer_id:
        flash("You must be linked to an engineer record.", "danger")
        return redirect(url_for("views.home"))
    
    engineer = Engineer.query.get(user.engineer_id)
    
    # Get access requests
    access_records = LabAccess.query.filter_by(
        engineer_id=user.engineer_id
    ).order_by(LabAccess.effective_at.desc()).all()
    
    labs_dict = {l.id: l for l in Lab.query.all()}
    
    # Helper function to add months
    def _add_months(d: date, months: int) -> date:
        y = d.year + (d.month - 1 + months) // 12
        m = (d.month - 1 + months) % 12 + 1
        dim = [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
               31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
        return date(y, m, min(d.day, dim))
    
    # Get training completions with expiration info
    completions = Completion.query.filter_by(
        engineer_id=user.engineer_id
    ).order_by(Completion.date_taken.desc()).all()
    
    courses_dict = {c.id: c for c in Course.query.all()}
    today = date.today()
    
    training_list = []
    for comp in completions:
        course = courses_dict.get(comp.course_id)
        if not course:
            continue
        
        # Calculate expiration
        if course.valid_months and course.valid_months > 0:
            due_date = _add_months(comp.date_taken, course.valid_months)
            days_left = (due_date - today).days
            
            if days_left < 0:
                status = "expired"
                status_class = "danger"
            elif days_left <= 30:
                status = "expiring_soon"
                status_class = "warning"
            else:
                status = "current"
                status_class = "success"
        else:
            due_date = None
            days_left = None
            status = "no_expiration"
            status_class = "secondary"
        
        training_list.append({
            "completion": comp,
            "course": course,
            "due_date": due_date,
            "days_left": days_left,
            "status": status,
            "status_class": status_class
        })
    
    # Get documents requiring acknowledgment
    lab_ids = [a.lab_id for a in access_records if a.status in ["pending", "active"]]
    pending_docs = []
    
    if lab_ids:
        docs = Document.query.filter(
            Document.lab_id.in_(lab_ids),
            Document.mandatory == True
        ).all()
        
        doc_acks = DocumentAck.query.filter_by(
            engineer_id=user.engineer_id
        ).all()
        ack_map = {(a.document_id, a.version): a for a in doc_acks}
        
        for doc in docs:
            if not ack_map.get((doc.id, doc.version)):
                lab = labs_dict.get(doc.lab_id)
                pending_docs.append({
                    "doc": doc,
                    "lab": lab
                })
    
    return render_template(
        "engineer_dashboard.html",
        engineer=engineer,
        access_records=access_records,
        labs_dict=labs_dict,
        training_list=training_list,
        pending_docs=pending_docs
    )
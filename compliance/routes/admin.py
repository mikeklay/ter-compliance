from __future__ import annotations

import os
import re
import csv
from datetime import datetime, date, timedelta
from io import StringIO

from flask import (
    Blueprint, request, redirect, url_for, flash, Response
)
from sqlalchemy.exc import IntegrityError

from compliance.models import (
    db,
    Engineer, Course, Lab, Completion,
    LabRequirement, Document, DocumentAck,
    LabAccess
)
from compliance.s3util import s3_upload_bytes, s3_presign_get
from compliance.auth_utils import require_roles

bp = Blueprint("admin", __name__)

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

def _to_int(value: str | None, field: str, allow_empty: bool = False) -> int | None:
    """Safe int converter with user-friendly messages via flash."""
    if value is None or value == "":
        if allow_empty:
            return None
        flash(f"'{field}' is required.", "warning")
        raise ValueError(field)
    try:
        return int(str(value).strip())
    except ValueError:
        flash(f"'{field}' must be a whole number.", "warning")
        raise

def _required_str(value: str | None, field: str) -> str:
    v = (value or "").strip()
    if not v:
        flash(f"'{field}' is required.", "warning")
        raise ValueError(field)
    return v

def _commit_ok(success_msg: str, duplicate_msg: str | None = None) -> bool:
    """Try to commit and show duplicate-friendly message on IntegrityError."""
    try:
        db.session.commit()
        flash(success_msg, "success")
        return True
    except IntegrityError:
        db.session.rollback()
        flash(duplicate_msg or "Duplicate or invalid data.", "warning")
        return False

_fname_pat = re.compile(r"[^A-Za-z0-9._-]+")

def _safe_filename(name: str) -> str:
    """Minimal filename sanitizer for S3 object keys."""
    name = os.path.basename(name)
    name = _fname_pat.sub("_", name).strip("._-")
    return name or "file"

def _upload_fileobj(fs_file, *, prefix: str) -> str:
    """
    Read a Werkzeug FileStorage and upload to S3, returning the S3 key.
    Names object with UTC timestamp + sanitized base name.
    """
    raw = fs_file.read()
    if not raw:
        raise RuntimeError("Empty file.")
    base = _safe_filename(fs_file.filename or "file")
    key = f"{prefix}/{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}_{base}"
    content_type = fs_file.mimetype or "application/octet-stream"
    s3_upload_bytes(key, raw, content_type=content_type)
    return key

def _add_months(d: date, months: int) -> date:
    """Add months to a date (handles month-length variations)."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    dim = [31,
           29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
           31,30,31,30,31,31,30,31,30,31][m-1]
    return date(y, m, min(d.day, dim))

def _csv_response(rows, filename: str) -> Response:
    sio = StringIO()
    w = csv.writer(sio)
    for r in rows:
        w.writerow(r)
    data = sio.getvalue()
    return Response(
        data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ------------------------------------------------------------------------------
# Engineers
# ------------------------------------------------------------------------------

@bp.post("/engineer")
@require_roles("admin")
def add_engineer():
    """Add a new engineer (employee_no and email must be unique)."""
    try:
        employee_no = _required_str(request.form.get("employee_no"), "Employee #")
        name        = _required_str(request.form.get("name"), "Full name")
        email       = _required_str(request.form.get("email"), "Email")
    except ValueError:
        return redirect(url_for("views.home"))

    e = Engineer(employee_no=employee_no, name=name, email=email)
    db.session.add(e)
    _commit_ok(
        "Engineer added.",
        "Engineer not added. Duplicate employee number or email.",
    )
    return redirect(url_for("views.home"))

# ------------------------------------------------------------------------------
# Labs
# ------------------------------------------------------------------------------

@bp.post("/lab")
@require_roles("admin")
def add_lab():
    """Add a lab (code must be unique)."""
    try:
        code       = _required_str(request.form.get("code"), "Lab code")
        name       = _required_str(request.form.get("name"), "Lab name")
        grace_days = _to_int(request.form.get("grace_days", "0"), "Grace days", allow_empty=True) or 0
        if grace_days < 0:
            flash("Grace days cannot be negative.", "warning")
            return redirect(url_for("views.home"))
    except ValueError:
        return redirect(url_for("views.home"))

    lab = Lab(code=code, name=name, grace_days=grace_days)
    db.session.add(lab)
    _commit_ok("Lab added.", f"Lab code '{code}' already exists.")
    return redirect(url_for("views.home"))

# ------------------------------------------------------------------------------
# Courses
# ------------------------------------------------------------------------------

@bp.post("/course")
@require_roles("admin")
def add_course():
    """Add a course (code must be unique)."""
    try:
        code         = _required_str(request.form.get("code"), "Course code")
        name         = _required_str(request.form.get("name"), "Course name")
        valid_months = _to_int(request.form.get("valid_months", "12"), "Validity months", allow_empty=True) or 12
        if valid_months <= 0:
            flash("Validity months must be greater than 0.", "warning")
            return redirect(url_for("views.home"))
    except ValueError:
        return redirect(url_for("views.home"))

    c = Course(code=code, name=name, valid_months=valid_months)
    db.session.add(c)
    _commit_ok("Course added.", f"Course code '{code}' already exists.")
    return redirect(url_for("views.home"))

# ------------------------------------------------------------------------------
# Requirements (Lab ↔ Course)
# ------------------------------------------------------------------------------

@bp.post("/requirement")
@require_roles("admin")
def add_requirement():
    """Upsert a course requirement for a lab (with optional validity override)."""
    try:
        lab_id       = _to_int(request.form.get("lab_id"), "Lab ID")
        course_id    = _to_int(request.form.get("course_id"), "Course ID")
        valid_months = _to_int(request.form.get("valid_months"), "Override months", allow_empty=True)
        if valid_months is not None and valid_months <= 0:
            flash("Override months must be greater than 0.", "warning")
            return redirect(url_for("views.home"))
    except ValueError:
        return redirect(url_for("views.home"))

    r = LabRequirement(lab_id=lab_id, course_id=course_id, valid_months=valid_months)
    db.session.merge(r)
    _commit_ok("Requirement saved.")
    return redirect(url_for("views.home"))

# ------------------------------------------------------------------------------
# Training Completions (with optional certificate upload)
# ------------------------------------------------------------------------------

@bp.post("/completion")
@require_roles("admin")
def add_completion():
    """
    Record a course completion for an engineer.
    Optionally attach a certificate file (S3) or legacy URL.
    """
    try:
        engineer_id = _to_int(request.form.get("engineer_id"), "Engineer ID")
        course_id   = _to_int(request.form.get("course_id"), "Course ID")
        date_str    = _required_str(request.form.get("date_taken"), "Date taken (YYYY-MM-DD)")
        try:
            date_taken = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Date taken must be in YYYY-MM-DD format.", "warning")
            return redirect(url_for("views.home"))
    except ValueError:
        return redirect(url_for("views.home"))

    cert_key = None
    fs = request.files.get("certificate_file")
    if fs and fs.filename:
        try:
            cert_key = _upload_fileobj(fs, prefix=f"certs/eng-{engineer_id}")
        except RuntimeError as e:
            flash(f"Certificate not uploaded: {e}", "warning")

    certificate_url = (request.form.get("certificate_url") or "").strip() or None

    c = Completion(
        engineer_id=engineer_id,
        course_id=course_id,
        date_taken=date_taken,
        s3_key=cert_key,
        certificate_url=certificate_url,
    )
    db.session.add(c)
    _commit_ok("Completion recorded.")
    return redirect(url_for("views.home"))

# ------------------------------------------------------------------------------
# Secure Certificate Download (presigned S3)
# ------------------------------------------------------------------------------

@bp.get("/completion/download")
@require_roles("admin", "manager")
def completion_download():
    """Redirect to a presigned S3 URL for a completion certificate."""
    comp_id_str = request.args.get("completion_id")
    try:
        comp_id = _to_int(comp_id_str, "Completion ID")
    except ValueError:
        return redirect(url_for("views.home"))

    c = Completion.query.get(comp_id)
    if not c:
        flash("Completion not found.", "warning")
        return redirect(url_for("views.home"))

    if not c.s3_key:
        flash("No certificate file for this completion.", "warning")
        return redirect(url_for("views.home"))

    try:
        url = s3_presign_get(c.s3_key, expires_in=300)  
    except Exception as e:
        flash(f"Could not generate download link: {e}", "warning")
        return redirect(url_for("views.home"))

    return redirect(url)

# ------------------------------------------------------------------------------
# Documents & Acknowledgements
# ------------------------------------------------------------------------------

@bp.post("/document")
@require_roles("admin")
def add_document():
    """
    Add or update a lab document (optionally upload a file to S3).
    """
    try:
        lab_id   = _to_int(request.form.get("lab_id"), "Lab ID")
        title    = _required_str(request.form.get("title"), "Document title")
        version  = _to_int(request.form.get("version", "1"), "Version", allow_empty=True) or 1
        mandatory_raw = (request.form.get("mandatory", "1") or "1").strip()
        mandatory = bool(int(mandatory_raw))
    except ValueError:
        return redirect(url_for("views.home"))

    s3_key = None
    fs = request.files.get("file")
    if fs and fs.filename:
        try:
            s3_key = _upload_fileobj(fs, prefix=f"docs/lab-{lab_id}")
        except RuntimeError as e:
            flash(f"Document file not uploaded: {e}", "warning")

    d = Document(lab_id=lab_id, title=title, version=version, mandatory=mandatory, s3_key=s3_key)
    db.session.add(d)
    _commit_ok("Document added.")
    return redirect(url_for("views.home"))

# ------------------------------------------------------------------------------
# Secure Document Download (presigned S3)
# ------------------------------------------------------------------------------

@bp.get("/document/download")
@require_roles("admin", "manager")
def document_download():
    """Redirect to a presigned S3 URL for a document file."""
    doc_id_str = request.args.get("document_id")
    try:
        doc_id = _to_int(doc_id_str, "Document ID")
    except ValueError:
        return redirect(url_for("views.home"))

    d = Document.query.get(doc_id)
    if not d:
        flash("Document not found.", "warning")
        return redirect(url_for("views.home"))

    if not d.s3_key:
        flash("This document has no file.", "warning")
        return redirect(url_for("views.home"))

    try:
        url = s3_presign_get(d.s3_key, expires_in=300)  
    except Exception as e:
        flash(f"Could not generate download link: {e}", "warning")
        return redirect(url_for("views.home"))

    return redirect(url)

# ------------------------------------------------------------------------------
# Acknowledge Document 
# ------------------------------------------------------------------------------

@bp.post("/ack")
@require_roles("admin")
def ack_document():
    """Record that an engineer has read/acknowledged a specific document version."""
    try:
        engineer_id = _to_int(request.form.get("engineer_id"), "Engineer ID")
        document_id = _to_int(request.form.get("document_id"), "Document ID")
        version     = _to_int(request.form.get("version"), "Version")
    except ValueError:
        return redirect(url_for("views.home"))

    a = DocumentAck(
        engineer_id=engineer_id,
        document_id=document_id,
        version=version,
        acked_at=datetime.utcnow(),
    )
    db.session.add(a)
    _commit_ok("Acknowledgment captured.", "Already acknowledged this version.")
    return redirect(url_for("views.home"))


# ------------------------------------------------------------------------------
# CSV Reports
# ------------------------------------------------------------------------------

@bp.get("/reports/active.csv")
@require_roles("admin", "manager")
def report_active_csv():
    """Export active access rows with engineer & lab names."""
    rows = [("generated_at_utc", "engineer_id", "engineer_name", "lab_id", "lab", "since_utc")]
    q = (db.session.query(LabAccess, Engineer, Lab)
         .join(Engineer, Engineer.id == LabAccess.engineer_id)
         .join(Lab, Lab.id == LabAccess.lab_id)
         .filter(LabAccess.status == "active")
         .order_by(LabAccess.effective_at.desc()))
    now = datetime.utcnow().isoformat(timespec="seconds")
    for acc, eng, lab in q.all():
        rows.append((
            now,
            eng.id,
            eng.name,
            lab.id,
            f"{lab.name} ({lab.code})",
            acc.effective_at
        ))
    return _csv_response(rows, "active_access.csv")

@bp.get("/reports/pending.csv")
@require_roles("admin", "manager")
def report_pending_csv():
    """Export pending access rows with engineer & lab names."""
    rows = [("generated_at_utc", "engineer_id", "engineer_name", "lab_id", "lab", "requested_utc")]
    q = (db.session.query(LabAccess, Engineer, Lab)
         .join(Engineer, Engineer.id == LabAccess.engineer_id)
         .join(Lab, Lab.id == LabAccess.lab_id)
         .filter(LabAccess.status == "pending")
         .order_by(LabAccess.effective_at.desc()))
    now = datetime.utcnow().isoformat(timespec="seconds")
    for acc, eng, lab in q.all():
        rows.append((
            now,
            eng.id,
            eng.name,
            lab.id,
            f"{lab.name} ({lab.code})",
            acc.effective_at
        ))
    return _csv_response(rows, "pending_access.csv")

@bp.get("/reports/expiring30.csv")
@require_roles("admin", "manager")
def report_expiring_30_csv():
    """
    Export latest completion per (engineer, course) whose due date is within 30 days.
    """
    today = date.today()
    rows = [("generated_at_utc", "engineer_id", "engineer_name",
             "course_id", "course_code", "taken", "due", "days_left")]

    course_by_id = {c.id: c for c in Course.query.all()}
    eng_by_id    = {e.id: e for e in Engineer.query.all()}

    latest: dict[tuple[int, int], Completion] = {}
    comps = Completion.query.order_by(
        Completion.engineer_id.asc(),
        Completion.course_id.asc(),
        Completion.date_taken.desc()
    ).all()
    for c in comps:
        key = (c.engineer_id, c.course_id)
        if key not in latest:
            latest[key] = c

    now = datetime.utcnow().isoformat(timespec="seconds")
    for (eid, cid), comp in latest.items():
        course = course_by_id.get(cid)
        months = course.valid_months if course else None
        if not months or months <= 0:
            continue
        due = _add_months(comp.date_taken, int(months))
        days = (due - today).days
        if days <= 30:
            rows.append((
                now,
                eid,
                eng_by_id[eid].name if eid in eng_by_id else eid,
                cid,
                course.code if course else cid,
                comp.date_taken.isoformat(),
                due.isoformat(),
                days,
            ))

    return _csv_response(rows, "expiring_30_days.csv")

@bp.get("/reports/access.csv")
@require_roles("admin", "manager")
def report_access_csv():
    """Export all access records (any status) with engineer & lab names."""
    sio = StringIO()
    w = csv.writer(sio)
    w.writerow(["generated_at_utc", "engineer_id", "engineer_name",
                "lab_id", "lab", "status", "reason_code", "effective_at_utc"])

    now = datetime.utcnow().isoformat(timespec="seconds")
    q = (db.session.query(LabAccess, Engineer, Lab)
         .join(Engineer, Engineer.id == LabAccess.engineer_id)
         .join(Lab, Lab.id == LabAccess.lab_id)
         .order_by(LabAccess.effective_at.desc()))
    for acc, eng, lab in q.all():
        w.writerow([
            now,
            eng.id,
            eng.name,
            lab.id,
            f"{lab.name} ({lab.code})",
            acc.status,
            getattr(acc, 'reason_code', '') or "",
            acc.effective_at or "",
        ])

    return Response(sio.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=access_all_statuses.csv"})

@bp.get("/reports/completions.csv")
@require_roles("admin", "manager")
def report_completions_csv():
    """All course completions with taken date, due date, days left, and cert info."""
    courses = {c.id: c for c in Course.query.all()}
    engs = {e.id: e for e in Engineer.query.all()}
    
    today = date.today()
    rows = Completion.query.order_by(Completion.date_taken.desc()).all()

    out = StringIO()
    w = csv.writer(out)
    w.writerow([
        "engineer_id", "engineer_name", "course_id", "course_code",
        "date_taken", "due_date", "days_left",
        "certificate_url", "certificate_s3_key"
    ])

    for c in rows:
        course = courses.get(c.course_id)
        months = (course.valid_months or 0) if course else 0
        due = _add_months(c.date_taken, months) if months > 0 else None
        days_left = (due - today).days if due else None
        e = engs.get(c.engineer_id)

        w.writerow([
            c.engineer_id,
            (e.name if e else ""),
            c.course_id,
            (course.code if course else ""),
            c.date_taken.isoformat() if c.date_taken else "",
            due.isoformat() if due else "",
            "" if days_left is None else days_left,
            c.certificate_url or "",
            (c.s3_key or ""),
        ])

    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=completions.csv"})


@bp.get("/reports/doc_acks.csv")
@require_roles("admin", "manager")
def report_doc_acks_csv():
    """All document acknowledgements with engineer, document, version, and timestamp."""
    out = StringIO()
    w = csv.writer(out)
    w.writerow(["engineer_id", "engineer_name", "document_id", "title", 
                "lab_id", "version", "acknowledged_at"])

    engs = {e.id: e for e in Engineer.query.all()}
    docs = {d.id: d for d in Document.query.all()}

    for a in DocumentAck.query.order_by(DocumentAck.acked_at.desc()).all():
        e = engs.get(a.engineer_id)
        d = docs.get(a.document_id)
        w.writerow([
            a.engineer_id,
            (e.name if e else ""),
            a.document_id,
            (d.title if d else ""),
            (d.lab_id if d else ""),
            a.version,
            a.acked_at.isoformat() if a.acked_at else "",
        ])

    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=document_acknowledgements.csv"})


@bp.get("/reports/compliance_status.csv")
@require_roles("admin", "manager")
def report_compliance_status_csv():
    """
    Export current compliance status with detailed issues breakdown.
    Shows training gaps and missing document acknowledgments.
    """
    sio = StringIO()
    w = csv.writer(sio)
    w.writerow([
        "engineer_id", "engineer_name", "lab_id", "lab_name", 
        "access_status", "training_issues", "document_issues"
    ])
    
    # Get all access records
    access_records = LabAccess.query.filter(
        LabAccess.status.in_(["pending", "active"])
    ).all()
    
    engineers = {e.id: e for e in Engineer.query.all()}
    labs = {l.id: l for l in Lab.query.all()}
    courses = {c.id: c for c in Course.query.all()}
    
    today = date.today()
    
    for acc in access_records:
        eng = engineers.get(acc.engineer_id)
        lab = labs.get(acc.lab_id)
        
        if not eng or not lab:
            continue
        
        # Get training issues
        training_issues = []
        reqs = LabRequirement.query.filter_by(lab_id=acc.lab_id).all()
        for req in reqs:
            course = courses.get(req.course_id)
            if not course:
                continue
                
            # Find latest completion
            comp = Completion.query.filter_by(
                engineer_id=acc.engineer_id,
                course_id=course.id
            ).order_by(Completion.date_taken.desc()).first()
            
            if not comp:
                training_issues.append(f"{course.code} (not completed)")
            else:
                # Check if expired
                valid_months = req.valid_months if req.valid_months else course.valid_months
                if valid_months and valid_months > 0:
                    expire_days = valid_months * 30
                    expires = comp.date_taken + timedelta(days=expire_days)
                    grace_expires = expires + timedelta(days=lab.grace_days)
                    if today > grace_expires:
                        training_issues.append(f"{course.code} (expired)")
        
        # Get document issues
        doc_issues = []
        docs = Document.query.filter_by(lab_id=acc.lab_id, mandatory=True).all()
        for doc in docs:
            ack = DocumentAck.query.filter_by(
                engineer_id=acc.engineer_id,
                document_id=doc.id,
                version=doc.version
            ).first()
            if not ack:
                doc_issues.append(f"{doc.title} v{doc.version}")
        
        w.writerow([
            acc.engineer_id,
            eng.name,
            acc.lab_id,
            lab.name,
            acc.status,
            "; ".join(training_issues) if training_issues else "None",
            "; ".join(doc_issues) if doc_issues else "None"
        ])
    
    return Response(
        sio.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=compliance_status.csv"}
    )
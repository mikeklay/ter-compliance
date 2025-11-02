from datetime import date
from flask import Blueprint, render_template, session, g
from compliance.models import (
    db,
    Engineer, Course, Lab, Completion,
    LabRequirement, Document, DocumentAck,
    LabAccess, LabMetrics
)

bp = Blueprint("views", __name__)

# ---------- Jinja filters ----------

@bp.app_template_filter("days_left")
def _days_left(due: date | None) -> int | None:
    if not due:
        return None
    return (due - date.today()).days

@bp.app_template_filter("days_badge")
def _days_badge(days: int | None) -> str:
    if days is None:
        return '<span class="badge text-bg-secondary">n/a</span>'
    if days < 0:
        return f'<span class="badge text-bg-danger">{days}d</span>'
    if days <= 30:
        return f'<span class="badge text-bg-warning">{days}d</span>'
    return f'<span class="badge text-bg-success">{days}d</span>'

# ---------- Helpers ----------

def _add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    dim = [31,
           29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
           31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    day = min(d.day, dim)
    return date(y, m, day)

def current_access_rows(status: str):
    return (
        LabAccess.query
        .filter_by(status=status)
        .order_by(LabAccess.effective_at.desc())
        .all()
    )

def labs_by_id():
    labs = Lab.query.order_by(Lab.name.asc()).all()
    return {l.id: l for l in labs}, labs

def engineers_by_id():
    engs = Engineer.query.order_by(Engineer.name.asc()).all()
    return {e.id: e for e in engs}

def latest_metrics_by_lab():
    out = {}
    rows = LabMetrics.query.order_by(LabMetrics.lab_id.asc(), LabMetrics.asof.desc()).all()
    for r in rows:
        if r.lab_id not in out:
            out[r.lab_id] = r
    return out

def documents_all():
    try:
        return Document.query.order_by(Document.uploaded_at.desc()).all()
    except Exception:
        return Document.query.order_by(Document.id.desc()).all()

def completions_all():
    try:
        return Completion.query.order_by(Completion.date_taken.desc()).all()
    except Exception:
        return Completion.query.order_by(Completion.id.desc()).all()

# ---------- Route ----------

@bp.route("/")
def home():
    # Access sections
    active = current_access_rows(status="active")
    pending = current_access_rows(status="pending")

    # Lookups
    lab_by_id, labs = labs_by_id()
    eng_by_id = engineers_by_id()
    courses = Course.query.order_by(Course.code.asc()).all()
    course_by_id = {c.id: c for c in courses}

    # Metrics & resources
    latest_metrics = latest_metrics_by_lab()
    documents = documents_all()
    completions = completions_all()

    # Build due_map: (engineer_id, course_id) -> {due, days}
    due_map: dict[tuple[int, int], dict] = {}
    today = date.today()
    for c in completions:
        months = None
        course = course_by_id.get(c.course_id)
        if course and (course.valid_months or course.valid_months == 0):
            months = int(course.valid_months)

        if months and months > 0:
            due = _add_months(c.date_taken, months)
            days = (due - today).days
        else:
            due, days = None, None

        due_map[(c.engineer_id, c.course_id)] = {"due": due, "days": days}

    # Get current role from g (set by before_request in __init__.py)
    session_role = getattr(g, 'role', 'engineer')
    session_email = getattr(g, 'user_email', None)

    return render_template(
        "home.html",
        active=active,
        pending=pending,
        lab_by_id=lab_by_id,
        labs=labs,
        eng_by_id=eng_by_id,
        latest_metrics=latest_metrics,
        documents=documents,
        completions=completions,
        courses=courses,
        due_map=due_map,
        today=today,
        session_role=session_role,
        session_email=session_email,
    )
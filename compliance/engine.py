"""
Compliance engine: the rules that decide whether an engineer may enter a lab.

An engineer is compliant for a lab when
  1. every course the lab requires has a completion that is still current, using the
     lab's override validity (LabRequirement.valid_months) when set, otherwise the
     course default, extended by the lab's grace period; and
  2. every mandatory lab document is acknowledged at its *current* version.

Anything unknown or misconfigured (missing lab, missing course, no validity period)
fails closed. These functions have no web dependencies, so they can be tested and
reused outside the Flask routes.
"""
import calendar
from datetime import date
from typing import Optional

from compliance.models import Course, Completion, Document, DocumentAck, Lab, LabRequirement


def add_months(d: date, months: int) -> date:
    """Add calendar months, clamping to the last day of a shorter month (Jan 31 + 1 -> Feb 28/29)."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def latest_completion(engineer_id: int, course_id: int) -> Optional[Completion]:
    return (
        Completion.query
        .filter_by(engineer_id=engineer_id, course_id=course_id)
        .order_by(Completion.date_taken.desc())
        .first()
    )


def is_training_current(engineer_id: int, course: Course, override_months: Optional[int],
                        grace_days: int, asof: date) -> bool:
    """True if the engineer's latest completion of `course` is unexpired on `asof`, including grace days."""
    months = override_months if override_months is not None else course.valid_months
    if not months or months <= 0:
        # No validity configured: treat as not current (an admin must define it)
        return False

    comp = latest_completion(engineer_id, course.id)
    if not comp:
        return False

    due = add_months(comp.date_taken, months)
    return asof.toordinal() <= due.toordinal() + grace_days


def has_required_acks(engineer_id: int, lab_id: int) -> bool:
    """All mandatory documents for the lab must be acknowledged at the current version."""
    for d in Document.query.filter_by(lab_id=lab_id, mandatory=True).all():
        ack = (
            DocumentAck.query
            .filter_by(engineer_id=engineer_id, document_id=d.id, version=d.version)
            .first()
        )
        if not ack:
            return False
    return True


def is_compliant_for_lab(engineer_id: int, lab_id: int, asof: Optional[date] = None) -> bool:
    """Compliance = all required courses current AND all mandatory documents acknowledged."""
    asof = asof or date.today()
    lab = Lab.query.get(lab_id)
    if not lab:
        return False

    for r in LabRequirement.query.filter_by(lab_id=lab_id).all():
        course = Course.query.get(r.course_id)
        if not course:
            return False
        if not is_training_current(engineer_id, course, r.valid_months, lab.grace_days, asof):
            return False

    return has_required_acks(engineer_id, lab_id)

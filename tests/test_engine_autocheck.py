"""
Compliance engine edge cases and the automated autocheck state machine.

Edge cases: a course with no validity period, an unknown lab, and a requirement
that points at a deleted course must all fail closed (not compliant).

Autocheck: PENDING + compliant -> ACTIVE, ACTIVE + not compliant -> REVOKED,
REVOKED stays revoked until a manager approves again.
"""
from datetime import date, timedelta

from compliance.models import db, Course, Completion, LabAccess, LabRequirement, AuditLog
from compliance.engine import add_months, is_compliant_for_lab


def _status(engineer_id, lab_id):
    rows = LabAccess.query.filter_by(engineer_id=engineer_id, lab_id=lab_id).all()
    assert len(rows) == 1, "exactly one access row per engineer/lab"
    return rows[0].status


def _add_access(engineer_id, lab_id, status):
    db.session.add(LabAccess(engineer_id=engineer_id, lab_id=lab_id, status=status))
    db.session.commit()


# ---------------------------------------------------------------------------
# Engine edge cases: every unknown or misconfigured input fails closed
# ---------------------------------------------------------------------------

def test_course_without_validity_period_is_not_current(app, sample_engineer, sample_lab):
    with app.app_context():
        course = Course(code='NOVAL-1', name='No validity set', valid_months=0)
        db.session.add(course)
        db.session.flush()
        db.session.add(LabRequirement(lab_id=sample_lab, course_id=course.id, valid_months=None))
        db.session.add(Completion(engineer_id=sample_engineer, course_id=course.id,
                                  date_taken=date.today() - timedelta(days=1)))
        db.session.commit()

        assert not is_compliant_for_lab(sample_engineer, sample_lab)


def test_unknown_lab_is_not_compliant(app, sample_engineer):
    with app.app_context():
        assert not is_compliant_for_lab(sample_engineer, 99999)


def test_requirement_for_missing_course_is_not_compliant(app, sample_engineer, sample_lab):
    with app.app_context():
        db.session.add(LabRequirement(lab_id=sample_lab, course_id=99999))
        db.session.commit()

        assert not is_compliant_for_lab(sample_engineer, sample_lab)


def test_lab_override_shortens_course_validity(app, sample_engineer, sample_lab, sample_course):
    """A lab can require more recent training than the course default (12 months)."""
    with app.app_context():
        db.session.add(LabRequirement(lab_id=sample_lab, course_id=sample_course, valid_months=3))
        db.session.add(Completion(engineer_id=sample_engineer, course_id=sample_course,
                                  date_taken=date.today() - timedelta(days=180)))
        db.session.commit()

        assert not is_compliant_for_lab(sample_engineer, sample_lab)


# ---------------------------------------------------------------------------
# Autocheck state transitions
# ---------------------------------------------------------------------------

def test_autocheck_activates_pending_compliant_engineer(app, authenticated_client_manager, sample_data):
    eng, lab = sample_data['engineer'], sample_data['lab']
    with app.app_context():
        _add_access(eng, lab, 'pending')

    resp = authenticated_client_manager.post('/manager/autocheck')
    assert resp.status_code == 302

    with app.app_context():
        assert _status(eng, lab) == 'active'
        assert AuditLog.query.filter_by(action='auto_activate').count() == 1


def test_autocheck_revokes_active_engineer_with_expired_training(
        app, authenticated_client_manager, sample_data_expired_training):
    eng, lab = sample_data_expired_training['engineer'], sample_data_expired_training['lab']
    with app.app_context():
        _add_access(eng, lab, 'active')

    authenticated_client_manager.post('/manager/autocheck')

    with app.app_context():
        assert _status(eng, lab) == 'revoked'
        assert AuditLog.query.filter_by(action='auto_revoke').count() == 1


def test_autocheck_leaves_pending_noncompliant_and_active_compliant_unchanged(
        app, authenticated_client_manager, sample_data_no_ack, sample_course, multiple_labs):
    """No change when status already matches compliance; nothing is audited."""
    eng, lab_missing_ack = sample_data_no_ack['engineer'], sample_data_no_ack['lab']
    lab_ok = multiple_labs[0]  # no requirements and no documents, so trivially compliant
    with app.app_context():
        _add_access(eng, lab_missing_ack, 'pending')
        _add_access(eng, lab_ok, 'active')

    authenticated_client_manager.post('/manager/autocheck')

    with app.app_context():
        assert _status(eng, lab_missing_ack) == 'pending'
        assert _status(eng, lab_ok) == 'active'
        assert AuditLog.query.filter(AuditLog.action.in_(['auto_activate', 'auto_revoke'])).count() == 0


def test_autocheck_never_reinstates_revoked_access(app, authenticated_client_manager, sample_data):
    eng, lab = sample_data['engineer'], sample_data['lab']
    with app.app_context():
        _add_access(eng, lab, 'revoked')

    authenticated_client_manager.post('/manager/autocheck')

    with app.app_context():
        assert _status(eng, lab) == 'revoked'


def test_engineer_cannot_run_autocheck(app, authenticated_client_engineer, sample_data):
    eng, lab = sample_data['engineer'], sample_data['lab']
    with app.app_context():
        _add_access(eng, lab, 'pending')

    resp = authenticated_client_engineer.post('/manager/autocheck')
    assert resp.status_code in (302, 401, 403)

    with app.app_context():
        assert _status(eng, lab) == 'pending'


# ---------------------------------------------------------------------------
# Manual approve and revoke
# ---------------------------------------------------------------------------

def test_manual_approve_activates_compliant_engineer(app, authenticated_client_manager, sample_data):
    eng, lab = sample_data['engineer'], sample_data['lab']
    authenticated_client_manager.post('/manager/approve', data={'engineer_id': eng, 'lab_id': lab})
    with app.app_context():
        assert _status(eng, lab) == 'active'


def test_manual_approve_keeps_noncompliant_engineer_pending(app, authenticated_client_manager,
                                                            sample_data_no_ack):
    eng, lab = sample_data_no_ack['engineer'], sample_data_no_ack['lab']
    authenticated_client_manager.post('/manager/approve', data={'engineer_id': eng, 'lab_id': lab})
    with app.app_context():
        assert _status(eng, lab) == 'pending'


def test_manual_revoke_replaces_active_access(app, authenticated_client_manager, sample_data):
    eng, lab = sample_data['engineer'], sample_data['lab']
    with app.app_context():
        _add_access(eng, lab, 'active')

    authenticated_client_manager.post('/manager/revoke', data={'engineer_id': eng, 'lab_id': lab})
    with app.app_context():
        assert _status(eng, lab) == 'revoked'


def test_approve_rejects_non_numeric_ids(app, authenticated_client_manager):
    resp = authenticated_client_manager.post('/manager/approve', data={'engineer_id': 'x', 'lab_id': ''})
    assert resp.status_code == 302
    with app.app_context():
        assert LabAccess.query.count() == 0


# ---------------------------------------------------------------------------
# Month arithmetic: expirations clamp to the end of shorter months
# ---------------------------------------------------------------------------

def test_add_months_clamps_to_month_end():
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)   # leap year
    assert add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)  # leap day + 1 year
    assert add_months(date(2025, 11, 15), 3) == date(2026, 2, 15)  # crosses a year

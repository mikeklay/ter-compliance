# seed.py — idempotent demo data for local/dev
from datetime import date, timedelta

from compliance.models import (
    db,
    Engineer, Lab, Course,
    LabRequirement, Completion,
    LabAccess, LabMetrics, Document,
    User,  
)

def _seed_core():
    # Engineers
    if not Engineer.query.filter_by(employee_no="E100").first():
        db.session.add(Engineer(employee_no="E100", name="Ava Nguyen",  email="ava@example.com"))
    if not Engineer.query.filter_by(employee_no="E101").first():
        db.session.add(Engineer(employee_no="E101", name="Mike Jordan", email="mike@example.com"))

    # Labs
    if not Lab.query.filter_by(code="LAB-EE").first():
        db.session.add(Lab(code="LAB-EE", name="Electrical Engineering Lab", grace_days=0))
    if not Lab.query.filter_by(code="LAB-CHEM").first():
        db.session.add(Lab(code="LAB-CHEM", name="Chemistry Lab", grace_days=7))
    db.session.commit()

    lab_ee   = Lab.query.filter_by(code="LAB-EE").first()
    lab_chem = Lab.query.filter_by(code="LAB-CHEM").first()
    ava  = Engineer.query.filter_by(employee_no="E100").first()
    mike = Engineer.query.filter_by(employee_no="E101").first()

    # Courses
    if not Course.query.filter_by(code="SAFE-101").first():
        db.session.add(Course(code="SAFE-101", name="General Safety", valid_months=12))
    if not Course.query.filter_by(code="ELEC-201").first():
        db.session.add(Course(code="ELEC-201", name="Electrical Safety", valid_months=24))
    if not Course.query.filter_by(code="CHEM-110").first():
        db.session.add(Course(code="CHEM-110", name="Chemical Handling", valid_months=12))
    db.session.commit()

    safe = Course.query.filter_by(code="SAFE-101").first()
    elec = Course.query.filter_by(code="ELEC-201").first()
    chem = Course.query.filter_by(code="CHEM-110").first()

    # Lab requirements
    if not LabRequirement.query.filter_by(lab_id=lab_ee.id, course_id=safe.id).first():
        db.session.add(LabRequirement(lab_id=lab_ee.id, course_id=safe.id))
    if not LabRequirement.query.filter_by(lab_id=lab_ee.id, course_id=elec.id).first():
        db.session.add(LabRequirement(lab_id=lab_ee.id, course_id=elec.id, valid_months=24))
    if not LabRequirement.query.filter_by(lab_id=lab_chem.id, course_id=safe.id).first():
        db.session.add(LabRequirement(lab_id=lab_chem.id, course_id=safe.id))
    if not LabRequirement.query.filter_by(lab_id=lab_chem.id, course_id=chem.id).first():
        db.session.add(LabRequirement(lab_id=lab_chem.id, course_id=chem.id))
    db.session.commit()

    # Completions
    today = date.today()
    if not Completion.query.filter_by(engineer_id=ava.id, course_id=safe.id, date_taken=today - timedelta(days=20)).first():
        db.session.add(Completion(engineer_id=ava.id, course_id=safe.id, date_taken=today - timedelta(days=20)))
    if not Completion.query.filter_by(engineer_id=ava.id, course_id=elec.id, date_taken=today - timedelta(days=300)).first():
        db.session.add(Completion(engineer_id=ava.id, course_id=elec.id, date_taken=today - timedelta(days=300)))
    if not Completion.query.filter_by(engineer_id=mike.id, course_id=safe.id, date_taken=today - timedelta(days=400)).first():
        db.session.add(Completion(engineer_id=mike.id, course_id=safe.id, date_taken=today - timedelta(days=400)))
    if not Completion.query.filter_by(engineer_id=mike.id, course_id=chem.id, date_taken=today - timedelta(days=10)).first():
        db.session.add(Completion(engineer_id=mike.id, course_id=chem.id, date_taken=today - timedelta(days=10)))
    db.session.commit()

    # Access states
    if not LabAccess.query.filter_by(engineer_id=ava.id, lab_id=lab_ee.id, status="pending").first():
        db.session.add(LabAccess(engineer_id=ava.id, lab_id=lab_ee.id, status="pending"))
    if not LabAccess.query.filter_by(engineer_id=mike.id, lab_id=lab_chem.id, status="pending").first():
        db.session.add(LabAccess(engineer_id=mike.id, lab_id=lab_chem.id, status="pending"))
    db.session.commit()

    # Metrics
    if not LabMetrics.query.filter_by(lab_id=lab_ee.id, asof=today).first():
        db.session.add(LabMetrics(lab_id=lab_ee.id, asof=today, utilization=62, condition=91, activity=74))
    if not LabMetrics.query.filter_by(lab_id=lab_chem.id, asof=today).first():
        db.session.add(LabMetrics(lab_id=lab_chem.id, asof=today, utilization=71, condition=86, activity=65))
    db.session.commit()

    # Documents (placeholders)
    if not Document.query.filter_by(lab_id=lab_ee.id, title="EE Lab Manual", version=1).first():
        db.session.add(Document(lab_id=lab_ee.id, title="EE Lab Manual", version=1, mandatory=True, s3_key=None))
    if not Document.query.filter_by(lab_id=lab_chem.id, title="Chemical Safety SOP", version=1).first():
        db.session.add(Document(lab_id=lab_chem.id, title="Chemical Safety SOP", version=1, mandatory=True, s3_key=None))
    db.session.commit()


def _seed_users():
    created = False
    if not User.query.filter_by(email="admin@example.com").first():
        a = User(email="admin@example.com", role="admin")
        a.set_password("Admin123!")
        db.session.add(a); created = True

    if not User.query.filter_by(email="manager@example.com").first():
        m = User(email="manager@example.com", role="manager")
        m.set_password("Manager123!")
        db.session.add(m); created = True

    # Link a real engineer if present
    eng = Engineer.query.first()
    if eng and not User.query.filter_by(email="eng@example.com").first():
        e = User(email="eng@example.com", role="engineer", engineer_id=eng.id)
        e.set_password("Eng123!")
        db.session.add(e); created = True

    if created:
        db.session.commit()


def seed_data():
    _seed_core()
    _seed_users()

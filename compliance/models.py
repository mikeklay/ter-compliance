from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, CheckConstraint
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# ------------------------------
# Core reference entities
# ------------------------------

class Engineer(db.Model):
    __tablename__ = "engineer"
    id = db.Column(db.Integer, primary_key=True)
    employee_no = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)

    # relationships (optional)
    completions = db.relationship("Completion", backref="engineer", lazy="dynamic")
    accesses = db.relationship("LabAccess", backref="engineer", lazy="dynamic")
    doc_acks = db.relationship("DocumentAck", backref="engineer", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Engineer {self.id} {self.name}>"


class Lab(db.Model):
    __tablename__ = "lab"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    grace_days = db.Column(db.Integer, default=0, nullable=False)

    requirements = db.relationship("LabRequirement", backref="lab", lazy="dynamic")
    documents = db.relationship("Document", backref="lab", lazy="dynamic")
    metrics = db.relationship("LabMetrics", backref="lab", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Lab {self.code}>"


class Course(db.Model):
    __tablename__ = "course"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    # default validity in months (can be overridden per lab in LabRequirement.valid_months)
    valid_months = db.Column(db.Integer, nullable=True)

    completions = db.relationship("Completion", backref="course", lazy="dynamic")
    requirements = db.relationship("LabRequirement", backref="course", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Course {self.code}>"

# ------------------------------
# Configuration entities
# ------------------------------

class LabRequirement(db.Model):
    """
    A course required for a lab. Optionally overrides validity months for this lab.
    """
    __tablename__ = "lab_requirement"
    id = db.Column(db.Integer, primary_key=True)
    lab_id = db.Column(db.Integer, db.ForeignKey("lab.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    valid_months = db.Column(db.Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("lab_id", "course_id", name="uq_lab_course"),
    )

# ------------------------------
# Operational entities
# ------------------------------

class Completion(db.Model):
    __tablename__ = "completion"
    id = db.Column(db.Integer, primary_key=True)
    engineer_id = db.Column(db.Integer, db.ForeignKey("engineer.id"), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False, index=True)
    date_taken = db.Column(db.Date, nullable=False)

    certificate_url = db.Column(db.String(1024), nullable=True)

    # Map the Python attribute `s3_key` to the existing DB column `certificate_s3_key`
    s3_key = db.Column("certificate_s3_key", db.String(1024), nullable=True)

    __table_args__ = (
        UniqueConstraint("engineer_id", "course_id", "date_taken", name="uq_completion_once_per_day"),
    )


class Document(db.Model):
    __tablename__ = "document"
    id = db.Column(db.Integer, primary_key=True)
    lab_id = db.Column(db.Integer, db.ForeignKey("lab.id"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    mandatory = db.Column(db.Boolean, default=True, nullable=False)
    s3_key = db.Column(db.String(1024), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("lab_id", "title", "version", name="uq_doc_lab_title_version"),
    )


class DocumentAck(db.Model):
    __tablename__ = "document_ack"
    id = db.Column(db.Integer, primary_key=True)
    engineer_id = db.Column(db.Integer, db.ForeignKey("engineer.id"), nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey("document.id"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    acked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("engineer_id", "document_id", "version", name="uq_ack_one_per_version"),
    )


class LabAccess(db.Model):
    """
    Tracks access state per engineer/lab.
    status âˆˆ {'pending','active','revoked'}
    """
    __tablename__ = "lab_access"
    id = db.Column(db.Integer, primary_key=True)
    engineer_id = db.Column(db.Integer, db.ForeignKey("engineer.id"), nullable=False, index=True)
    lab_id = db.Column(db.Integer, db.ForeignKey("lab.id"), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, index=True)  # pending | active | revoked
    reason_code = db.Column(db.String(64), nullable=True)  # ADDED: tracks reason for status
    effective_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("engineer_id", "lab_id", "status", name="uq_access_unique_state"),
        CheckConstraint("status in ('pending','active','revoked')", name="ck_access_status"),
    )


class LabMetrics(db.Model):
    __tablename__ = "lab_metrics"
    id = db.Column(db.Integer, primary_key=True)
    lab_id = db.Column(db.Integer, db.ForeignKey("lab.id"), nullable=False, index=True)
    asof = db.Column(db.Date, default=date.today, nullable=False, index=True)

    utilization = db.Column(db.Integer, nullable=False)  # 0-100
    condition   = db.Column(db.Integer, nullable=False)  # 0-100
    activity    = db.Column(db.Integer, nullable=False)  # 0-100

    __table_args__ = (
        UniqueConstraint("lab_id", "asof", name="uq_lab_metrics_daily"),
        CheckConstraint("utilization >= 0 AND utilization <= 100", name="ck_util_pct"),
        CheckConstraint("`condition` >= 0 AND `condition` <= 100", name="ck_cond_pct"),
        CheckConstraint("activity >= 0 AND activity <= 100", name="ck_act_pct"),
    )

# ------------------------------
# Auth / Users
# ------------------------------

class User(db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    pass_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), nullable=False)  # "admin" | "manager" | "engineer"
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    engineer_id = db.Column(db.Integer, db.ForeignKey("engineer.id"), nullable=True)

    def set_password(self, raw: str):
        self.pass_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.pass_hash, raw)

# ------------------------------
# Audit Log
# ------------------------------

class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    actor_user_id = db.Column(db.Integer, nullable=True, index=True)
    action = db.Column(db.String(64), nullable=False, index=True)   # e.g. approve_access
    entity = db.Column(db.String(64), nullable=False, index=True)   # e.g. lab_access, course, document
    entity_id = db.Column(db.String(128), nullable=True, index=True)
    meta_json = db.Column(db.Text, nullable=True)


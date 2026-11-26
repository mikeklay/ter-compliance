"""
Compliance engine tests - training validation and document acknowledgment.
FIXED: Using IDs instead of detached objects to avoid SQLAlchemy session issues.
"""
import pytest
from datetime import date, timedelta
from compliance.models import (
    db, Engineer, Lab, Course, LabRequirement, 
    Completion, Document, DocumentAck
)
from compliance.routes.manager import is_compliant_for_lab


def test_current_training_is_compliant(app, sample_data):
    """Test that recent training passes compliance check."""
    with app.app_context():
        eng_id = sample_data['engineer']
        lab_id = sample_data['lab']
        
        # Should be compliant (training from 30 days ago with 12-month validity)
        compliant = is_compliant_for_lab(eng_id, lab_id)
        
        assert compliant, "Recent training should be compliant"


def test_expired_training_detected(app, sample_engineer, sample_lab, sample_course):
    """Test that expired training is correctly identified."""
    with app.app_context():
        # Create requirement (using IDs)
        req = LabRequirement(lab_id=sample_lab, course_id=sample_course)
        db.session.add(req)
        
        # Add expired completion (13 months ago for 12-month course)
        old_completion = Completion(
            engineer_id=sample_engineer,
            course_id=sample_course,
            date_taken=date.today() - timedelta(days=395)
        )
        db.session.add(old_completion)
        db.session.commit()
        
        # Test using IDs
        compliant = is_compliant_for_lab(sample_engineer, sample_lab)
        
        assert not compliant, "Expired training should result in non-compliance"


def test_grace_period_extends_expiration(app, sample_engineer, sample_course):
    """Test that grace period allows recently expired training."""
    with app.app_context():
        # Create lab with 7-day grace period
        lab = Lab(code='LAB-GRACE', name='Grace Lab', grace_days=7)
        db.session.add(lab)
        db.session.flush()
        
        req = LabRequirement(lab_id=lab.id, course_id=sample_course)
        db.session.add(req)
        
        # Add completion that expired 5 days ago (within 7-day grace)
        # 12 months + 5 days = 370 days ago
        recent_completion = Completion(
            engineer_id=sample_engineer,
            course_id=sample_course,
            date_taken=date.today() - timedelta(days=370)
        )
        db.session.add(recent_completion)
        db.session.commit()
        
        # Test - should be compliant due to grace period
        compliant = is_compliant_for_lab(sample_engineer, lab.id)
        
        assert compliant, "Training within grace period should be compliant"


def test_missing_training_detected(app, sample_engineer, sample_lab, sample_course):
    """Test that missing required training is detected."""
    with app.app_context():
        # Create requirement but NO completion
        req = LabRequirement(lab_id=sample_lab, course_id=sample_course)
        db.session.add(req)
        db.session.commit()
        
        # Test
        compliant = is_compliant_for_lab(sample_engineer, sample_lab)
        
        assert not compliant, "Missing training should result in non-compliance"


def test_lab_specific_validity_override(app, sample_engineer, sample_lab, sample_course):
    """Test that lab-specific validity overrides course default."""
    with app.app_context():
        # Create requirement with 6-month override (course default is 12)
        req = LabRequirement(
            lab_id=sample_lab,
            course_id=sample_course,
            valid_months=6
        )
        db.session.add(req)
        
        # Add completion from 8 months ago
        # Would be valid under 12mo default, but NOT under 6mo override
        comp = Completion(
            engineer_id=sample_engineer,
            course_id=sample_course,
            date_taken=date.today() - timedelta(days=240)
        )
        db.session.add(comp)
        db.session.commit()
        
        # Test
        compliant = is_compliant_for_lab(sample_engineer, sample_lab)
        
        assert not compliant, "Lab override should make 8-month-old training non-compliant"


def test_multiple_completions_uses_latest(app, sample_engineer, sample_lab, sample_course):
    """Test that system uses the latest completion when multiple exist."""
    with app.app_context():
        req = LabRequirement(lab_id=sample_lab, course_id=sample_course)
        db.session.add(req)
        
        # Add old expired completion
        old_comp = Completion(
            engineer_id=sample_engineer,
            course_id=sample_course,
            date_taken=date.today() - timedelta(days=400)
        )
        db.session.add(old_comp)
        
        # Add recent current completion
        new_comp = Completion(
            engineer_id=sample_engineer,
            course_id=sample_course,
            date_taken=date.today() - timedelta(days=30)
        )
        db.session.add(new_comp)
        db.session.commit()
        
        # Test - should use latest completion
        compliant = is_compliant_for_lab(sample_engineer, sample_lab)
        
        assert compliant, "Latest completion should be used for compliance check"


def test_document_acknowledgment_required(app, sample_data_no_ack):
    """Test that mandatory documents must be acknowledged."""
    with app.app_context():
        eng_id = sample_data_no_ack['engineer']
        lab_id = sample_data_no_ack['lab']
        
        # Training is current but document not acknowledged
        # Should be non-compliant
        compliant = is_compliant_for_lab(eng_id, lab_id)
        
        assert not compliant, "Missing document acknowledgment should cause non-compliance"


def test_document_acknowledgment_makes_compliant(app, sample_data_no_ack):
    """Test that acknowledging documents achieves compliance."""
    with app.app_context():
        eng_id = sample_data_no_ack['engineer']
        lab_id = sample_data_no_ack['lab']
        doc_id = sample_data_no_ack['document']
        
        # Get the actual document object to get version
        doc = Document.query.get(doc_id)
        
        # Acknowledge the document
        ack = DocumentAck(
            engineer_id=eng_id,
            document_id=doc_id,
            version=doc.version
        )
        db.session.add(ack)
        db.session.commit()
        
        # Now should be compliant
        compliant = is_compliant_for_lab(eng_id, lab_id)
        
        assert compliant, "Acknowledging all documents should achieve compliance"


def test_document_version_change_invalidates_ack(app, sample_data_no_ack):
    """Test that new document version requires re-acknowledgment."""
    with app.app_context():
        eng_id = sample_data_no_ack['engineer']
        lab_id = sample_data_no_ack['lab']
        doc_id = sample_data_no_ack['document']
        
        # Get the actual document object
        doc = Document.query.get(doc_id)
        
        # Acknowledge version 1
        ack = DocumentAck(
            engineer_id=eng_id,
            document_id=doc_id,
            version=1
        )
        db.session.add(ack)
        db.session.commit()
        
        # Should be compliant with v1
        compliant = is_compliant_for_lab(eng_id, lab_id)
        assert compliant, "Should be compliant after acknowledging v1"
        
        # Update document to version 2
        doc.version = 2
        db.session.commit()
        
        # Should now be non-compliant
        compliant = is_compliant_for_lab(eng_id, lab_id)
        assert not compliant, "Should be non-compliant with unacknowledged v2"


def test_optional_documents_dont_affect_compliance(app, sample_engineer, sample_lab, sample_course):
    """Test that optional documents don't affect compliance status."""
    with app.app_context():
        # Create requirement and current completion
        req = LabRequirement(lab_id=sample_lab, course_id=sample_course)
        comp = Completion(
            engineer_id=sample_engineer,
            course_id=sample_course,
            date_taken=date.today() - timedelta(days=30)
        )
        db.session.add_all([req, comp])
        
        # Create optional document (mandatory=False)
        doc = Document(
            lab_id=sample_lab,
            title='Optional Doc',
            version=1,
            mandatory=False
        )
        db.session.add(doc)
        db.session.commit()
        
        # Should be compliant without acknowledging optional doc
        compliant = is_compliant_for_lab(sample_engineer, sample_lab)
        
        assert compliant, "Optional documents should not affect compliance"


def test_no_requirements_means_compliant(app, sample_engineer, sample_lab):
    """Test that lab with no requirements is automatically compliant."""
    with app.app_context():
        # Lab exists but has no requirements
        compliant = is_compliant_for_lab(sample_engineer, sample_lab)
        
        assert compliant, "Lab with no requirements should be compliant"


def test_combined_training_and_document_compliance(app, sample_engineer, sample_lab, sample_course):
    """Test that both training AND documents must be compliant."""
    with app.app_context():
        # Create requirement and current completion
        req = LabRequirement(lab_id=sample_lab, course_id=sample_course)
        comp = Completion(
            engineer_id=sample_engineer,
            course_id=sample_course,
            date_taken=date.today() - timedelta(days=30)
        )
        doc = Document(
            lab_id=sample_lab,
            title='Safety Manual',
            version=1,
            mandatory=True
        )
        db.session.add_all([req, comp, doc])
        db.session.commit()
        
        # Current training but missing doc ack - NOT compliant
        compliant = is_compliant_for_lab(sample_engineer, sample_lab)
        assert not compliant, "Should be non-compliant without doc ack"
        
        # Add document acknowledgment
        ack = DocumentAck(
            engineer_id=sample_engineer,
            document_id=doc.id,
            version=1
        )
        db.session.add(ack)
        db.session.commit()
        
        # Now both training and docs are compliant
        compliant = is_compliant_for_lab(sample_engineer, sample_lab)
        assert compliant, "Should be compliant with both training and doc ack"
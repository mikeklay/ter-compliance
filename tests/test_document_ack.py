"""
Document acknowledgment functionality tests.
FIXED: Using dict access and IDs from sample_data
"""
import pytest
from compliance.models import db, DocumentAck, Engineer, LabAccess, Document


def test_engineer_can_acknowledge_document(client, engineer_user, sample_data, app):
    """Test engineer self-service acknowledgment."""
    with app.app_context():
        doc_id = sample_data['document']
        
        # Login as engineer
        client.post('/auth/login', data={
            'email': 'engineer@test.com',
            'password': 'Eng123!'
        })
        
        # Acknowledge document (doc_id is already an int)
        response = client.post(
            f'/engineer/acknowledge/{doc_id}',
            follow_redirects=True
        )
        
        assert response.status_code == 200
        
        # Verify acknowledgment created
        # Get document to check version
        doc = Document.query.get(doc_id)
        ack = DocumentAck.query.filter_by(
            engineer_id=engineer_user['engineer_id'],
            document_id=doc_id,
            version=doc.version
        ).first()
        
        assert ack is not None, "Acknowledgment should be created"


def test_duplicate_acknowledgment_handled_gracefully(client, engineer_user, sample_data, app):
    """Test that duplicate acknowledgments are handled without error."""
    with app.app_context():
        doc_id = sample_data['document']
        doc = Document.query.get(doc_id)
        
        # Create initial acknowledgment
        ack1 = DocumentAck(
            engineer_id=engineer_user['engineer_id'],
            document_id=doc_id,
            version=doc.version
        )
        db.session.add(ack1)
        db.session.commit()
        
        # Login and try to acknowledge again
        client.post('/auth/login', data={
            'email': 'engineer@test.com',
            'password': 'Eng123!'
        })
        
        response = client.post(
            f'/engineer/acknowledge/{doc_id}',
            follow_redirects=True
        )
        
        assert response.status_code == 200
        
        # Should still only have one acknowledgment
        ack_count = DocumentAck.query.filter_by(
            engineer_id=engineer_user['engineer_id'],
            document_id=doc_id,
            version=doc.version
        ).count()
        
        assert ack_count == 1, "Should not create duplicate acknowledgments"


def test_engineer_documents_page_shows_required_docs(client, engineer_user, sample_data, app):
    """Test that engineer documents page shows required documents."""
    with app.app_context():
        eng = Engineer.query.get(engineer_user['engineer_id'])
        lab_id = sample_data['lab']
        
        # Create access for engineer to this lab
        access = LabAccess(
            engineer_id=eng.id,
            lab_id=lab_id,
            status='active'
        )
        db.session.add(access)
        db.session.commit()
        
        # Login and visit documents page
        client.post('/auth/login', data={
            'email': 'engineer@test.com',
            'password': 'Eng123!'
        })
        
        response = client.get('/engineer/documents')
        
        assert response.status_code == 200
        assert b'Test Document' in response.data  # Document title from sample_data


def test_acknowledged_documents_show_as_complete(client, engineer_user, sample_data, app):
    """Test that acknowledged documents appear as acknowledged."""
    with app.app_context():
        doc_id = sample_data['document']
        doc = Document.query.get(doc_id)
        eng = Engineer.query.get(engineer_user['engineer_id'])
        lab_id = sample_data['lab']
        
        # Create access
        access = LabAccess(engineer_id=eng.id, lab_id=lab_id, status='active')
        db.session.add(access)
        
        # Acknowledge document
        ack = DocumentAck(
            engineer_id=eng.id,
            document_id=doc_id,
            version=doc.version
        )
        db.session.add(ack)
        db.session.commit()
        
        # Login and check documents page
        client.post('/auth/login', data={
            'email': 'engineer@test.com',
            'password': 'Eng123!'
        })
        
        response = client.get('/engineer/documents')
        
        assert response.status_code == 200
        # Should show as acknowledged (Done button or similar)
        assert b'Done' in response.data or b'acknowledged' in response.data.lower()


def test_admin_can_record_acknowledgment(authenticated_client_admin, sample_data, app):
    """Test that admin can record acknowledgment on behalf of engineer."""
    with app.app_context():
        eng_id = sample_data['engineer']
        doc_id = sample_data['document']
        doc = Document.query.get(doc_id)
        
        # Admin acknowledges for engineer
        response = authenticated_client_admin.post('/admin/ack', 
            data={
                'engineer_id': eng_id,
                'document_id': doc_id,
                'version': doc.version
            },
            follow_redirects=True
        )
        
        assert response.status_code == 200
        
        # Verify acknowledgment created
        ack = DocumentAck.query.filter_by(
            engineer_id=eng_id,
            document_id=doc_id,
            version=doc.version
        ).first()
        
        assert ack is not None


def test_acknowledgment_timestamp_recorded(app, sample_data_no_ack):
    """Test that acknowledgment timestamp is recorded."""
    from datetime import datetime
    
    with app.app_context():
        eng_id = sample_data_no_ack['engineer']  # Changed
        doc_id = sample_data_no_ack['document']  # Changed
        doc = Document.query.get(doc_id)
        
        before = datetime.utcnow()
        
        ack = DocumentAck(
            engineer_id=eng_id,
            document_id=doc_id,
            version=doc.version
        )
        db.session.add(ack)
        db.session.commit()
        
        after = datetime.utcnow()
        
        assert ack.acked_at is not None
        assert before <= ack.acked_at <= after


def test_engineer_without_engineer_record_cannot_acknowledge(client, manager_user, sample_data, app):
    """Test that user without engineer_id cannot acknowledge documents."""
    with app.app_context():
        doc_id = sample_data['document']
        
        # Login as manager (who has no engineer_id)
        client.post('/auth/login', data={
            'email': 'manager@test.com',
            'password': 'Manager123!'
        })
        
        response = client.post(
            f'/engineer/acknowledge/{doc_id}',
            follow_redirects=True
        )
        
        assert response.status_code == 200
        # Should show error message
        assert b'engineer record' in response.data.lower()


def test_documents_page_shows_statistics(client, engineer_user, sample_data, app):
    """Test that documents page shows acknowledgment statistics."""
    with app.app_context():
        eng = Engineer.query.get(engineer_user['engineer_id'])
        lab_id = sample_data['lab']
        
        # Create access
        access = LabAccess(engineer_id=eng.id, lab_id=lab_id, status='active')
        db.session.add(access)
        db.session.commit()
        
        # Login and check page
        client.post('/auth/login', data={
            'email': 'engineer@test.com',
            'password': 'Eng123!'
        })
        
        response = client.get('/engineer/documents')
        
        assert response.status_code == 200
        # Should show total, acknowledged, and pending counts
        assert b'Total' in response.data or b'total' in response.data
        assert b'Acknowledged' in response.data or b'acknowledged' in response.data
        assert b'Pending' in response.data or b'pending' in response.data
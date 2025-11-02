"""
Test configuration and fixtures for TER testing suite.
"""
import pytest
import sys
import os
from datetime import date, timedelta

# Add parent directory to path so we can import compliance package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from compliance import create_app
from compliance.models import (
    db, Engineer, Lab, Course, LabRequirement, 
    Completion, Document, DocumentAck, LabAccess, User
)
from compliance.auth_utils import make_jwt


@pytest.fixture
def app():
    """Create application for testing with in-memory database."""
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SECRET_KEY': 'test-secret-key',
        'JWT_SECRET': 'test-jwt-secret',
        'WTF_CSRF_ENABLED': False,  # Disable CSRF for testing
    })
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Test client for making requests."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """CLI test runner."""
    return app.test_cli_runner()


@pytest.fixture
def admin_user(app):
    """Create an admin user and return dict with user info."""
    with app.app_context():
        user = User(email='admin@test.com', role='admin', is_active=True)
        user.set_password('Admin123!')
        db.session.add(user)
        db.session.commit()
        # Return dict to avoid detached instance issues
        return {'id': user.id, 'role': user.role, 'email': user.email}


@pytest.fixture
def manager_user(app):
    """Create a manager user and return dict with user info."""
    with app.app_context():
        user = User(email='manager@test.com', role='manager', is_active=True)
        user.set_password('Manager123!')
        db.session.add(user)
        db.session.commit()
        return {'id': user.id, 'role': user.role, 'email': user.email}


@pytest.fixture
def engineer_user(app):
    """Create an engineer user linked to an Engineer record."""
    with app.app_context():
        # Create engineer record first
        eng = Engineer(
            employee_no='E001',
            name='Test Engineer',
            email='engineer@test.com'
        )
        db.session.add(eng)
        db.session.flush()
        
        # Create user linked to engineer
        user = User(
            email='engineer@test.com',
            role='engineer',
            is_active=True,
            engineer_id=eng.id
        )
        user.set_password('Eng123!')
        db.session.add(user)
        db.session.commit()
        
        return {
            'id': user.id,
            'role': user.role,
            'email': user.email,
            'engineer_id': eng.id
        }


# =============================================================================
# AUTHENTICATED CLIENT FIXTURES - Use these for testing protected routes
# =============================================================================

@pytest.fixture
def authenticated_client_admin(client, app, admin_user):
    """
    Return test client with admin authentication cookie set.
    Use this instead of passing headers manually.
    
    Example:
        def test_something(authenticated_client_admin):
            response = authenticated_client_admin.get('/admin/reports/active.csv')
            assert response.status_code == 200
    """
    with app.app_context():
        token = make_jwt(admin_user['id'], admin_user['role'], admin_user['email'])
        client.set_cookie('jwt', token)
        return client


@pytest.fixture
def authenticated_client_manager(client, app, manager_user):
    """Return test client with manager authentication cookie set."""
    with app.app_context():
        token = make_jwt(manager_user['id'], manager_user['role'], manager_user['email'])
        client.set_cookie('jwt', token)
        return client


@pytest.fixture
def authenticated_client_engineer(client, app, engineer_user):
    """Return test client with engineer authentication cookie set."""
    with app.app_context():
        token = make_jwt(engineer_user['id'], engineer_user['role'], engineer_user['email'])
        client.set_cookie('jwt', token)
        return client


# =============================================================================
# LEGACY HEADER-BASED AUTH FIXTURES - Kept for backward compatibility
# These work but authenticated_client_* fixtures are preferred
# =============================================================================

@pytest.fixture
def auth_headers_admin(app, admin_user):
    """
    Return authentication headers for admin user.
    NOTE: Use authenticated_client_admin instead for better compatibility.
    """
    with app.app_context():
        token = make_jwt(admin_user['id'], admin_user['role'], admin_user['email'])
        # Flask test client needs environ keys, not standard headers
        return {'HTTP_COOKIE': f'jwt={token}'}


@pytest.fixture
def auth_headers_manager(app, manager_user):
    """Return authentication headers for manager user."""
    with app.app_context():
        token = make_jwt(manager_user['id'], manager_user['role'], manager_user['email'])
        return {'HTTP_COOKIE': f'jwt={token}'}


@pytest.fixture
def auth_headers_engineer(app, engineer_user):
    """Return authentication headers for engineer user."""
    with app.app_context():
        token = make_jwt(engineer_user['id'], engineer_user['role'], engineer_user['email'])
        return {'HTTP_COOKIE': f'jwt={token}'}


# =============================================================================
# SAMPLE DATA FIXTURES
# =============================================================================

@pytest.fixture
def sample_engineer(app):
    """Create a sample engineer and return ID (not object)."""
    with app.app_context():
        eng = Engineer(
            employee_no='E100',
            name='Sample Engineer',
            email='sample@test.com'
        )
        db.session.add(eng)
        db.session.commit()
        # Return ID only to avoid detached instance issues
        return eng.id


@pytest.fixture
def sample_lab(app):
    """Create a sample laboratory and return ID (not object)."""
    with app.app_context():
        lab = Lab(
            code='LAB-TEST',
            name='Test Laboratory',
            grace_days=7
        )
        db.session.add(lab)
        db.session.commit()
        return lab.id


@pytest.fixture
def sample_course(app):
    """Create a sample course and return ID (not object)."""
    with app.app_context():
        course = Course(
            code='SAFE-101',
            name='Safety Training',
            valid_months=12
        )
        db.session.add(course)
        db.session.commit()
        return course.id


@pytest.fixture
def sample_data(app, sample_engineer, sample_lab, sample_course):
    """
    Create complete sample data set for testing - WITH document acknowledgment.
    Engineer is COMPLIANT (has training + acknowledged documents).
    
    Returns dict of IDs:
        {
            'engineer': int,
            'lab': int,
            'course': int,
            'completion': int,
            'document': int
        }
    """
    with app.app_context():
        # Create requirement linking course to lab
        req = LabRequirement(
            lab_id=sample_lab,
            course_id=sample_course,
            valid_months=None  # Use course default (12 months)
        )
        db.session.add(req)
        
        # Create a completion (30 days old - should be current)
        comp = Completion(
            engineer_id=sample_engineer,
            course_id=sample_course,
            date_taken=date.today() - timedelta(days=30)
        )
        db.session.add(comp)
        
        # Create a mandatory document
        doc = Document(
            lab_id=sample_lab,
            title='Test Document',
            version=1,
            mandatory=True
        )
        db.session.add(doc)
        db.session.flush()  # Get doc.id before committing
        
        # Acknowledge the document so engineer is compliant
        ack = DocumentAck(
            engineer_id=sample_engineer,
            document_id=doc.id,
            version=1
        )
        db.session.add(ack)
        
        db.session.commit()
        
        # Return IDs only (not objects) to avoid detached instance issues
        return {
            'engineer': sample_engineer,
            'lab': sample_lab,
            'course': sample_course,
            'completion': comp.id,
            'document': doc.id
        }


@pytest.fixture
def sample_data_no_ack(app, sample_engineer, sample_lab, sample_course):
    """
    Create sample data WITHOUT document acknowledgment.
    Engineer is NON-COMPLIANT (has training but missing document ack).
    
    Returns dict of IDs:
        {
            'engineer': int,
            'lab': int,
            'course': int,
            'completion': int,
            'document': int
        }
    """
    with app.app_context():
        # Create requirement linking course to lab
        req = LabRequirement(
            lab_id=sample_lab,
            course_id=sample_course,
            valid_months=None  # Use course default
        )
        db.session.add(req)
        
        # Create a completion (30 days old - should be current)
        comp = Completion(
            engineer_id=sample_engineer,
            course_id=sample_course,
            date_taken=date.today() - timedelta(days=30)
        )
        db.session.add(comp)
        
        # Create a document but DON'T acknowledge it
        doc = Document(
            lab_id=sample_lab,
            title='Test Document',
            version=1,
            mandatory=True
        )
        db.session.add(doc)
        
        db.session.commit()
        
        # Return IDs only
        return {
            'engineer': sample_engineer,
            'lab': sample_lab,
            'course': sample_course,
            'completion': comp.id,
            'document': doc.id
        }


# =============================================================================
# HELPER FIXTURES FOR SPECIFIC TEST SCENARIOS
# =============================================================================

@pytest.fixture
def sample_data_expired_training(app, sample_engineer, sample_lab, sample_course):
    """
    Create sample data with EXPIRED training (400 days old).
    Engineer is NON-COMPLIANT due to expired training.
    """
    with app.app_context():
        req = LabRequirement(
            lab_id=sample_lab,
            course_id=sample_course,
            valid_months=None
        )
        db.session.add(req)
        
        # Create OLD completion (400 days old - expired for 12-month course)
        comp = Completion(
            engineer_id=sample_engineer,
            course_id=sample_course,
            date_taken=date.today() - timedelta(days=400)
        )
        db.session.add(comp)
        
        doc = Document(
            lab_id=sample_lab,
            title='Test Document',
            version=1,
            mandatory=True
        )
        db.session.add(doc)
        db.session.flush()
        
        # Acknowledge document (so only issue is expired training)
        ack = DocumentAck(
            engineer_id=sample_engineer,
            document_id=doc.id,
            version=1
        )
        db.session.add(ack)
        
        db.session.commit()
        
        return {
            'engineer': sample_engineer,
            'lab': sample_lab,
            'course': sample_course,
            'completion': comp.id,
            'document': doc.id
        }


@pytest.fixture
def multiple_engineers(app):
    """Create multiple engineers for testing bulk operations."""
    with app.app_context():
        engineers = []
        for i in range(1, 4):
            eng = Engineer(
                employee_no=f'E{100+i}',
                name=f'Engineer {i}',
                email=f'eng{i}@test.com'
            )
            db.session.add(eng)
            db.session.flush()
            engineers.append(eng.id)
        
        db.session.commit()
        return engineers


@pytest.fixture
def multiple_labs(app):
    """Create multiple labs for testing."""
    with app.app_context():
        labs = []
        for i in range(1, 4):
            lab = Lab(
                code=f'LAB-{i}',
                name=f'Laboratory {i}',
                grace_days=7
            )
            db.session.add(lab)
            db.session.flush()
            labs.append(lab.id)
        
        db.session.commit()
        return labs
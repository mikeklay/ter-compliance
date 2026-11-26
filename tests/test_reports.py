"""
CSV report generation tests.
FIXED: Using authenticated_client_* fixtures
"""
import pytest
import csv
from io import StringIO
from compliance.models import db, LabAccess


def test_active_access_report_downloads(authenticated_client_admin):
    """Test that active access CSV report downloads successfully."""
    response = authenticated_client_admin.get('/admin/reports/active.csv')
    
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'
    assert 'attachment' in response.headers.get('Content-Disposition', '')


def test_active_access_report_has_correct_columns(authenticated_client_admin):
    """Test that active access report has expected columns."""
    response = authenticated_client_admin.get('/admin/reports/active.csv')
    
    csv_data = response.data.decode('utf-8')
    reader = csv.reader(StringIO(csv_data))
    headers = next(reader)
    
    expected_columns = ['generated_at_utc', 'engineer_id', 'engineer_name', 'lab_id', 'lab', 'since_utc']
    assert headers == expected_columns


def test_pending_access_report_downloads(authenticated_client_admin):
    """Test that pending access CSV report downloads successfully."""
    response = authenticated_client_admin.get('/admin/reports/pending.csv')
    
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'


def test_expiring_training_report_downloads(authenticated_client_admin):
    """Test that expiring training report downloads successfully."""
    response = authenticated_client_admin.get('/admin/reports/expiring30.csv')
    
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'


def test_compliance_status_report_downloads(authenticated_client_admin):
    """Test that compliance status report downloads successfully."""
    response = authenticated_client_admin.get('/admin/reports/compliance_status.csv')
    
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'


def test_completions_report_downloads(authenticated_client_admin):
    """Test that completions report downloads successfully."""
    response = authenticated_client_admin.get('/admin/reports/completions.csv')
    
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'


def test_document_acks_report_downloads(authenticated_client_admin):
    """Test that document acknowledgments report downloads successfully."""
    response = authenticated_client_admin.get('/admin/reports/doc_acks.csv')
    
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'


def test_access_history_report_downloads(authenticated_client_admin):
    """Test that access history report downloads successfully."""
    response = authenticated_client_admin.get('/admin/reports/access.csv')
    
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'


def test_active_access_report_includes_data(authenticated_client_admin, sample_data, app):
    """Test that active access report includes actual data."""
    with app.app_context():
        eng_id = sample_data['engineer']
        lab_id = sample_data['lab']
        
        # Create active access
        access = LabAccess(
            engineer_id=eng_id,
            lab_id=lab_id,
            status='active'
        )
        db.session.add(access)
        db.session.commit()
        
    response = authenticated_client_admin.get('/admin/reports/active.csv')
    
    csv_data = response.data.decode('utf-8')
    reader = csv.reader(StringIO(csv_data))
    rows = list(reader)
    
    # Should have header + at least 1 data row
    assert len(rows) >= 2
    # Should include engineer name
    assert any('Sample Engineer' in str(row) for row in rows)


def test_compliance_status_report_shows_issues(authenticated_client_admin, sample_data, app):
    """Test that compliance status report includes issue details."""
    with app.app_context():
        eng_id = sample_data['engineer']
        lab_id = sample_data['lab']
        
        # Create pending access (engineer is non-compliant - missing doc ack)
        access = LabAccess(
            engineer_id=eng_id,
            lab_id=lab_id,
            status='pending'
        )
        db.session.add(access)
        db.session.commit()
    
    response = authenticated_client_admin.get('/admin/reports/compliance_status.csv')
    
    assert response.status_code == 200
    csv_data = response.data.decode('utf-8')
    reader = csv.reader(StringIO(csv_data))
    headers = next(reader)
    
    # Should have training_issues and document_issues columns
    assert 'training_issues' in headers
    assert 'document_issues' in headers


def test_manager_can_download_reports(authenticated_client_manager):
    """Test that manager role can download reports."""
    response = authenticated_client_manager.get('/admin/reports/active.csv')
    
    assert response.status_code == 200
    assert response.mimetype == 'text/csv'


def test_engineer_cannot_download_reports(authenticated_client_engineer):
    """Test that engineer role cannot download reports."""
    response = authenticated_client_engineer.get('/admin/reports/active.csv')
    
    # Should be forbidden or unauthorized
    assert response.status_code in [401, 403]


def test_reports_without_auth_redirect(client):
    """Test that reports without authentication redirect or fail."""
    response = client.get('/admin/reports/active.csv')
    
    # Should not return CSV - either redirect or unauthorized
    assert response.status_code in [302, 401, 403]
    if response.status_code != 302:
        assert response.mimetype != 'text/csv'


def test_csv_reports_are_valid_format(authenticated_client_admin):
    """Test that all CSV reports produce valid CSV format."""
    reports = [
        '/admin/reports/active.csv',
        '/admin/reports/pending.csv',
        '/admin/reports/expiring30.csv',
        '/admin/reports/compliance_status.csv',
        '/admin/reports/completions.csv',
        '/admin/reports/doc_acks.csv',
        '/admin/reports/access.csv'
    ]
    
    for report_url in reports:
        response = authenticated_client_admin.get(report_url)
        
        assert response.status_code == 200, f"{report_url} failed to download"
        
        # Should be parseable as CSV
        csv_data = response.data.decode('utf-8')
        try:
            reader = csv.reader(StringIO(csv_data))
            rows = list(reader)
            assert len(rows) >= 1, f"{report_url} has no data"
        except csv.Error as e:
            pytest.fail(f"{report_url} is not valid CSV: {e}")


def test_expiring_training_report_includes_days_left(authenticated_client_admin, sample_data, app):
    """Test that expiring training report calculates days left."""
    with app.app_context():
        # sample_data already has a completion
        pass
    
    response = authenticated_client_admin.get('/admin/reports/expiring30.csv')
    
    csv_data = response.data.decode('utf-8')
    reader = csv.reader(StringIO(csv_data))
    headers = next(reader)
    
    # Should have days_left column
    assert 'days_left' in headers
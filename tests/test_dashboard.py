"""
Tests for Dashboard functionality
"""
import asyncio
import tempfile
import os
from jobhunt.db import JobHuntDB
from jobhunt.models import Job, Application
from jobhunt.app.screens.dashboard import DashboardScreen


def test_count_jobs_method():
    """Test that count_jobs method works correctly"""
    # Create a temporary DB for testing
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        database = JobHuntDB(database_path=db_path)
        
        # Initially should have 0 jobs
        assert database.count_jobs() == 0
        assert database.count_applications() == 0
        
        # Add a test job
        test_job = Job(
            id="test_job",
            title="Test Job",
            company="Test Corp",
            location="Test Location",
            description="Test job description",
            url="http://test.com",
            source="test",
            posted_date="2023-01-01"
        )
        database.save_job(test_job)
        
        # Should have 1 job now
        assert database.count_jobs() == 1
        assert database.count_applications() == 0
        
        # Add a test application
        test_application = Application(
            job_id="test_job",
            status="applied",
            applied_date="2023-01-01"
        )
        database.save_application(test_application)
        
        # Should have 1 job and 1 application
        assert database.count_jobs() == 1
        assert database.count_applications() == 1
        
    finally:
        # Clean up the temporary file
        if os.path.exists(db_path):
            os.unlink(db_path)
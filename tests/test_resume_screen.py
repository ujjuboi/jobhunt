"""
Tests for the resume screen functionality
"""
import pytest
from unittest.mock import Mock, patch
from jobhunt.app.screens.resume import ResumeScreen
from jobhunt.resume.profile_parser import Profile


def test_resume_screen_instantiation():
    screen = ResumeScreen()
    assert screen is not None
    assert screen.screen_name == "resume"


def test_resume_screen_with_db():
    screen = ResumeScreen(db=None)
    assert screen.db is None
    assert screen.resume_manager is None
    assert screen._agent is None


def test_resume_screen_get_content():
    screen = ResumeScreen()
    content = screen._get_content()
    assert content is not None


def test_resume_screen_profile_auto_save():
    """Test that profile is auto-saved to database when loaded."""
    # Create mock resume manager
    mock_resume_manager = Mock()
    mock_profile = Profile(
        name="Test User",
        email="test@test.com",
        phone="123-456-7890",
        summary="Test summary",
        skills=["Python", "JavaScript"],
        experience=[],
        education=[],
        certifications=[],
        projects=[]
    )
    mock_resume_manager.load_profile_from_docx.return_value = mock_profile
    
    # Create mock database
    mock_db = Mock()
    
    # Create screen with mock db and resume manager
    screen = ResumeScreen(db=mock_db)
    screen.resume_manager = mock_resume_manager
    
    # Test profile auto-save
    with patch.object(screen, 'query_one') as mock_query:
        screen._update_resume_preview("test_resume.docx")
        
        # Verify database save was called
        mock_db.save_profile.assert_called_once()
        
        # Verify status was updated
        mock_query.assert_any_call("#resume_status")


def test_resume_screen_profile_auto_save_no_db():
    """Test that profile auto-save doesn't fail when db is None."""
    screen = ResumeScreen(db=None)
    
    # Should not raise any exceptions even when db is None
    with patch.object(screen, 'query_one') as mock_query:
        # Mock the resume manager to avoid actual file loading 
        with patch('jobhunt.app.screens.resume.ResumeManager') as mock_manager_class:
            mock_manager = Mock()
            mock_manager_class.return_value = mock_manager
            mock_profile = Profile(
                name="Test User",
                email="test@test.com",
                phone="123-456-7890",
                summary="Test summary",
                skills=["Python", "JavaScript"],
                experience=[],
                education=[],
                certifications=[],
                projects=[]
            )
            mock_manager.load_profile_from_docx.return_value = mock_profile
            screen.resume_manager = mock_manager
            
            screen._update_resume_preview("test_resume.docx")
            
            # Should not call save_profile when db is None
            mock_manager.save_profile.assert_not_called()

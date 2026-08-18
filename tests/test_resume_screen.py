"""
Tests for the resume screen functionality
"""
import pytest
from jobhunt.app.screens.resume import ResumeScreen


def test_resume_screen_instantiation():
    """Test that ResumeScreen can be instantiated"""
    screen = ResumeScreen()
    assert screen is not None
    assert screen.screen_name == "resume"


def test_resume_screen_compose():
    """Test that ResumeScreen compose method works without errors"""
    screen = ResumeScreen()
    
    # This should not raise any exceptions
    try:
        compose_result = list(screen.compose())
        assert len(compose_result) > 0
    except Exception as e:
        pytest.fail(f"ResumeScreen.compose() raised an exception: {e}")


def test_resume_screen_get_content():
    """Test that ResumeScreen _get_content method works"""
    screen = ResumeScreen()
    
    # This should not raise any exceptions
    try:
        content = screen._get_content()
        assert content is not None
    except Exception as e:
        pytest.fail(f"ResumeScreen._get_content() raised an exception: {e}")
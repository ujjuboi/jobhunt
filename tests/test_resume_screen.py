"""
Tests for the resume screen functionality
"""
import pytest
from jobhunt.app.screens.resume import ResumeScreen


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

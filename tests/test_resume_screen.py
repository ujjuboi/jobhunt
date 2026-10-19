"""
Tests for the resume screen functionality
"""
import asyncio

import pytest
from unittest.mock import Mock, patch

from jobhunt.app import JobHuntApp
from jobhunt.app.components import ScrollableTextWindow, StatusText
from jobhunt.app.screens.resume import ResumeScreen
from jobhunt.resume.profile_parser import Profile


def test_resume_screen_instantiation():
    screen = ResumeScreen()
    assert screen is not None
    assert screen.screen_name == "resume"


def test_resume_screen_with_db():
    screen = ResumeScreen(database=None)
    assert screen.database is None
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
    mock_database = Mock()
    
    # Create screen with mock database and resume manager
    screen = ResumeScreen(database=mock_database)
    screen.resume_manager = mock_resume_manager
    
    # Test profile auto-save
    with patch.object(screen, 'query_one') as mock_query:
        screen._update_resume_preview("test_resume.docx")
        
        # Verify database save was called
        mock_database.save_profile.assert_called_once()
        
        # Verify status was updated
        mock_query.assert_any_call("#resume_status", StatusText)


def test_resume_screen_profile_auto_save_no_db():
    """Test that profile auto-save doesn't fail when database is None."""
    screen = ResumeScreen(database=None)
    
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


def test_resume_preview_keeps_scrollable_viewport():
    """The resume preview must stay a usable, scrollable viewport on short terminals.

    Regression test for issue #6: the preview is a ``1fr`` TextArea inside a
    clipping container, so the fixed-height chrome above it (title, label,
    Select, status, button row) can squeeze the preview to zero rows on a short
    terminal, leaving scrolling with nowhere to go.
    """

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(120, 20)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#resume_btn")
            await asyncio.sleep(0.1)

            preview = app.screen.query_one("#resume_preview", ScrollableTextWindow)
            preview.text = "\n".join(f"Line {i}: resume content" for i in range(200))
            await asyncio.sleep(0.1)

            assert preview.max_scroll_y > 0
            # ``region`` is the allocated box (see the ``min-height: 5`` rule in
            # app.tcss), which must keep enough rows for the TextArea to scroll.
            assert preview.region.height >= 5

            preview.focus()
            await asyncio.sleep(0.1)
            await pilot.press("pagedown")
            await asyncio.sleep(0.1)
            assert preview.scroll_offset.y > 0

    asyncio.run(run())

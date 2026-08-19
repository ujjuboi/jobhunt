"""
Test cases for the search screen functionality.
"""
import pytest
from unittest.mock import Mock, patch

from jobhunt.app.screens.search import SearchScreen


def _make_job(title, company, job_id=None, location=None, source=None):
    """Build a lightweight job stand-in (Mock is enough for _search)."""
    job = Mock()
    job.title = title
    job.company = company
    job.location = location
    job.description = ""
    job.tags = []
    job.id = job_id or f"{title}-{company}"
    job.source = source or "indeed"
    return job


def _make_config(sources):
    """Build a mocked UserConfig with an iterable enabled-source list."""
    mock_config = Mock()
    mock_config.sources.enabled = list(sources)
    return mock_config


def test_search_with_no_enabled_sources():
    """Test search when no sources are enabled."""
    # Mock the get_user_config function to return a config with no enabled sources
    mock_config = _make_config([])

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        jobs = screen._search("test query")
        assert jobs == []
        assert screen.search_notes == []


def test_search_keyword_source():
    """Test search with a single keyword-searchable source (indeed/linkedin)."""
    mock_config = _make_config(["indeed"])

    # Mock agent and its run_tool method
    mock_agent = Mock()
    mock_agent.run_tool.return_value = [_make_job("Software Engineer", "Test Corp")]

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent

        jobs = screen._search("software engineer")

        # Keyword sources are queried with an empty company (board search)
        mock_agent.run_tool.assert_called_once_with(
            "search_jobs",
            query="software engineer",
            source="indeed",
            company="",
            limit=20,
            raise_errors=True
        )
        assert len(jobs) == 1


def test_search_multiple_keyword_sources():
    """Test search aggregates across multiple keyword-searchable sources."""
    mock_config = _make_config(["indeed", "linkedin"])

    mock_agent = Mock()
    mock_job1 = _make_job("Software Engineer", "Test Corp", source="indeed")
    mock_job2 = _make_job("Frontend Developer", "Another Corp", source="linkedin")

    mock_agent.run_tool.side_effect = [[mock_job1], [mock_job2]]

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent

        jobs = screen._search("engineer")

        assert mock_agent.run_tool.call_count == 2
        assert len(jobs) == 2
        assert {j.source for j in jobs} == {"indeed", "linkedin"}


def test_search_skips_company_only_sources():
    """Greenhouse/Lever/Ashby must not be queried by a keyword search."""
    mock_config = _make_config(["greenhouse", "indeed"])

    mock_agent = Mock()
    mock_agent.run_tool.return_value = [_make_job("Backend Engineer", "Some Corp", source="indeed")]

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent

        jobs = screen._search("engineer")

        # Only the keyword source is queried
        mock_agent.run_tool.assert_called_once()
        assert mock_agent.run_tool.call_args.kwargs["source"] == "indeed"
        assert len(jobs) == 1


def test_search_company_only_sources_produce_note():
    """If only company-only sources are enabled, search reports it as a note."""
    mock_config = _make_config(["greenhouse", "ashby"])

    mock_agent = Mock()

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent

        jobs = screen._search("engineer")

        assert jobs == []
        assert not mock_agent.run_tool.called
        assert len(screen.search_notes) == 1
        assert "greenhouse" in screen.search_notes[0]
        assert "ashby" in screen.search_notes[0]
        assert "keyword search" in screen.search_notes[0]


def test_search_with_source_error_surfaces_notes():
    """Test search when a keyword source fails: note records the failure."""
    mock_config = _make_config(["indeed", "linkedin"])

    mock_agent = Mock()
    mock_job = _make_job("Software Engineer", "Test Corp", source="indeed")
    mock_agent.run_tool.side_effect = [[mock_job], Exception("Board search failed")]

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent

        jobs = screen._search("engineer")

        # Should return results from successful source
        assert len(jobs) == 1
        # And record the failing source for display
        assert len(screen.search_notes) == 1
        assert "linkedin" in screen.search_notes[0]
        assert "Board search failed" in screen.search_notes[0]


def test_search_dedup_empty_title_falls_back_to_id():
    """Test that jobs with empty titles are deduplicated by job.id."""
    mock_config = _make_config(["indeed", "linkedin"])

    mock_agent = Mock()
    mock_job1 = _make_job("", "", job_id="job-1")
    mock_job2 = _make_job("", "", job_id="job-2")
    # A duplicate with same ID as job1
    mock_job3 = _make_job("", "", job_id="job-1")

    mock_agent.run_tool.side_effect = [[mock_job1, mock_job3], [mock_job2]]

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent

        jobs = screen._search("engineer")

        # job-1 and job-2 should be kept, job-3 (duplicate of job-1) dropped
        assert len(jobs) == 2
        ids = [j.id for j in jobs]
        assert "job-1" in ids
        assert "job-2" in ids
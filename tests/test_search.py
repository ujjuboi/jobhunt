"""
Test cases for the search screen (config-driven browse + local filtering).

The screen fetches jobs from every configured source on mount/refresh and
then narrows the result list as the user types. Greenhouse/Lever/Ashby are
company-only boards; only Indeed/LinkedIn provide a site-wide search.
"""
import pytest
from unittest.mock import Mock, patch

from jobhunt.app.screens.search import SearchScreen


def _make_job(title, company, job_id=None, location=None, source=None):
    """Build a lightweight job stand-in (Mock is enough for the screen logic)."""
    job = Mock()
    job.title = title
    job.company = company
    job.location = location
    job.description = ""
    job.tags = []
    job.id = job_id or f"{title}-{company}"
    job.source = source or "indeed"
    return job


def _make_config(sources, companies=None):
    """Build a mocked UserConfig with iterable per-source company lookups."""
    mock_config = Mock()
    mock_config.sources.enabled = list(sources)
    mock_config.sources.companies = dict(companies or {})
    mock_config.companies_for = Mock(
        side_effect=lambda source: list((companies or {}).get(source, []))
    )
    return mock_config


def test_browse_no_enabled_sources_returns_empty():
    """Test browse when no sources are enabled."""
    mock_config = _make_config([])

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        jobs = screen._browse()
        assert jobs == []
        assert screen.search_notes == []


def test_browse_keyword_source_uses_board_search():
    """Indeed/LinkedIn are browsed with a full board search (no company)."""
    mock_config = _make_config(["indeed"])

    mock_agent = Mock()
    mock_agent.run_tool.return_value = [_make_job("Software Engineer", "Test Corp")]

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent

        jobs = screen._browse()

        mock_agent.run_tool.assert_called_once_with(
            "search_jobs",
            query="",
            source="indeed",
            company="",
            limit=50,
            raise_errors=True
        )
        assert len(jobs) == 1


def test_browse_company_only_boards_fetch_each_slug():
    """Greenhouse/Lever/Ashby fetch every configured company slug."""
    mock_config = _make_config(
        ["greenhouse"],
        companies={"greenhouse": ["gitlab", "stripe"]},
    )

    mock_agent = Mock()
    mock_agent.run_tool.side_effect = [
        [_make_job("Backend Engineer", "gitlab", source="greenhouse")],
        [_make_job("Staff Engineer", "stripe", source="greenhouse")],
    ]

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent

        jobs = screen._browse()

        assert mock_agent.run_tool.call_count == 2
        mock_agent.run_tool.assert_any_call(
            "search_jobs", query="", source="greenhouse", company="gitlab",
            limit=50, raise_errors=True
        )
        mock_agent.run_tool.assert_any_call(
            "search_jobs", query="", source="greenhouse", company="stripe",
            limit=50, raise_errors=True
        )
        assert len(jobs) == 2


def test_browse_company_only_without_companies_notes_them():
    """A company-only source with no configured slugs records a note."""
    mock_config = _make_config(["greenhouse"])

    mock_agent = Mock()

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent

        jobs = screen._browse()

        assert jobs == []
        assert not mock_agent.run_tool.called
        assert len(screen.search_notes) == 1
        assert "greenhouse" in screen.search_notes[0]
        assert "no companies configured" in screen.search_notes[0]


def test_browse_surface_source_failures():
    """A failing source/slug is recorded as a note; other results survive."""
    mock_config = _make_config(
        ["greenhouse", "indeed"],
        companies={"greenhouse": ["gitlab"]},
    )

    mock_agent = Mock()
    ok = _make_job("Backend Engineer", "gitlab", source="greenhouse")
    mock_agent.run_tool.side_effect = [[ok], Exception("404 Not Found")]

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent

        jobs = screen._browse()

        assert len(jobs) == 1
        assert any("404" in note for note in screen.search_notes)


def test_browse_dedupes_across_sources_by_title_company():
    """Duplicate (title, company) pairs are dropped across sources."""
    mock_config = _make_config(["indeed", "linkedin"])

    j1 = _make_job("Software Engineer", "Acme", job_id="a", source="indeed")
    j2 = _make_job("Software Engineer", "Acme", job_id="b", source="linkedin")
    j3 = _make_job("Product Manager", "Acme", job_id="c", source="indeed")

    mock_agent = Mock()
    mock_agent.run_tool.side_effect = [[j1, j3], [j2]]

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent

        jobs = screen._browse()

        assert len(jobs) == 2


def test_dedupe_empty_title_falls_back_to_id():
    """Jobs with empty title/company are deduplicated by job.id."""
    screen = SearchScreen()

    j1 = _make_job("", "", job_id="job-1")
    j2 = _make_job("", "", job_id="job-2")
    j3 = _make_job("", "", job_id="job-1")

    jobs = screen._dedupe([j1, j3, j2])

    assert {j.id for j in jobs} == {"job-1", "job-2"}


def test_filter_matches_against_job_fields():
    """Local filtering matches title/company/location/description/tags."""
    screen = SearchScreen()

    j1 = _make_job("Backend Engineer", "gitlab", location="Remote")
    j2 = _make_job("Recruiter", "gitlab")
    j2.tags = ["talent"]

    assert screen._filter([j1, j2], "engineer") == [j1]
    assert screen._filter([j1, j2], "gitlab") == [j1, j2]
    assert screen._filter([j1, j2], "talent") == [j2]


def test_render_filters_and_sets_status(monkeypatch):
    """Typing a query narrows the results and reports the count."""
    mock_config = _make_config(["indeed"])
    screen = SearchScreen()
    screen.status = None

    all_jobs = [_make_job("Backend Engineer", "gitlab"), _make_job("Recruiter", "gitlab")]
    screen.all_jobs = all_jobs

    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        monkeypatch.setattr(screen, "_set_status", lambda msg: setattr(screen, "status", msg))
        monkeypatch.setattr(screen, "query_one", lambda *a, **k: _FakeTextArea())
        screen._render_results("engineer")
        assert "narrowed" in (screen.status or "").lower()

        screen._render_results("")
        assert "2 jobs found" in screen.status


class _FakeTextArea:
    def __init__(self):
        self.text = ""
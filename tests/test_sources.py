"""
Source adapter tests: field mapping, date parsing, dedupe-safe tags, and
Playwright adapters' URL/id extraction. HTTP is mocked so the API-based
tests run offline against fixture payloads.
"""
from pathlib import Path

import httpx

from jobhunt.sources import get_source_adapter
from jobhunt.sources.greenhouse import GreenhouseAdapter
from jobhunt.sources.lever import LeverAdapter
from jobhunt.sources.ashby import AshbyAdapter
from jobhunt.sources.linkedin import LinkedInAdapter
from jobhunt.sources.indeed import IndeedAdapter


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


GREENHOUSE_PAYLOAD = {
    "jobs": [
        {
            "id": 123,
            "title": "Software Engineer",
            "location": {"name": "Remote"},
            "content": "<p>Build things</p>",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
            "updated_at": "2026-08-01T12:00:00Z",
            "departments": [{"name": "Engineering"}, {"name": "Product"}],
        }
    ]
}

LEVER_PAYLOAD = [
    {
        "id": "lever-1",
        "text": "Product Manager",
        "company": "Acme",
        "location": "San Francisco",
        "description": "Own the roadmap",
        "applyUrl": "https://jobs.lever.co/acme/lever-1",
        "createdAt": 1700000000000,
        "categories": {"team": "Product"},
    }
]

ASHBY_PAYLOAD = {
    "apiVersion": "1",
    "jobs": [
        {
            "id": "ashby-1",
            "title": "Backend Engineer",
            "department": "Engineering",
            "location": "New York",
            "descriptionPlain": "Build the platform",
            "applyUrl": "https://jobs.ashbyhq.com/acme/ashby-1",
            "jobUrl": "https://jobs.ashbyhq.com/acme/ashby-1",
            "publishedAt": "2026-07-15T00:00:00Z",
        }
    ],
}


def test_greenhouse_maps_fields(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(GREENHOUSE_PAYLOAD))
    jobs = GreenhouseAdapter().get_jobs("acme")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "123"
    assert job.title == "Software Engineer"
    assert job.company == "acme"
    assert job.location == "Remote"
    assert job.url.endswith("/jobs/123")
    assert job.posted_date is not None
    assert job.posted_date.year == 2026
    assert job.tags == ["Engineering", "Product"]
    assert job.source == "greenhouse"


def test_lever_maps_fields_and_converts_ms_epoch(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(LEVER_PAYLOAD))
    jobs = LeverAdapter().get_jobs("acme")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "lever-1"
    assert job.title == "Product Manager"
    assert job.company == "acme"
    assert job.location == "San Francisco"
    assert job.url == "https://jobs.lever.co/acme/lever-1"
    # createdAt is ms-epoch (1700000000000) -> 2023-11-14
    assert job.posted_date is not None
    assert job.posted_date.year == 2023
    assert job.posted_date.month == 11
    assert job.tags == ["Product"]
    assert job.source == "lever"


def test_ashby_reads_jobs_array(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(ASHBY_PAYLOAD))
    jobs = AshbyAdapter().get_jobs("acme")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "ashby-1"
    assert job.title == "Backend Engineer"
    assert job.company == "acme"
    assert job.location == "New York"
    assert job.url == "https://jobs.ashbyhq.com/acme/ashby-1"
    assert job.posted_date is not None
    assert job.posted_date.year == 2026
    assert job.tags == ["Engineering"]
    assert job.source == "ashby"


def test_ashby_empty_jobs_array_is_not_an_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse({"apiVersion": "1", "jobs": []}))
    assert AshbyAdapter().get_jobs("acme") == []


def test_get_source_adapter():
    """Test that the factory returns the correct adapter types"""
    assert isinstance(get_source_adapter('greenhouse'), GreenhouseAdapter)
    assert isinstance(get_source_adapter('lever'), LeverAdapter)
    assert isinstance(get_source_adapter('ashby'), AshbyAdapter)
    assert isinstance(get_source_adapter('indeed'), IndeedAdapter)

    # LinkedIn uses browser login; a session file is persisted in cache.
    linkedin = get_source_adapter('linkedin')
    assert isinstance(linkedin, LinkedInAdapter)

    try:
        get_source_adapter('unknown-source')
        raise AssertionError("Expected ValueError for unknown source")
    except ValueError:
        pass


def test_linkedin_extracts_job_id():
    """Job ids must be extracted from /jobs/view/<id> hrefs with trailing slashes."""
    adapter = LinkedInAdapter()
    assert adapter._extract_job_id("https://www.linkedin.com/jobs/view/3950772534/") == "3950772534"
    assert adapter._extract_job_id("/jobs/view/3950772534?refId=xyz") == "3950772534"
    assert adapter._extract_job_id("https://www.linkedin.com/jobs/view/12?trk=pp") == "12"
    assert adapter._extract_job_id("") == ""


def _FakePlaywright(behavior):
    """Return a sync_playwright stand-in that records the login interaction."""
    class FakePage:
        def goto(self, url):
            behavior["goto_url"] = url

        def fill(self, selector, value):
            behavior["fills"].append((selector, value))

        def click(self, selector):
            behavior["clicked"] = selector
            behavior["was_clicked"] = True

        def wait_for_url(self, pattern, timeout=None):
            behavior["waited"] = (pattern, timeout)

        def set_default_timeout(self, timeout):
            behavior["default_timeout"] = timeout

    class FakeContext:
        def new_page(self):
            return FakePage()

        def storage_state(self, path=None):
            behavior["saved_state_path"] = path

    class FakeBrowser:
        def __init__(self, headless):
            behavior["headless"] = headless

        def new_context(self, storage_state=None):
            behavior["restored_state"] = storage_state
            return FakeContext()

        def close(self):
            behavior["closed"] = True

    class FakeChromium:
        def launch(self, **kwargs):
            return FakeBrowser(kwargs.get("headless"))

    class FakePlaywright:
        def __init__(self):
            self.chromium = FakeChromium()

        def stop(self):
            behavior["stopped"] = True

    class FakeManager:
        def start(self):
            return FakePlaywright()

    return FakeManager()


def test_linkedin_adapter_login_persists_session(monkeypatch, tmp_path):
    import jobhunt.sources.linkedin as linkedin_module

    behavior = {"fills": [], "was_clicked": False}
    monkeypatch.setattr(linkedin_module, "sync_playwright", lambda: _FakePlaywright(behavior))
    session = str(tmp_path / "linkedin_session.json")

    adapter = LinkedInAdapter(session_file=session)
    assert adapter.login() is True

    assert behavior["headless"] is False
    assert behavior["goto_url"] == "https://www.linkedin.com/login"
    # Browser-only login: the user signs in themselves, so no pre-fill/click.
    assert behavior["fills"] == []
    assert behavior["was_clicked"] is False
    assert behavior["waited"] == ("**/feed/**", 300000)
    assert behavior["saved_state_path"] == session
    assert behavior["default_timeout"] == 60000
    assert behavior["closed"] is True
    assert behavior["stopped"] is True


def test_indeed_extracts_job_id():
    """Indeed ids are the jk query param, not the last path segment."""
    adapter = IndeedAdapter()
    assert adapter._extract_job_id("https://www.indeed.com/viewjob?jk=abc123&tk=xyz") == "abc123"
    assert adapter._extract_job_id("/viewjob?jk=abc123") == "abc123"
    assert adapter._extract_job_id("https://www.indeed.com/rc/clk?jk=def456") == "def456"
    assert adapter._extract_job_id("") == ""


def test_linkedin_session_email_none_without_session(tmp_path):
    """Without a persisted session there can be no account email."""
    adapter = LinkedInAdapter(session_file=str(tmp_path / "missing.json"))
    assert adapter.session_email() is None


def test_linkedin_session_email_resolves_from_me_payload(monkeypatch, tmp_path):
    """session_email must resolve the account from the me payload when signed in."""
    import jobhunt.sources.linkedin as linkedin_module

    session = str(tmp_path / "linkedin_session.json")
    Path(session).write_text("{}")

    class FakeResponse:
        ok = True

        def text(self):
            return '{"emailAddress": "me@example.com"}'

    class FakeRequest:
        def get(self, url, headers=None, timeout=None):
            return FakeResponse()

    class FakePage:
        def set_default_timeout(self, timeout):
            pass

    class FakeContext:
        def new_page(self):
            return FakePage()

        def cookies(self):
            return [{"name": "JSESSIONID", "value": '"token"'}]

        @property
        def request(self):
            return FakeRequest()

        def storage_state(self, path=None):
            pass

    class FakeBrowser:
        def __init__(self, headless):
            behavior["headless"] = headless

        def new_context(self, storage_state=None):
            return FakeContext()

        def close(self):
            behavior["closed"] = True

    class FakeChromium:
        def launch(self, **kwargs):
            return FakeBrowser(kwargs.get("headless"))

    class FakePlaywright:
        def __init__(self):
            self.chromium = FakeChromium()

        def stop(self):
            behavior["stopped"] = True

    class FakeManager:
        def start(self):
            return FakePlaywright()

    behavior = {}
    monkeypatch.setattr(linkedin_module, "sync_playwright", lambda: FakeManager())

    adapter = LinkedInAdapter(session_file=session)
    assert adapter.session_email() == "me@example.com"
    assert behavior["headless"] is True
    assert behavior["closed"] is True
    assert behavior["stopped"] is True
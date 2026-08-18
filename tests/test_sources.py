"""
Source adapter tests: field mapping, date parsing, dedupe-safe tags, and
Playwright adapters' URL/id extraction. HTTP is mocked so the API-based
tests run offline against fixture payloads.
"""
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

    # LinkedIn requires email/password
    try:
        get_source_adapter('linkedin')
        raise AssertionError("Expected ValueError for LinkedIn without credentials")
    except ValueError:
        pass

    linkedin = get_source_adapter('linkedin', email='a@b.c', password='secret')
    assert isinstance(linkedin, LinkedInAdapter)
    assert linkedin.email == 'a@b.c'

    try:
        get_source_adapter('unknown-source')
        raise AssertionError("Expected ValueError for unknown source")
    except ValueError:
        pass


def test_linkedin_extracts_job_id():
    """Job ids must be extracted from /jobs/view/<id> hrefs with trailing slashes."""
    adapter = LinkedInAdapter(email="a@b.c", password="secret")
    assert adapter._extract_job_id("https://www.linkedin.com/jobs/view/3950772534/") == "3950772534"
    assert adapter._extract_job_id("/jobs/view/3950772534?refId=xyz") == "3950772534"
    assert adapter._extract_job_id("https://www.linkedin.com/jobs/view/12?trk=pp") == "12"
    assert adapter._extract_job_id("") == ""


def test_indeed_extracts_job_id():
    """Indeed ids are the jk query param, not the last path segment."""
    adapter = IndeedAdapter()
    assert adapter._extract_job_id("https://www.indeed.com/viewjob?jk=abc123&tk=xyz") == "abc123"
    assert adapter._extract_job_id("/viewjob?jk=abc123") == "abc123"
    assert adapter._extract_job_id("https://www.indeed.com/rc/clk?jk=def456") == "def456"
    assert adapter._extract_job_id("") == ""
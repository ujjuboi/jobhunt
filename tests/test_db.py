"""
Database repository tests: save/get round-trips and ordering.
"""
from datetime import datetime, timedelta

from jobhunt.db import JobHuntDB
from jobhunt.models import Job, Application, Profile, Resume


def _make_job(job_id: str, title: str, posted_date: datetime | None) -> Job:
    return Job(
        id=job_id,
        title=title,
        company="Acme",
        location="Remote",
        description="Do the thing",
        url=f"https://example.com/jobs/{job_id}",
        posted_date=posted_date,
        tags=["Engineering"],
        source="test",
        fit_score=0.8,
        fit_explanation="decent",
    )


def test_job_save_and_get_round_trip(tmp_path):
    db = JobHuntDB(str(tmp_path / "test.db"))
    job = _make_job("j1", "Engineer", datetime(2026, 8, 1, 12, 0, 0))
    assert db.save_job(job)
    retrieved = db.get_job("j1")
    assert retrieved is not None
    assert retrieved.title == "Engineer"
    assert retrieved.company == "Acme"
    assert retrieved.posted_date == job.posted_date
    assert retrieved.tags == ["Engineering"]
    assert retrieved.fit_score == 0.8
    assert retrieved.source == "test"


def test_get_jobs_orders_by_posted_date_desc(tmp_path):
    db = JobHuntDB(str(tmp_path / "test.db"))
    base = datetime(2026, 8, 1, 12, 0, 0)
    db.save_job(_make_job("old", "Old Job", base - timedelta(days=30)))
    db.save_job(_make_job("new", "New Job", base))
    db.save_job(_make_job("none", "No Date", None))
    jobs = db.get_jobs()
    assert [j.id for j in jobs] == ["new", "old", "none"]


def test_application_save_and_get_round_trip(tmp_path):
    db = JobHuntDB(str(tmp_path / "test.db"))
    db.save_job(_make_job("j1", "Engineer", None))
    app = Application(job_id="j1", status="applied", applied_date=datetime(2026, 8, 2), notes="n")
    assert db.save_application(app)
    retrieved = db.get_application("j1")
    assert retrieved is not None
    assert retrieved.status == "applied"
    assert retrieved.applied_date == app.applied_date
    assert retrieved.notes == "n"


def test_embedding_save_and_get_round_trip(tmp_path):
    db = JobHuntDB(str(tmp_path / "test.db"))
    vector = [0.1, 0.2, 0.3]
    assert db.save_embedding("job", "j1", vector)
    assert db.get_embedding("job", "j1") == vector
    assert db.get_embedding("job", "missing") is None


def test_profile_save_and_get_round_trip(tmp_path):
    db = JobHuntDB(str(tmp_path / "test.db"))
    profile = Profile(name="Ada Lovelace", email="ada@example.com", skills=["Python"])
    assert db.save_profile(profile)
    retrieved = db.get_profile()
    assert retrieved is not None
    assert retrieved.name == "Ada Lovelace"
    assert retrieved.skills == ["Python"]


def test_resume_save_and_get_round_trip(tmp_path):
    db = JobHuntDB(str(tmp_path / "test.db"))
    resume = Resume(id="r1", job_id="j1", content="content", path="/tmp/r1.docx", generated_at=datetime(2026, 8, 1))
    assert db.save_resume(resume)
    retrieved = db.get_resume("r1")
    assert retrieved is not None
    assert retrieved.path == "/tmp/r1.docx"
    assert retrieved.generated_at == resume.generated_at

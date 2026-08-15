"""
ScorePipeline tests: semantic ranking, embedding dedupe, LLM confirm modes.
Uses a deterministic bag-of-words fake embedding client and a fake agent.
"""
import re
import zlib

import pytest

from jobhunt.config import get_scoring_mode
from jobhunt.db import JobHuntDB
from jobhunt.models import Job, Profile
from jobhunt.scoring import ScorePipeline, DEDUPE_THRESHOLD


DIM = 16


def _bow_vector(text, dim=DIM):
    vec = [0.0] * dim
    for token in re.findall(r"\w+", text.lower()):
        vec[zlib.crc32(token.encode("utf-8")) % dim] += 1.0
    norm = sum(x * x for x in vec) ** 0.5
    if norm:
        vec = [x / norm for x in vec]
    return vec


class FakeEmbeddings:
    def __init__(self):
        self.embed_calls = 0

    def embed_text(self, text, model="bge-m3-mlx-fp16", use_bge_prefix=False):
        self.embed_calls += 1
        return _bow_vector(text)

    def embed_batch(self, texts, model="bge-m3-mlx-fp16", use_bge_prefix=False):
        self.embed_calls += 1
        return [_bow_vector(t) for t in texts]

    def close(self):
        pass


class FakeAgent:
    def __init__(self, score=0.9):
        self.score = score

    def chat_with_agent(self, messages):
        return {
            "score": self.score,
            "explanation": "great fit",
            "matched_skills": ["python"],
            "missing_skills": ["docker"],
            "suggested_bullets": ["built services in Python"],
        }


def _job(job_id, title, description):
    return Job(id=job_id, title=title, company="Acme", description=description, source="test")


def _profile(skills=("python", "backend"), summary="python backend engineer"):
    return Profile(name="Ada", summary=summary, skills=list(skills))


@pytest.fixture
def db(tmp_path):
    return JobHuntDB(str(tmp_path / "test.db"))


def _score(db, jobs, profile, mode, embeddings=None, agent=None, top_n=15):
    pipeline = ScorePipeline(db, embeddings or FakeEmbeddings(), agent=agent)
    return pipeline.score(jobs, profile, mode=mode, top_n=top_n)


def test_semantic_mode_ranks_by_relevance(db):
    jobs = [
        _job("j1", "Backend Engineer", "python backend services and databases"),
        _job("j2", "UI Designer", "react typescript css and ui design"),
        _job("j3", "Data Scientist", "machine learning pandas and statistics"),
    ]
    profile = _profile(summary="python backend engineer", skills=["python", "backend", "sql", "statistics"])
    fits = _score(db, jobs, profile, mode="embedding")
    assert [f.job_id for f in fits] == ["j1", "j3", "j2"]
    assert fits[0].score > fits[-1].score


def test_hybrid_uses_llm_confirm_on_top_n(db):
    jobs = [_job(f"j{i}", f"Job {i}", f"python backend role number {i}") for i in range(5)]
    profile = _profile()
    agent = FakeAgent(score=0.88)
    fits = _score(db, jobs, profile, mode="hybrid", agent=agent, top_n=2)
    # Exactly the top-2 semantic candidates were LLM-confirmed.
    confirmed = [f for f in fits if f.explanation == "great fit"]
    assert len(confirmed) == 2
    for f in confirmed:
        assert f.score == 0.88
        assert f.matched_skills == ["python"]


def test_llm_mode_confirms_every_job(db):
    jobs = [_job(f"j{i}", f"Job {i}", f"python role {i}") for i in range(3)]
    agent = FakeAgent(score=0.77)
    fits = _score(db, jobs, profile=_profile(), mode="llm", agent=agent)
    assert len(fits) == 3
    assert all(f.explanation == "great fit" for f in fits)


def test_dedupe_skips_near_duplicates(db):
    desc = "senior python backend engineer building apis and data pipelines"
    jobs = [
        _job("dup1", "Backend Engineer", desc),
        _job("dup2", "Backend Engineer (Senior)", desc),
        _job("other", "Frontend Engineer", "react ui design typescript css"),
    ]
    embeddings = FakeEmbeddings()
    fits = _score(db, jobs, profile=_profile(), mode="embedding", embeddings=embeddings)
    ids = [f.job_id for f in fits]
    assert "other" in ids
    assert len(ids) == 2  # one of dup1/dup2 was dropped
    assert not ("dup1" in ids and "dup2" in ids)


def test_embedding_mode_without_profile_vector_returns_empty(db):
    # A profile with no embeddable text yields no profile vector.
    jobs = [_job("j1", "Backend Engineer", "python backend")]
    profile = Profile(name="Noop")
    fits = _score(db, jobs, profile, mode="embedding")
    assert fits == []


def test_profile_embedding_is_cached(db):
    embeddings = FakeEmbeddings()
    pipeline = ScorePipeline(db, embeddings)
    profile = _profile()
    pipeline.ensure_profile_embedding(profile)
    calls_after_first = embeddings.embed_calls
    pipeline.ensure_profile_embedding(profile)
    assert embeddings.embed_calls == calls_after_first


def test_similar_jobs_ranks_most_similar_first(db):
    jobs = [
        _job("base", "Backend Engineer", "python backend services"),
        _job("near", "Python Backend Dev", "backend python services apis"),
        _job("far", "Designer", "branding figma and visual design"),
    ]
    for job in jobs:
        db.save_job(job)
    embeddings = FakeEmbeddings()
    pipeline = ScorePipeline(db, embeddings)
    similar = pipeline.similar_jobs("base", limit=2)
    assert [j.id for j in similar] == ["near", "far"]


def test_scoring_mode_config_default_and_override(monkeypatch):
    monkeypatch.delenv("JOBHUNT_SCORING_MODE", raising=False)
    assert get_scoring_mode() == "hybrid"
    monkeypatch.setenv("JOBHUNT_SCORING_MODE", "llm")
    assert get_scoring_mode() == "llm"


def test_scoring_mode_rejects_invalid(monkeypatch):
    monkeypatch.setenv("JOBHUNT_SCORING_MODE", "bogus")
    with pytest.raises(ValueError):
        get_scoring_mode()

"""
Fit scoring pipeline for JobHunt.

Hybrid mode: embedding (semantic) stage over all jobs, then an LLM confirm
stage over the top candidates. Also supports embedding-only and LLM-only
modes via `scoring.mode` (see config.get_scoring_mode).
"""
import logging
import os
import re
from typing import List, Dict, Optional

from ..config import get_scoring_mode, get_user_config
from ..db import JobHuntDB
from ..embeddings import EmbeddingClient
from ..models import Job, Profile, FitScore
from ..llm import DEFAULT_CHAT_MODEL

logger = logging.getLogger(__name__)

DEDUPE_THRESHOLD = 0.95
LLM_CONFIRM_TOP_N = 15


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


class ScorePipeline:
    """Ranks jobs against a profile and produces explainable FitScores."""

    def __init__(self, db: JobHuntDB, embedding_client: EmbeddingClient, agent=None):
        self.db = db
        self.embeddings = embedding_client
        self.agent = agent

    def _job_text(self, job: Job) -> str:
        return _strip_html(f"{job.title}\n{job.description}").strip()

    def _profile_text(self, profile: Profile) -> str:
        parts = [profile.summary or ""]
        parts.extend(
            " ".join(str(e.get(k, "")) for k in ("title", "company", "description"))
            for e in profile.experience
        )
        parts.append(" ".join(profile.skills))
        return "\n".join(p for p in parts if p).strip()

    def ensure_profile_embedding(self, profile: Profile) -> Optional[List[float]]:
        """Return the profile embedding, computing and caching it if missing."""
        text = self._profile_text(profile)
        if not text:
            return None
        cached = self.db.get_profile_embedding()
        if cached:
            return cached
        vector = self.embeddings.embed_text(text, use_bge_prefix=True)
        if vector:
            self.db.save_embedding("profile", "profile", vector)
        return vector

    def ensure_job_embeddings(self, jobs: List[Job]) -> Dict[str, List[float]]:
        """Return job embeddings keyed by job id, computing and caching missing ones."""
        vectors: Dict[str, List[float]] = {}
        missing = []
        for job in jobs:
            cached = self.db.get_embedding("job", job.id)
            if cached:
                vectors[job.id] = cached
            else:
                missing.append(job)

        if missing:
            batch = self.embeddings.embed_batch([self._job_text(j) for j in missing])
            if batch:
                for job, vector in zip(missing, batch):
                    vectors[job.id] = vector
                    self.db.save_embedding("job", job.id, vector)
        return vectors

    def _semantic_scores(
        self, job_vectors: Dict[str, List[float]], profile_vector: List[float]
    ) -> Dict[str, float]:
        return {
            job_id: self.db.cosine_similarity(vector, profile_vector)
            for job_id, vector in job_vectors.items()
        }

    def _dedupe_jobs(
        self, jobs: List[Job], job_vectors: Dict[str, List[float]]
    ) -> List[Job]:
        """Drop near-duplicate jobs (embedding cosine > threshold)."""
        kept = []
        seen_vectors: List[List[float]] = []
        for job in jobs:
            vector = job_vectors.get(job.id)
            if vector is None:
                kept.append(job)
                continue
            if any(self.db.cosine_similarity(vector, other) > DEDUPE_THRESHOLD for other in seen_vectors):
                continue
            seen_vectors.append(vector)
            kept.append(job)
        return kept

    def _llm_confirm(self, job: Job, profile: Profile) -> Optional[FitScore]:
        """Score a job via the LLM using a strict JSON response."""
        if self.agent is None:
            return None
        config = get_user_config()
        score_prompt = config.prompts.score or (
            'Score how well this candidate profile fits this job posting. '
            'Respond with JSON only, using keys: "score" (0.0 to 1.0), '
            '"explanation" (short reason), "matched_skills" (list), '
            '"missing_skills" (list), "suggested_bullets" (list).'
        )
        prompt = (
            f"{score_prompt}\n\n"
            f"JOB:\n{self._job_text(job)[:2000]}\n\n"
            f"PROFILE:\n{self._profile_text(profile)[:2000]}"
        )
        # Check for environment variable override
        confirm_model = os.environ.get("JOBHUNT_CONFIRM_MODEL")
        if not confirm_model:
            # Fall back to config
            confirm_model = config.model.confirm
        # Only ask for a specific model when the user configured one explicitly;
        # otherwise let the agent use its own default.
        kwargs = {}
        if confirm_model and confirm_model != DEFAULT_CHAT_MODEL:
            kwargs["model"] = confirm_model
        try:
            data = self.agent.chat_with_agent(
                [
                    {"role": "system", "content": "You are a job-fit analyzer returning strict JSON."},
                    {"role": "user", "content": prompt},
                ],
                **kwargs,
            )
            raw_score = float(data.get("score", 0.0))
            # Models sometimes return 0-100 instead of 0-1; normalize.
            score = raw_score / 100.0 if raw_score > 1.0 else raw_score
            score = max(0.0, min(1.0, score))
            return FitScore(
                job_id=job.id,
                score=score,
                explanation=str(data.get("explanation", "")),
                matched_skills=list(data.get("matched_skills", [])),
                missing_skills=list(data.get("missing_skills", [])),
                suggested_bullets=list(data.get("suggested_bullets", [])),
            )
        except Exception as e:
            logger.warning("LLM fit confirm failed for %s: %s", job.id, e, exc_info=True)
            return None

    @staticmethod
    def _semantic_fit(job: Job, score: float) -> FitScore:
        return FitScore(
            job_id=job.id,
            score=round(score, 4),
            explanation=f"Embedding similarity: {score:.2f}",
            matched_skills=[],
            missing_skills=[],
            suggested_bullets=[],
        )

    def score(
        self,
        jobs: List[Job],
        profile: Profile,
        mode: Optional[str] = None,
        top_n: int = LLM_CONFIRM_TOP_N,
    ) -> List[FitScore]:
        """Rank jobs and return explainable FitScores for the requested mode."""
        if mode is None:
            mode = get_scoring_mode()

        profile_vector = self.ensure_profile_embedding(profile)
        job_vectors = self.ensure_job_embeddings(jobs)
        jobs = self._dedupe_jobs(jobs, job_vectors)

        semantic = self._semantic_scores(job_vectors, profile_vector) if profile_vector else {}

        if mode == "embedding":
            if not profile_vector:
                return []
            ranked = sorted(jobs, key=lambda j: semantic.get(j.id, 0.0), reverse=True)
            results = [self._semantic_fit(j, semantic.get(j.id, 0.0)) for j in ranked]
            results.sort(key=lambda f: f.score, reverse=True)
            return results

        # llm / hybrid modes
        if mode == "llm":
            ranked = jobs
        elif mode == "hybrid":
            ranked = sorted(jobs, key=lambda j: semantic.get(j.id, 0.0), reverse=True)
        else:
            raise ValueError(f"Invalid scoring mode: {mode}")

        confirm_set = ranked if mode == "llm" else ranked[:top_n]
        confirmed = {}
        for job in confirm_set:
            fit = self._llm_confirm(job, profile)
            if fit is not None:
                confirmed[job.id] = fit

        results = []
        for job in ranked:
            if job.id in confirmed:
                results.append(confirmed[job.id])
            elif mode == "llm":
                continue
            else:
                results.append(self._semantic_fit(job, semantic.get(job.id, 0.0)))
        results.sort(key=lambda f: f.score, reverse=True)
        return results

    def similar_jobs(self, job_id: str, limit: int = 10) -> List[Job]:
        """Return the jobs most similar to job_id by embedding cosine."""
        job = self.db.get_job(job_id)
        if not job:
            return []
        others = [o for o in self.db.get_jobs(limit=1000) if o.id != job_id]
        vectors = self.ensure_job_embeddings([job] + others)
        vector = vectors.get(job_id)
        if not vector:
            return []

        scored = []
        for other in others:
            other_vec = vectors.get(other.id)
            if other_vec:
                scored.append((self.db.cosine_similarity(vector, other_vec), other))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [other for _, other in scored[:limit]]

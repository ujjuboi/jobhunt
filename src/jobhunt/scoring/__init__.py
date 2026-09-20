"""
Fit scoring pipeline for JobHunt.

Hybrid mode: embedding (semantic) stage over all jobs, then an LLM confirm
stage over the top candidates. Also supports embedding-only and LLM-only
modes via `scoring.mode` (see config.get_scoring_mode).
"""
import logging
import os
import re
from typing import Dict, List, Optional

from ..config import get_scoring_mode, get_user_config
from ..db import JobHuntDB
from ..embeddings import EmbeddingClient
from ..llm import DEFAULT_CHAT_MODEL
from ..models import FitScore, Job, Profile

logger = logging.getLogger(__name__)

DEDUPE_THRESHOLD = 0.95
LLM_CONFIRM_TOP_N = 15


def _strip_html(text: str) -> str:
    """Strip HTML tags from a string.

    Args:
        text: The raw text, possibly containing HTML markup.

    Returns:
        The text with all tags replaced by single spaces.
    """
    return re.sub(r"<[^>]+>", " ", text or "")


class ScorePipeline:
    """Ranks jobs against a profile and produces explainable FitScores.

    Args:
        database: The database used for embedding caching and lookups.
        embedding_client: The client used to compute embeddings.
        agent: Optional agent used for the LLM confirm stage.
    """

    def __init__(
        self,
        database: JobHuntDB,
        embedding_client: EmbeddingClient,
        agent=None,
    ):
        self.database = database
        self.embeddings = embedding_client
        self.agent = agent

    def _job_text(self, job: Job) -> str:
        """Build the plain-text representation of a job for embedding.

        Args:
            job: The job to flatten.

        Returns:
            A single string of title and description with HTML stripped.
        """
        return _strip_html(f"{job.title}\n{job.description}").strip()

    def _profile_text(self, profile: Profile) -> str:
        """Build the plain-text representation of a profile for embedding.

        Args:
            profile: The candidate profile to flatten.

        Returns:
            A newline-joined string of summary, experience, and skills.
        """
        parts = [profile.summary or ""]
        parts.extend(
            " ".join(str(entry.get(k, "")) for k in ("title", "company", "description"))
            for entry in profile.experience
        )
        parts.append(" ".join(profile.skills))
        return "\n".join(part for part in parts if part).strip()

    def ensure_profile_embedding(self, profile: Profile) -> Optional[List[float]]:
        """Return the profile embedding, computing and caching it if missing.

        Args:
            profile: The profile whose embedding is needed.

        Returns:
            The cached or freshly computed embedding, or ``None`` when the
            profile has no embeddable text.
        """
        text = self._profile_text(profile)
        if not text:
            return None
        cached = self.database.get_profile_embedding()
        if cached:
            return cached
        vector = self.embeddings.embed_text(text, use_bge_prefix=True)
        if vector:
            self.database.save_embedding("profile", "profile", vector)
        return vector

    def ensure_job_embeddings(self, jobs: List[Job]) -> Dict[str, List[float]]:
        """Return job embeddings keyed by job id, computing and caching missing ones.

        Args:
            jobs: The jobs whose embeddings are needed.

        Returns:
            A mapping of job id to its embedding vector.
        """
        vectors: Dict[str, List[float]] = {}
        missing_jobs = []
        for job_entry in jobs:
            cached = self.database.get_embedding("job", job_entry.id)
            if cached:
                vectors[job_entry.id] = cached
            else:
                missing_jobs.append(job_entry)

        if missing_jobs:
            batch = self.embeddings.embed_batch(
                [self._job_text(entry) for entry in missing_jobs]
            )
            if batch:
                for job_entry, vector in zip(missing_jobs, batch):
                    vectors[job_entry.id] = vector
                    self.database.save_embedding("job", job_entry.id, vector)
        return vectors

    def _semantic_scores(
        self,
        job_vectors: Dict[str, List[float]],
        profile_vector: List[float],
    ) -> Dict[str, float]:
        """Compute cosine similarity of every job vector against the profile.

        Args:
            job_vectors: Job ids mapped to their embedding vectors.
            profile_vector: The profile embedding vector.

        Returns:
            A mapping of job id to its semantic similarity score.
        """
        return {
            job_id: self.database.cosine_similarity(vector, profile_vector)
            for job_id, vector in job_vectors.items()
        }

    def _dedupe_jobs(
        self,
        jobs: List[Job],
        job_vectors: Dict[str, List[float]],
    ) -> List[Job]:
        """Drop near-duplicate jobs (embedding cosine > threshold).

        Args:
            jobs: The jobs to filter.
            job_vectors: Job ids mapped to their embedding vectors.

        Returns:
            The jobs with near-duplicates removed, in original order.
        """
        deduplicated: List[Job] = []
        seen_vectors: List[List[float]] = []
        for job_entry in jobs:
            vector = job_vectors.get(job_entry.id)
            if vector is None:
                deduplicated.append(job_entry)
                continue
            if any(
                self.database.cosine_similarity(vector, other) > DEDUPE_THRESHOLD
                for other in seen_vectors
            ):
                continue
            seen_vectors.append(vector)
            deduplicated.append(job_entry)
        return deduplicated

    def _llm_confirm(self, job: Job, profile: Profile) -> Optional[FitScore]:
        """Score a job via the LLM using a strict JSON response.

        Args:
            job: The job to score.
            profile: The candidate profile to score against.

        Returns:
            A :class:`FitScore`, or ``None`` when the LLM stage fails or no
            agent is available.
        """
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
        except Exception as error:
            logger.warning("LLM fit confirm failed for %s: %s", job.id, error, exc_info=True)
            return None

    @staticmethod
    def _semantic_fit(job: Job, score: float) -> FitScore:
        """Build a semantic-only FitScore for a job.

        Args:
            job: The job that was scored.
            score: The raw semantic similarity score.

        Returns:
            A :class:`FitScore` with an embedding-similarity explanation.
        """
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
        """Rank jobs and return explainable FitScores for the requested mode.

        Args:
            jobs: The jobs to score.
            profile: The candidate profile to score against.
            mode: ``hybrid`` (default), ``embedding``, or ``llm``; falls back
                to the configured scoring mode when ``None``.
            top_n: Number of top semantic candidates to LLM-confirm in hybrid
                mode.

        Returns:
            The ranked :class:`FitScore` results.

        Raises:
            ValueError: When ``mode`` names an unknown scoring mode.
        """
        if mode is None:
            mode = get_scoring_mode()

        profile_vector = self.ensure_profile_embedding(profile)
        job_vectors = self.ensure_job_embeddings(jobs)
        jobs = self._dedupe_jobs(jobs, job_vectors)

        semantic = self._semantic_scores(job_vectors, profile_vector) if profile_vector else {}

        if mode == "embedding":
            if not profile_vector:
                return []
            ranked = sorted(jobs, key=lambda job_entry: semantic.get(job_entry.id, 0.0), reverse=True)
            results = [self._semantic_fit(entry, semantic.get(entry.id, 0.0)) for entry in ranked]
            results.sort(key=lambda fit_score: fit_score.score, reverse=True)
            return results

        # llm / hybrid modes
        if mode == "llm":
            ranked = jobs
        elif mode == "hybrid":
            ranked = sorted(jobs, key=lambda job_entry: semantic.get(job_entry.id, 0.0), reverse=True)
        else:
            raise ValueError(f"Invalid scoring mode: {mode}")

        confirm_set = ranked if mode == "llm" else ranked[:top_n]
        confirmed = {}
        for job_entry in confirm_set:
            fit_score = self._llm_confirm(job_entry, profile)
            if fit_score is not None:
                confirmed[job_entry.id] = fit_score

        results = []
        for job_entry in ranked:
            if job_entry.id in confirmed:
                results.append(confirmed[job_entry.id])
            elif mode == "llm":
                continue
            else:
                results.append(self._semantic_fit(job_entry, semantic.get(job_entry.id, 0.0)))
        results.sort(key=lambda fit_score: fit_score.score, reverse=True)
        return results

    def similar_jobs(self, job_id: str, limit: int = 10) -> List[Job]:
        """Return the jobs most similar to ``job_id`` by embedding cosine.

        Args:
            job_id: The job whose nearest neighbours to find.
            limit: Maximum number of similar jobs to return.

        Returns:
            The most similar jobs, most similar first.
        """
        job = self.database.get_job(job_id)
        if not job:
            return []
        others = [o for o in self.database.get_jobs(limit=1000) if o.id != job_id]
        vectors = self.ensure_job_embeddings([job] + others)
        vector = vectors.get(job_id)
        if not vector:
            return []

        scored = []
        for other_job in others:
            other_vec = vectors.get(other_job.id)
            if other_vec:
                scored.append((self.database.cosine_similarity(vector, other_vec), other_job))
        scored.sort(key=lambda scored_entry: scored_entry[0], reverse=True)
        return [other_job for _, other_job in scored[:limit]]
"""
Agent module for JobHunt.

Handles tool calling and the agent loop. :class:`ToolRegistry` exposes the
tools the UI and agents can invoke; :class:`JobHuntAgent` wires those tools
to the oMLX-backed chat client.
"""
import json
import logging
import os
from typing import Any, Dict, Iterator, List, Optional

from openai import OpenAI

from .. import llm
from ..config import get_omlx_settings, get_user_config
from ..db import JobHuntDB
from ..embeddings import EmbeddingClient
from ..llm import get_default_model
from ..models import Application, FitScore, Job, Profile
from ..sources import get_source_adapter
from ..scoring import ScorePipeline

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for all available agent tools.

    Args:
        database: The database the tools read/write through.
        agent: The agent these tools serve (used for LLM-backed scoring).
    """

    def __init__(self, database: JobHuntDB = None, agent=None) -> None:
        self.tools: Dict[str, Any] = {}
        self.database = database
        self.agent = agent
        self.register_tool("search_jobs", self.search_jobs)
        self.register_tool("get_job_detail", self.get_job_detail)
        self.register_tool("score_fit", self.score_fit)
        self.register_tool("tailor_resume", self.tailor_resume)
        self.register_tool("generate_cover_letter", self.generate_cover_letter)
        self.register_tool("update_status", self.update_status)
        self.register_tool("list_jobs", self.list_jobs)

    def register_tool(self, name: str, func) -> None:
        """Register a tool function.

        Args:
            name: The tool name used to invoke it.
            func: The callable implementing the tool.
        """
        self.tools[name] = func

    def get_tool(self, name: str):
        """Get a tool function by name.

        Args:
            name: The tool name to look up.

        Returns:
            The registered callable, or ``None`` when unknown.
        """
        return self.tools.get(name)

    def list_tools(self) -> List[str]:
        """Return the names of all registered tools.

        Returns:
            Sorted-in-insertion-order list of tool names.
        """
        return list(self.tools.keys())

    def _dedupe_jobs(self, jobs: List[Job]) -> List[Job]:
        """Remove in-batch duplicates by job id and (title, company).

        Re-fetched jobs that are already stored in the database are kept so
        repeated browses still list them; ``save_job`` upserts by id.

        Args:
            jobs: The raw list of fresh jobs from a source adapter.

        Returns:
            A deduplicated list preserving first-seen order.
        """
        deduplicated = []
        seen_ids: set = set()
        seen_keys: set = set()

        for job_entry in jobs:
            job_id = getattr(job_entry, "id", None) or ""
            if job_id and job_id in seen_ids:
                continue
            if job_id:
                seen_ids.add(job_id)

            title = (job_entry.title or "").lower()
            company = (job_entry.company or "").lower()
            dedupe_key = (title, company) if (title or company) else job_id
            if dedupe_key and dedupe_key in seen_keys:
                continue
            if dedupe_key:
                seen_keys.add(dedupe_key)
            deduplicated.append(job_entry)

        return deduplicated

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def search_jobs(
        self,
        query: str,
        source: str = "",
        company: str = "",
        limit: int = 50,
        raise_errors: bool = False,
    ) -> List[Job]:
        """Search for jobs using a query on the specified source.

        Args:
            query: The keyword query (empty for company-board browsing).
            source: The source to search; defaults to the first enabled
                source in the user config.
            company: Optional company slug (required for board-only sources).
            limit: Maximum number of jobs to fetch.
            raise_errors: When True, re-raise adapter failures instead of
                silently returning ``[]``.

        Returns:
            The fetched (and deduplicated) jobs, saved to the database.
        """
        if not self.database:
            return []

        # Resolve default source from user config when not specified explicitly.
        config = get_user_config()
        if not source:
            source = config.sources.enabled[0] if config.sources.enabled else "greenhouse"

        try:
            adapter = get_source_adapter(source)

            if company:
                jobs = adapter.get_jobs(company, limit, raise_errors=raise_errors)
            else:
                jobs = adapter.search_jobs(query, limit, raise_errors=raise_errors)

            # Deduplicate jobs
            jobs = self._dedupe_jobs(jobs)

            # Save jobs to database (also set source on each job)
            for job_entry in jobs:
                # Set the source on each job (for the UI to display it)
                job_entry.source = source
                self.database.save_job(job_entry)

            return jobs

        except Exception as error:
            logger.warning("Error searching jobs via %s: %s", source, error, exc_info=True)
            if raise_errors:
                raise
            return []

    def get_job_detail(self, job_id: str) -> Optional[Job]:
        """Get detailed information about a specific job.

        Args:
            job_id: The database id of the job to look up.

        Returns:
            The stored job, or ``None`` when not found.
        """
        if not self.database:
            return None

        try:
            # Try to get from local database first
            return self.database.get_job(job_id)
        except Exception as error:
            logger.warning("Error getting job detail for %s: %s", job_id, error, exc_info=True)
            return None

    def score_fit(self, job_id: str, profile: Profile) -> FitScore:
        """Score job fit against profile using the hybrid embedding + LLM pipeline.

        Args:
            job_id: The id of the job to score.
            profile: The candidate profile to score against.

        Returns:
            A :class:`FitScore`, with a zero score and explanatory text when
            scoring cannot be completed.
        """
        def _failed(message: str) -> FitScore:
            return FitScore(
                job_id=job_id,
                score=0.0,
                explanation=message,
                matched_skills=[],
                missing_skills=[],
                suggested_bullets=[],
            )

        if not self.database:
            return _failed("No database available")
        job_entry = self.database.get_job(job_id)
        if not job_entry:
            return _failed(f"Job {job_id} not found")
        try:
            pipeline = ScorePipeline(self.database, EmbeddingClient(), agent=self.agent)
            results = pipeline.score([job_entry], profile, mode="hybrid", top_n=1)
            return results[0] if results else _failed("No score could be computed")
        except Exception as error:
            logger.warning("Fit scoring failed for job %s: %s", job_id, error, exc_info=True)
            return _failed(f"Fit scoring failed: {error}")

    def tailor_resume(self, job_id: str, profile: Profile) -> str:
        """Tailor a resume for a specific job.

        Args:
            job_id: The id of the job to tailor for.
            profile: The candidate profile to tailor.

        Returns:
            A JSON string describing the result and artifact paths.
        """
        job_entry = self.database.get_job(job_id) if self.database else None
        if not job_entry:
            return f"Job {job_id} not found"

        try:
            from ..resume import ResumeManager
            from ..resume.profile_parser import Profile as RProfile

            manager = ResumeManager()
            resume_profile = self._convert_profile(profile)

            tailored = manager.generate_tailored_resume(
                resume_profile, job_entry.description, agent=self.agent,
            )
            artifacts = manager.save_tailored_resume(
                tailored, job_entry.company, job_entry.id,
            )
            return json.dumps({
                "status": "ok",
                "summary": tailored.summary,
                "skills": tailored.updated_skills,
                "artifacts": artifacts,
            }, indent=2)
        except FileNotFoundError as error:
            return f"Resume directory not found: {error}"
        except Exception as error:
            logger.exception("tailor_resume failed")
            return f"Error tailoring resume: {error}"

    def generate_cover_letter(self, job_id: str, profile: Profile) -> str:
        """Generate a cover letter for a specific job.

        Args:
            job_id: The id of the job to write for.
            profile: The candidate profile to write from.

        Returns:
            A JSON string describing the result and artifact path.
        """
        job_entry = self.database.get_job(job_id) if self.database else None
        if not job_entry:
            return f"Job {job_id} not found"

        try:
            from ..resume import ResumeManager

            manager = ResumeManager()
            resume_profile = self._convert_profile(profile)

            cover_letter = manager.generate_cover_letter(
                resume_profile, job_entry.description,
                company_name=job_entry.company, agent=self.agent,
            )
            path = manager.save_cover_letter_to_output(
                cover_letter, job_entry.company, job_entry.id,
            )
            return json.dumps({
                "status": "ok",
                "path": path,
                "preview": cover_letter.content[:500],
            }, indent=2)
        except FileNotFoundError as error:
            return f"Resume directory not found: {error}"
        except Exception as error:
            logger.exception("generate_cover_letter failed")
            return f"Error generating cover letter: {error}"

    @staticmethod
    def _convert_profile(profile: Profile):
        """Convert models.Profile (dict-style) to resume Profile sections.

        Args:
            profile: The database-style :class:`Profile` to convert.

        Returns:
            A :class:`jobhunt.resume.profile_parser.Profile` with
            experience/education/projects mapped to ResumeSections.
        """
        from ..resume.profile_parser import Profile as RProfile, ResumeSection

        def _dicts_to_sections(items):
            sections = []
            for piece in items:
                if isinstance(piece, dict):
                    sections.append(ResumeSection(
                        title=piece.get("title", ""),
                        content=piece.get("content", ""),
                        bullets=piece.get("bullets", []),
                    ))
                elif hasattr(piece, "title"):
                    sections.append(piece)
            return sections

        return RProfile(
            name=profile.name or "",
            email=profile.email or "",
            phone=profile.phone or "",
            summary=profile.summary or "",
            skills=profile.skills or [],
            certifications=profile.certifications or [],
            experience=_dicts_to_sections(profile.experience),
            education=_dicts_to_sections(profile.education),
            projects=_dicts_to_sections(profile.projects),
        )

    def update_status(self, job_id: str, status: str) -> bool:
        """Update a job's application status.

        Args:
            job_id: The id of the job to update.
            status: The new application status (e.g. ``saved``, ``applied``).

        Returns:
            True when the application entry was saved.
        """
        if not self.database:
            return False

        try:
            # Get the job to make sure it exists
            job_entry = self.database.get_job(job_id)
            if not job_entry:
                return False

            # Create application entry
            application = Application(
                job_id=job_id,
                status=status,
                applied_date=None,  # Set to current time if status is 'applied'
                notes=None,
                cover_letter=None,
                resume_version=None
            )

            return self.database.save_application(application)
        except Exception as error:
            logger.warning("Error updating status for job %s: %s", job_id, error, exc_info=True)
            return False

    def list_jobs(self) -> List[Job]:
        """List all stored jobs.

        Returns:
            The jobs from the database, or ``[]`` on failure.
        """
        if not self.database:
            return []

        try:
            return self.database.get_jobs()
        except Exception as error:
            logger.warning("Error listing jobs: %s", error, exc_info=True)
            return []


class JobHuntAgent:
    """Main agent class for handling job hunting tasks.

    Args:
        database: The database the agent's tools operate on.
    """

    def __init__(self, database: JobHuntDB = None) -> None:
        settings = get_omlx_settings()
        self.client = OpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout=llm.DEFAULT_TIMEOUT_SECONDS,
            max_retries=2,
        )
        self.tool_registry = ToolRegistry(database, agent=self)

    def run_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute a tool with the given arguments.

        Args:
            tool_name: The name of the registered tool to invoke.
            **kwargs: Keyword arguments forwarded to the tool.

        Returns:
            The tool's return value.

        Raises:
            ValueError: When ``tool_name`` is not a registered tool.
        """
        tool = self.tool_registry.get_tool(tool_name)
        if tool:
            return tool(**kwargs)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    def _resolve_model(self, model: Optional[str]) -> str:
        """Resolve the chat model name for a request.

        Precedence: explicit ``model`` -> ``JOBHUNT_CHAT_MODEL`` env var ->
        user config -> builtin default.

        Args:
            model: An explicit model override, or ``None``.

        Returns:
            The resolved model name.
        """
        if model:
            return model
        # Check environment variable first
        env_var = "JOBHUNT_CHAT_MODEL"
        env_val = os.environ.get(env_var)
        if env_val:
            return env_val
        # Then check config
        config = get_user_config()
        if config.model and config.model.chat:
            return config.model.chat
        # Fall back to default
        return get_default_model("chat")

    def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None) -> str:
        """Chat with the agent, returning the plain-text reply content.

        Uses the retrying LLM layer; transient oMLX failures are retried.

        Args:
            messages: The conversation history (role/content dicts).
            model: Optional explicit model override.

        Returns:
            The agent's plain-text reply.
        """
        return llm.complete(
            messages,
            model=self._resolve_model(model),
            temperature=0.1,
        )

    def chat_stream(
        self, messages: List[Dict[str, str]], model: Optional[str] = None
    ) -> Iterator[str]:
        """Chat with the agent, yielding reply text deltas as they stream in.

        Args:
            messages: The conversation history (role/content dicts).
            model: Optional explicit model override.

        Returns:
            An iterator yielding reply text deltas.
        """
        return llm.stream(
            messages,
            model=self._resolve_model(model),
            temperature=0.1,
        )

    def chat_with_agent(
        self, messages: List[Dict[str, str]], model: Optional[str] = None
    ) -> Dict[str, Any]:
        """Chat with the agent using structured responses (strict JSON object).

        Args:
            messages: The conversation history (role/content dicts).
            model: Optional explicit model override.

        Returns:
            The parsed JSON object reply.

        Raises:
            Exception: When the agent returns content that is not valid JSON.
        """
        content = llm.complete(
            messages,
            model=self._resolve_model(model),
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            logger.warning("Agent returned non-JSON to chat_with_agent: %s", content[:200])
            raise Exception(f"Agent returned invalid JSON: {error}") from error
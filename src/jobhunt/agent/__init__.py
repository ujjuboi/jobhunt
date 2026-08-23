"""
Agent module for JobHunt
Handles tool calling and agent loop
"""
import os
from typing import List, Dict, Any, Optional, Iterator
from openai import OpenAI
from ..config import get_omlx_settings, get_user_config
from ..models import Job, FitScore, Profile, Application
from ..sources import get_source_adapter
from ..db import JobHuntDB
from ..embeddings import EmbeddingClient
from ..scoring import ScorePipeline
from .. import llm
from ..llm import get_default_model
import json
import logging

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for all available agent tools"""
    
    def __init__(self, db: JobHuntDB = None, agent=None):
        self.tools = {}
        self.db = db
        self.agent = agent
        self.register_tool("search_jobs", self.search_jobs)
        self.register_tool("get_job_detail", self.get_job_detail)
        self.register_tool("score_fit", self.score_fit)
        self.register_tool("tailor_resume", self.tailor_resume)
        self.register_tool("generate_cover_letter", self.generate_cover_letter)
        self.register_tool("update_status", self.update_status)
        self.register_tool("list_jobs", self.list_jobs)
        
    def register_tool(self, name: str, func):
        """Register a tool function"""
        self.tools[name] = func
        
    def get_tool(self, name: str):
        """Get a tool function by name"""
        return self.tools.get(name)
        
    def list_tools(self) -> List[str]:
        """Get list of all available tools"""
        return list(self.tools.keys())
    
    def _dedupe_jobs(self, jobs: List[Job]) -> List[Job]:
        """Remove in-batch duplicates by job id and (title, company).

        Re-fetched jobs that are already stored in the database are kept so
        repeated browses still list them; save_job upserts by id.
        """
        deduped_jobs = []
        seen_ids = set()
        seen_keys = set()

        for job in jobs:
            job_id = getattr(job, "id", None) or ""
            if job_id and job_id in seen_ids:
                continue
            if job_id:
                seen_ids.add(job_id)

            title = (job.title or "").lower()
            company = (job.company or "").lower()
            key = (title, company) if (title or company) else job_id
            if key and key in seen_keys:
                continue
            if key:
                seen_keys.add(key)
            deduped_jobs.append(job)

        return deduped_jobs
    
    # Tool implementations
    
    def search_jobs(self, query: str, source: str = "", company: str = "", limit: int = 50, raise_errors: bool = False) -> List[Job]:
        """Search for jobs using a query on specified source."""
        if not self.db:
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
            for job in jobs:
                # Set the source on each job (for the UI to display it)
                job.source = source
                self.db.save_job(job)

            return jobs

        except Exception as e:
            logger.warning("Error searching jobs via %s: %s", source, e, exc_info=True)
            if raise_errors:
                raise
            return []

    def get_job_detail(self, job_id: str) -> Optional[Job]:
        """Get detailed information about a specific job"""
        if not self.db:
            return None

        try:
            # Try to get from local database first
            return self.db.get_job(job_id)
        except Exception as e:
            logger.warning("Error getting job detail for %s: %s", job_id, e, exc_info=True)
            return None
        
    def score_fit(self, job_id: str, profile: Profile) -> FitScore:
        """Score job fit against profile using the hybrid embedding + LLM pipeline."""
        def _failed(message: str) -> FitScore:
            return FitScore(
                job_id=job_id,
                score=0.0,
                explanation=message,
                matched_skills=[],
                missing_skills=[],
                suggested_bullets=[],
            )

        if not self.db:
            return _failed("No database available")
        job = self.db.get_job(job_id)
        if not job:
            return _failed(f"Job {job_id} not found")
        try:
            pipeline = ScorePipeline(self.db, EmbeddingClient(), agent=self.agent)
            results = pipeline.score([job], profile, mode="hybrid", top_n=1)
            return results[0] if results else _failed("No score could be computed")
        except Exception as e:
            logger.warning("Fit scoring failed for job %s: %s", job_id, e, exc_info=True)
            return _failed(f"Fit scoring failed: {e}")
        
    def tailor_resume(self, job_id: str, profile: Profile) -> str:
        """Tailor resume for a specific job"""
        job = self.db.get_job(job_id) if self.db else None
        if not job:
            return f"Job {job_id} not found"

        try:
            from ..resume import ResumeManager
            from ..resume.profile_parser import Profile as RProfile

            manager = ResumeManager()

            # Convert models.Profile dict-style experience to resume.Profile ResumeSections
            resume_profile = self._convert_profile(profile)

            tailored = manager.generate_tailored_resume(
                resume_profile, job.description, agent=self.agent,
            )
            artifacts = manager.save_tailored_resume(
                tailored, job.company, job.id,
            )
            return json.dumps({
                "status": "ok",
                "summary": tailored.summary,
                "skills": tailored.updated_skills,
                "artifacts": artifacts,
            }, indent=2)
        except FileNotFoundError as e:
            return f"Resume directory not found: {e}"
        except Exception as e:
            logger.exception("tailor_resume failed")
            return f"Error tailoring resume: {e}"

    def generate_cover_letter(self, job_id: str, profile: Profile) -> str:
        """Generate cover letter for a specific job"""
        job = self.db.get_job(job_id) if self.db else None
        if not job:
            return f"Job {job_id} not found"

        try:
            from ..resume import ResumeManager

            manager = ResumeManager()
            resume_profile = self._convert_profile(profile)

            cover_letter = manager.generate_cover_letter(
                resume_profile, job.description,
                company_name=job.company, agent=self.agent,
            )
            path = manager.save_cover_letter_to_output(
                cover_letter, job.company, job.id,
            )
            return json.dumps({
                "status": "ok",
                "path": path,
                "preview": cover_letter.content[:500],
            }, indent=2)
        except FileNotFoundError as e:
            return f"Resume directory not found: {e}"
        except Exception as e:
            logger.exception("generate_cover_letter failed")
            return f"Error generating cover letter: {e}"

    @staticmethod
    def _convert_profile(profile: Profile):
        """Convert models.Profile (dict-style) to resume.profile_parser.Profile (ResumeSection-style)."""
        from ..resume.profile_parser import Profile as RProfile, ResumeSection

        def _dicts_to_sections(items):
            sections = []
            for item in items:
                if isinstance(item, dict):
                    sections.append(ResumeSection(
                        title=item.get("title", ""),
                        content=item.get("content", ""),
                        bullets=item.get("bullets", []),
                    ))
                elif hasattr(item, "title"):
                    sections.append(item)
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
        """Update job application status"""
        if not self.db:
            return False
            
        try:
            # Get the job to make sure it exists
            job = self.db.get_job(job_id)
            if not job:
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
            
            return self.db.save_application(application)
        except Exception as e:
            logger.warning("Error updating status for job %s: %s", job_id, e, exc_info=True)
            return False

    def list_jobs(self) -> List[Job]:
        """List all jobs"""
        if not self.db:
            return []

        try:
            return self.db.get_jobs()
        except Exception as e:
            logger.warning("Error listing jobs: %s", e, exc_info=True)
            return []


class JobHuntAgent:
    """Main agent class for handling job hunting tasks"""

    def __init__(self, db: JobHuntDB = None):
        settings = get_omlx_settings()
        self.client = OpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout=llm.DEFAULT_TIMEOUT_SECONDS,
            max_retries=2,
        )
        self.tool_registry = ToolRegistry(db, agent=self)

    def run_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute a tool with given arguments"""
        tool = self.tool_registry.get_tool(tool_name)
        if tool:
            return tool(**kwargs)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    def _resolve_model(self, model: Optional[str]) -> str:
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
        """
        return llm.complete(
            messages,
            model=self._resolve_model(model),
            temperature=0.1,
        )

    def chat_stream(self, messages: List[Dict[str, str]], model: Optional[str] = None) -> Iterator[str]:
        """Chat with the agent, yielding reply text deltas as they stream in."""
        return llm.stream(
            messages,
            model=self._resolve_model(model),
            temperature=0.1,
        )

    def chat_with_agent(self, messages: List[Dict[str, str]], model: Optional[str] = None) -> Dict[str, Any]:
        """Chat with the agent using structured responses (strict JSON object)."""
        content = llm.complete(
            messages,
            model=self._resolve_model(model),
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("Agent returned non-JSON to chat_with_agent: %s", content[:200])
            raise Exception(f"Agent returned invalid JSON: {e}") from e
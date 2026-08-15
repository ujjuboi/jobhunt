"""
Agent module for JobHunt
Handles tool calling and agent loop
"""
from typing import List, Dict, Any, Optional
from openai import OpenAI
from ..config import get_omlx_settings
from ..models import Job, FitScore, Profile, Application
from ..sources import get_source_adapter
from ..db import JobHuntDB
import json
import hashlib


class ToolRegistry:
    """Registry for all available agent tools"""
    
    def __init__(self, db: JobHuntDB = None):
        self.tools = {}
        self.db = db
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
        """Remove duplicate jobs based on title and company"""
        if not self.db:
            return jobs
            
        deduped_jobs = []
        seen_hashes = set()
        
        for job in jobs:
            # Create a hash based on title and company (simplified deduplication)
            job_hash = hashlib.md5(f"{job.title}-{job.company}".encode()).hexdigest()
            if job_hash not in seen_hashes:
                seen_hashes.add(job_hash)
                # Also check if job is already in the database
                existing_job = self.db.get_job(job.id)
                if not existing_job:
                    deduped_jobs.append(job)
                    
        return deduped_jobs
    
    # Tool implementations
    
    def search_jobs(self, query: str, source: str = "greenhouse", company: str = "", limit: int = 50) -> List[Job]:
        """Search for jobs using a query on specified source"""
        if not self.db:
            # Debug: return empty list if DB not initialized
            return []
            
        try:
            adapter = get_source_adapter(source)
            if company:
                jobs = adapter.get_jobs(company, limit)
            else:
                jobs = adapter.search_jobs(query, limit)
            
            # Deduplicate jobs
            jobs = self._dedupe_jobs(jobs)
            
            # Save jobs to database
            for job in jobs:
                self.db.save_job(job)
                
            return jobs
            
        except Exception as e:
            print(f"Error searching jobs: {e}")
            return []
        
    def get_job_detail(self, job_id: str) -> Optional[Job]:
        """Get detailed information about a specific job"""
        if not self.db:
            return None
            
        try:
            # Try to get from local database first
            job = self.db.get_job(job_id)
            if job:
                return job
            
            # If not in DB, we would normally fetch from a source, 
            # but for now we'll just return what we have
            return job
            
        except Exception as e:
            print(f"Error getting job detail: {e}")
            return None
        
    def score_fit(self, job_id: str, profile: Profile) -> FitScore:
        """Score job fit against profile"""
        # This will be expanded in Phase 3 with embedding logic
        # For now, return a mock fit score
        return FitScore(
            job_id=job_id,
            score=0.0,
            explanation="Fit scoring not implemented yet",
            matched_skills=[],
            missing_skills=[],
            suggested_bullets=[]
        )
        
    def tailor_resume(self, job_id: str, profile: Profile) -> str:
        """Tailor resume for a specific job"""
        # This will be expanded in Phase 4
        return "Tailored resume content would be generated here"
        
    def generate_cover_letter(self, job_id: str, profile: Profile) -> str:
        """Generate cover letter for a specific job"""
        # This will be expanded in Phase 4
        return "Cover letter content would be generated here"
        
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
            print(f"Error updating status: {e}")
            return False
        
    def list_jobs(self) -> List[Job]:
        """List all jobs"""
        if not self.db:
            return []
            
        try:
            return self.db.get_jobs()
        except Exception as e:
            print(f"Error listing jobs: {e}")
            return []


class JobHuntAgent:
    """Main agent class for handling job hunting tasks"""
    
    def __init__(self, db: JobHuntDB = None):
        settings = get_omlx_settings()
        self.client = OpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key
        )
        self.tool_registry = ToolRegistry(db)
        
    def run_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute a tool with given arguments"""
        tool = self.tool_registry.get_tool(tool_name)
        if tool:
            return tool(**kwargs)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
        
    def run_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute a tool with given arguments"""
        tool = self.tool_registry.get_tool(tool_name)
        if tool:
            return tool(**kwargs)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
            
    def chat(self, messages: List[Dict[str, str]], model: str = "Qwen3-30B-A3B-6bit") -> str:
        """Chat with the agent, returning the plain-text reply content."""
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            raise Exception(f"Failed to communicate with agent: {e}")
            
    def chat_with_agent(self, messages: List[Dict[str, str]], model: str = "Qwen3-30B-A3B-6bit") -> Dict[str, Any]:
        """Chat with the agent using structured responses"""
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            # Handle errors appropriately
            raise Exception(f"Failed to communicate with agent: {e}")
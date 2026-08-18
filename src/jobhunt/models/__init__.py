"""
Pydantic models for JobHunt application
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class Job(BaseModel):
    """A job posting from any source"""
    id: str
    title: str
    company: str
    location: Optional[str] = None
    description: str
    url: Optional[str] = None
    posted_date: Optional[datetime] = None
    salary: Optional[str] = None
    remote: Optional[bool] = None
    tags: List[str] = []
    # Add fields for internal tracking
    source: str  # e.g., 'greenhouse', 'lever', 'ashby'
    # For-fit scoring
    fit_score: Optional[float] = None
    fit_explanation: Optional[str] = None


class Profile(BaseModel):
    """User's resume/profile information"""
    name: str = ""
    email: str = ""
    phone: str = ""
    location: Optional[str] = None
    summary: str = ""
    experience: List[Dict[str, Any]] = []
    education: List[Dict[str, Any]] = []
    skills: List[str] = []
    certifications: List[str] = []
    projects: List[Dict[str, Any]] = []
    # Section for LinkedIn profile if needed
    linkedin_url: Optional[str] = None


class FitScore(BaseModel):
    """Fit score for a job"""
    job_id: str
    score: float  # 0.0 to 1.0
    explanation: str
    matched_skills: List[str] = []
    missing_skills: List[str] = []
    suggested_bullets: List[str] = []


class Application(BaseModel):
    """Application tracking for a job"""
    job_id: str
    status: str  # e.g., 'saved', 'applied', 'interview', 'rejected'
    applied_date: Optional[datetime] = None
    notes: Optional[str] = None
    cover_letter: Optional[str] = None
    resume_version: Optional[str] = None


class Resume(BaseModel):
    """A tailored resume for a specific job"""
    id: str
    job_id: str
    content: str
    path: str  # Path to generated file
    generated_at: datetime
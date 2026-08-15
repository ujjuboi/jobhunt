"""
Database layer for JobHunt
Uses SQLite for storing jobs, applications, and embeddings
"""
import sqlite3
import os
from datetime import datetime
from typing import List, Optional
import numpy as np
from ..models import Job, Application, Profile, Resume


class JobHuntDB:
    """SQLite database handler for JobHunt"""
    
    def __init__(self, db_path: str = "jobhunt.db"):
        self.db_path = db_path
        self.init_database()
        
    def init_database(self):
        """Initialize the database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create jobs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT,
                    description TEXT,
                    url TEXT,
                    posted_date TEXT,
                    salary TEXT,
                    remote BOOLEAN,
                    tags TEXT,
                    source TEXT NOT NULL,
                    fit_score REAL,
                    fit_explanation TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create applications table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS applications (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    applied_date TEXT,
                    notes TEXT,
                    cover_letter TEXT,
                    resume_version TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create embeddings table for caching
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,  -- 'job', 'resume', 'profile'
                    entity_id TEXT NOT NULL,
                    embedding TEXT NOT NULL,  -- JSON string of embedding vector
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(kind, entity_id)
                )
            ''')
            
            # Create profiles table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    location TEXT,
                    summary TEXT,
                    experience TEXT,  -- JSON string
                    education TEXT,   -- JSON string
                    skills TEXT,      -- JSON string
                    linkedin_url TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create resumes table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS resumes (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    content TEXT,
                    path TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
    
    def save_job(self, job: Job) -> bool:
        """Save a job to the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO jobs 
                    (id, title, company, location, description, url, posted_date, salary, remote, tags, source, fit_score, fit_explanation)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    job.id,
                    job.title,
                    job.company,
                    job.location,
                    job.description,
                    job.url,
                    job.posted_date.isoformat() if job.posted_date else None,
                    job.salary,
                    job.remote,
                    ','.join(job.tags) if job.tags else '',
                    job.source,
                    job.fit_score,
                    job.fit_explanation
                ))
                conn.commit()
            return True
        except Exception as e:
            print(f"Error saving job: {e}")
            return False
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM jobs WHERE id = ?', (job_id,))
                row = cursor.fetchone()
                if row:
                    return Job(
                        id=row[0],
                        title=row[1],
                        company=row[2],
                        location=row[3],
                        description=row[4],
                        url=row[5],
                        posted_date=datetime.fromisoformat(row[6]) if row[6] else None,
                        salary=row[7],
                        remote=bool(row[8]) if row[8] is not None else None,
                        tags=row[9].split(',') if row[9] else [],
                        source=row[10],
                        fit_score=row[11],
                        fit_explanation=row[12]
                    )
            return None
        except Exception as e:
            print(f"Error getting job: {e}")
            return None
    
    def get_jobs(self, limit: int = 50, offset: int = 0) -> List[Job]:
        """Get a list of jobs"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM jobs 
                    ORDER BY posted_date DESC, created_at DESC 
                    LIMIT ? OFFSET ?
                ''', (limit, offset))
                rows = cursor.fetchall()
                jobs = []
                for row in rows:
                    jobs.append(Job(
                        id=row[0],
                        title=row[1],
                        company=row[2],
                        location=row[3],
                        description=row[4],
                        url=row[5],
                        posted_date=datetime.fromisoformat(row[6]) if row[6] else None,
                        salary=row[7],
                        remote=bool(row[8]) if row[8] is not None else None,
                        tags=row[9].split(',') if row[9] else [],
                        source=row[10],
                        fit_score=row[11],
                        fit_explanation=row[12]
                    ))
                return jobs
        except Exception as e:
            print(f"Error getting jobs: {e}")
            return []
    
    def save_application(self, application: Application) -> bool:
        """Save an application to the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO applications 
                    (job_id, status, applied_date, notes, cover_letter, resume_version)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    application.job_id,
                    application.status,
                    application.applied_date.isoformat() if application.applied_date else None,
                    application.notes,
                    application.cover_letter,
                    application.resume_version
                ))
                conn.commit()
            return True
        except Exception as e:
            print(f"Error saving application: {e}")
            return False
    
    def get_application(self, job_id: str) -> Optional[Application]:
        """Get an application by job ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM applications WHERE job_id = ?', (job_id,))
                row = cursor.fetchone()
                if row:
                    return Application(
                        job_id=row[0],
                        status=row[1],
                        applied_date=datetime.fromisoformat(row[2]) if row[2] else None,
                        notes=row[3],
                        cover_letter=row[4],
                        resume_version=row[5]
                    )
            return None
        except Exception as e:
            print(f"Error getting application: {e}")
            return None
    
    def save_embedding(self, kind: str, entity_id: str, embedding: List[float]) -> bool:
        """Save an embedding to the cache"""
        try:
            import json
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Convert embedding to JSON string for storage
                embedding_json = json.dumps(embedding)
                cursor.execute('''
                    INSERT OR REPLACE INTO embeddings (kind, entity_id, embedding)
                    VALUES (?, ?, ?)
                ''', (kind, entity_id, embedding_json))
                conn.commit()
            return True
        except Exception as e:
            print(f"Error saving embedding: {e}")
            return False
    
    def get_embedding(self, kind: str, entity_id: str) -> Optional[List[float]]:
        """Get an embedding from the cache"""
        try:
            import json
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT embedding FROM embeddings WHERE kind = ? AND entity_id = ?', (kind, entity_id))
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0])
            return None
        except Exception as e:
            print(f"Error getting embedding: {e}")
            return None
    
    def cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        try:
            # Convert to numpy arrays
            a = np.array(vec_a)
            b = np.array(vec_b)
            
            # Calculate cosine similarity
            dot_product = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            
            if norm_a == 0 or norm_b == 0:
                return 0.0
                
            return dot_product / (norm_a * norm_b)
        except Exception as e:
            print(f"Error calculating cosine similarity: {e}")
            return 0.0
    
    def get_job_embeddings(self) -> List[tuple]:
        """Get all job embeddings for batch processing"""
        try:
            import json
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id, embedding FROM embeddings WHERE kind = "job" AND embedding IS NOT NULL')
                rows = cursor.fetchall()
                # Convert JSON strings back to lists
                return [(row[0], json.loads(row[1])) for row in rows]
        except Exception as e:
            print(f"Error getting job embeddings: {e}")
            return []
    
    def get_profile_embedding(self) -> Optional[List[float]]:
        """Get profile embedding if it exists"""
        try:
            import json
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT embedding FROM embeddings WHERE kind = "profile" AND embedding IS NOT NULL LIMIT 1')
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0])
            return None
        except Exception as e:
            print(f"Error getting profile embedding: {e}")
            return None
    
    def save_profile(self, profile: Profile) -> bool:
        """Save a user profile to the database"""
        try:
            import json
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO profiles 
                    (id, name, email, phone, location, summary, experience, education, skills, linkedin_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    profile.name.lower().replace(' ', '_'),  # Simple ID from name
                    profile.name,
                    profile.email,
                    profile.phone,
                    profile.location,
                    profile.summary,
                    json.dumps(profile.experience) if profile.experience else '',
                    json.dumps(profile.education) if profile.education else '',
                    json.dumps(profile.skills) if profile.skills else '',
                    profile.linkedin_url
                ))
                conn.commit()
            return True
        except Exception as e:
            print(f"Error saving profile: {e}")
            return False
    
    def get_profile(self, profile_id: str = None) -> Optional[Profile]:
        """Get profile from the database"""
        try:
            import json
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if profile_id:
                    cursor.execute('SELECT * FROM profiles WHERE id = ?', (profile_id,))
                else:
                    cursor.execute('SELECT * FROM profiles LIMIT 1')
                row = cursor.fetchone()
                if row:
                    return Profile(
                        name=row[1],
                        email=row[2],
                        phone=row[3],
                        location=row[4],
                        summary=row[5],
                        experience=json.loads(row[6]) if row[6] else [],
                        education=json.loads(row[7]) if row[7] else [],
                        skills=json.loads(row[8]) if row[8] else [],
                        linkedin_url=row[9]
                    )
            return None
        except Exception as e:
            print(f"Error getting profile: {e}")
            return None
    
    def save_resume(self, resume: Resume) -> bool:
        """Save a resume to the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO resumes 
                    (id, job_id, content, path, generated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    resume.id,
                    resume.job_id,
                    resume.content,
                    resume.path,
                    resume.generated_at.isoformat()
                ))
                conn.commit()
            return True
        except Exception as e:
            print(f"Error saving resume: {e}")
            return False
    
    def get_resume(self, resume_id: str) -> Optional[Resume]:
        """Get a resume by ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM resumes WHERE id = ?', (resume_id,))
                row = cursor.fetchone()
                if row:
                    return Resume(
                        id=row[0],
                        job_id=row[1],
                        content=row[2],
                        path=row[3],
                        generated_at=datetime.fromisoformat(row[4])
                    )
            return None
        except Exception as e:
            print(f"Error getting resume: {e}")
            return None
"""
Database layer for JobHunt.

Uses SQLite for storing jobs, applications, profiles, resumes, and cached
embeddings.
"""
import json
import logging
import sqlite3
from datetime import datetime
from typing import List, Optional

import numpy as np

from ..models import Application, Job, Profile, Resume

logger = logging.getLogger(__name__)


class JobHuntDB:
    """SQLite database handler for JobHunt.

    Args:
        database_path: Filesystem path to the SQLite database file
            (default: ``jobhunt.db`` in the current directory).
    """

    def __init__(self, database_path: str = "jobhunt.db"):
        self.database_path = database_path
        self.init_database()

    def init_database(self) -> None:
        """Create the required tables if they do not exist yet."""
        with sqlite3.connect(self.database_path) as connection:
            cursor = connection.cursor()

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

            connection.commit()

    def save_job(self, job: Job) -> bool:
        """Save (upsert) a job to the database.

        Args:
            job: The job to persist.

        Returns:
            True on success, False on failure.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
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
                connection.commit()
            return True
        except Exception as error:
            logger.warning("Error saving job: %s", error)
            return False

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID.

        Args:
            job_id: The id of the job to look up.

        Returns:
            The job, or ``None`` when not found.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
                cursor.execute('SELECT * FROM jobs WHERE id = ?', (job_id,))
                record = cursor.fetchone()
                if record:
                    return Job(
                        id=record[0],
                        title=record[1],
                        company=record[2],
                        location=record[3],
                        description=record[4],
                        url=record[5],
                        posted_date=datetime.fromisoformat(record[6]) if record[6] else None,
                        salary=record[7],
                        remote=bool(record[8]) if record[8] is not None else None,
                        tags=record[9].split(',') if record[9] else [],
                        source=record[10],
                        fit_score=record[11],
                        fit_explanation=record[12]
                    )
            return None
        except Exception as error:
            logger.warning("Error getting job: %s", error)
            return None

    def get_jobs(self, limit: int = 50, offset: int = 0) -> List[Job]:
        """Get a list of jobs, most recently posted first.

        Args:
            limit: Maximum number of jobs to return.
            offset: Number of jobs to skip for pagination.

        Returns:
            A list of job objects.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
                cursor.execute('''
                    SELECT * FROM jobs 
                    ORDER BY posted_date DESC, created_at DESC 
                    LIMIT ? OFFSET ?
                ''', (limit, offset))
                records = cursor.fetchall()
                jobs = []
                for record in records:
                    jobs.append(Job(
                        id=record[0],
                        title=record[1],
                        company=record[2],
                        location=record[3],
                        description=record[4],
                        url=record[5],
                        posted_date=datetime.fromisoformat(record[6]) if record[6] else None,
                        salary=record[7],
                        remote=bool(record[8]) if record[8] is not None else None,
                        tags=record[9].split(',') if record[9] else [],
                        source=record[10],
                        fit_score=record[11],
                        fit_explanation=record[12]
                    ))
                return jobs
        except Exception as error:
            logger.warning("Error getting jobs: %s", error)
            return []

    def save_application(self, application: Application) -> bool:
        """Save (upsert) an application to the database.

        Args:
            application: The application to persist.

        Returns:
            True on success, False on failure.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
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
                connection.commit()
            return True
        except Exception as error:
            logger.warning("Error saving application: %s", error)
            return False

    def get_application(self, job_id: str) -> Optional[Application]:
        """Get an application by job ID.

        Args:
            job_id: The id of the job whose application to look up.

        Returns:
            The application, or ``None`` when not found.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
                cursor.execute('SELECT * FROM applications WHERE job_id = ?', (job_id,))
                record = cursor.fetchone()
                if record:
                    return Application(
                        job_id=record[0],
                        status=record[1],
                        applied_date=datetime.fromisoformat(record[2]) if record[2] else None,
                        notes=record[3],
                        cover_letter=record[4],
                        resume_version=record[5]
                    )
            return None
        except Exception as error:
            logger.warning("Error getting application: %s", error)
            return None

    def save_embedding(self, kind: str, entity_id: str, embedding: List[float]) -> bool:
        """Save an embedding to the cache.

        Args:
            kind: The embedding kind (``job``, ``resume``, or ``profile``).
            entity_id: The id of the entity the embedding belongs to.
            embedding: The float vector to persist as JSON.

        Returns:
            True on success, False on failure.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
                # Convert embedding to JSON string for storage
                embedding_json = json.dumps(embedding)
                cursor.execute('''
                    INSERT OR REPLACE INTO embeddings (kind, entity_id, embedding)
                    VALUES (?, ?, ?)
                ''', (kind, entity_id, embedding_json))
                connection.commit()
            return True
        except Exception as error:
            logger.warning("Error saving embedding: %s", error)
            return False

    def get_embedding(self, kind: str, entity_id: str) -> Optional[List[float]]:
        """Get an embedding from the cache.

        Args:
            kind: The embedding kind (``job``, ``resume``, or ``profile``).
            entity_id: The id of the entity whose embedding to fetch.

        Returns:
            The embedding vector, or ``None`` when not cached.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    'SELECT embedding FROM embeddings WHERE kind = ? AND entity_id = ?',
                    (kind, entity_id),
                )
                record = cursor.fetchone()
                if record:
                    return json.loads(record[0])
            return None
        except Exception as error:
            logger.warning("Error getting embedding: %s", error)
            return None

    def cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Calculate cosine similarity between two vectors.

        Args:
            vec_a: The first vector.
            vec_b: The second vector.

        Returns:
            A similarity in ``[0, 1]`` (0.0 when either vector is zero).
        """
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
        except Exception as error:
            logger.warning("Error calculating cosine similarity: %s", error)
            return 0.0

    def get_job_embeddings(self) -> List[tuple]:
        """Get all job embeddings for batch processing.

        Returns:
            A list of ``(entity_id, vector)`` tuples for cached job
            embeddings.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    'SELECT id, embedding FROM embeddings WHERE kind = "job" AND embedding IS NOT NULL'
                )
                records = cursor.fetchall()
                # Convert JSON strings back to lists
                return [(record[0], json.loads(record[1])) for record in records]
        except Exception as error:
            logger.warning("Error getting job embeddings: %s", error)
            return []

    def get_profile_embedding(self) -> Optional[List[float]]:
        """Get the cached profile embedding if it exists.

        Returns:
            The profile embedding vector, or ``None`` when not cached.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    'SELECT embedding FROM embeddings WHERE kind = "profile" '
                    'AND embedding IS NOT NULL LIMIT 1'
                )
                record = cursor.fetchone()
                if record:
                    return json.loads(record[0])
            return None
        except Exception as error:
            logger.warning("Error getting profile embedding: %s", error)
            return None

    def save_profile(self, profile: Profile) -> bool:
        """Save (upsert) a user profile to the database.

        Args:
            profile: The profile to persist.

        Returns:
            True on success, False on failure.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
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
                connection.commit()
            return True
        except Exception as error:
            logger.warning("Error saving profile: %s", error)
            return False

    def get_profile(self, profile_id: str = None) -> Optional[Profile]:
        """Get a profile from the database.

        Args:
            profile_id: The id of the profile to fetch, or ``None`` to fetch
                the first stored profile.

        Returns:
            The profile, or ``None`` when not found.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
                if profile_id:
                    cursor.execute('SELECT * FROM profiles WHERE id = ?', (profile_id,))
                else:
                    cursor.execute('SELECT * FROM profiles LIMIT 1')
                record = cursor.fetchone()
                if record:
                    return Profile(
                        name=record[1],
                        email=record[2],
                        phone=record[3],
                        location=record[4],
                        summary=record[5],
                        experience=json.loads(record[6]) if record[6] else [],
                        education=json.loads(record[7]) if record[7] else [],
                        skills=json.loads(record[8]) if record[8] else [],
                        linkedin_url=record[9]
                    )
            return None
        except Exception as error:
            logger.warning("Error getting profile: %s", error)
            return None

    def save_resume(self, resume: Resume) -> bool:
        """Save (upsert) a resume to the database.

        Args:
            resume: The resume to persist.

        Returns:
            True on success, False on failure.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
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
                connection.commit()
            return True
        except Exception as error:
            logger.warning("Error saving resume: %s", error)
            return False

    def get_resume(self, resume_id: str) -> Optional[Resume]:
        """Get a resume by ID.

        Args:
            resume_id: The id of the resume to look up.

        Returns:
            The resume, or ``None`` when not found.
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
                cursor.execute('SELECT * FROM resumes WHERE id = ?', (resume_id,))
                record = cursor.fetchone()
                if record:
                    return Resume(
                        id=record[0],
                        job_id=record[1],
                        content=record[2],
                        path=record[3],
                        generated_at=datetime.fromisoformat(record[4])
                    )
            return None
        except Exception as error:
            logger.warning("Error getting resume: %s", error)
            return None

    def count_jobs(self) -> int:
        """Count total jobs in the database.

        Returns:
            The number of stored jobs (0 on failure).
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
                cursor.execute('SELECT COUNT(*) FROM jobs')
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as error:
            logger.warning("Error counting jobs: %s", error)
            return 0

    def count_applications(self) -> int:
        """Count total applications in the database.

        Returns:
            The number of stored applications (0 on failure).
        """
        try:
            with sqlite3.connect(self.database_path) as connection:
                cursor = connection.cursor()
                cursor.execute('SELECT COUNT(*) FROM applications')
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as error:
            logger.warning("Error counting applications: %s", error)
            return 0
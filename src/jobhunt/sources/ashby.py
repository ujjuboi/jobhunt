"""
Ashby job board adapter
"""
import logging
from typing import List, Optional
from ..models import Job
from ..sources import SourceAdapter
import httpx

logger = logging.getLogger(__name__)


class AshbyAdapter(SourceAdapter):
    """Adapter for Ashby job board API"""
    
    def __init__(self, api_key: str = None):
        self.base_url = "https://api.ashbyhq.com/posting-api/job-board"
        self.api_key = api_key
    
    def get_jobs(self, company_slug: str, limit: int = 50) -> List[Job]:
        """Get jobs from an Ashby company board"""
        try:
            url = f"{self.base_url}/{company_slug}"
            
            response = httpx.get(url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            jobs = []
            
            # Ashby returns an object with a 'jobs' array of postings
            for job_data in data.get('jobs', []):
                department = job_data.get('department')
                # Normalize the job data
                job = self.normalize_job({
                    'id': str(job_data.get('id', '')),
                    'title': job_data.get('title', ''),
                    'company': company_slug,
                    'location': job_data.get('location', ''),
                    'description': job_data.get('descriptionPlain', '') or job_data.get('descriptionHtml', ''),
                    'url': job_data.get('applyUrl') or job_data.get('jobUrl'),
                    'posted_date': job_data.get('publishedAt'),
                    'tags': [department] if department else []
                })
                jobs.append(job)
                if len(jobs) >= limit:
                    break
                
            return jobs
            
        except Exception as e:
            logger.warning(f"Error fetching jobs from Ashby: {e}")
            return []
    
    def get_job_detail(self, job_id: str) -> Optional[Job]:
        """Get detailed information about an Ashby job"""
        # No public single-job endpoint for the posting API.
        logger.warning("Ashby job detail endpoint not implemented")
        return None
    
    def search_jobs(self, query: str, limit: int = 50) -> List[Job]:
        """Search for jobs using a query"""
        # Ashby typically requires specifying the company slug
        # We're implementing a simplified version
        return self.get_jobs(query, limit)
"""
Lever job board adapter
"""
import logging
from typing import List, Optional
from ..models import Job
from ..sources import SourceAdapter
import httpx

logger = logging.getLogger(__name__)


class LeverAdapter(SourceAdapter):
    """Adapter for Lever job board API"""
    
    def __init__(self, api_key: str = None):
        self.base_url = "https://api.lever.co/v0/postings"
        self.api_key = api_key
    
    def get_jobs(self, company_slug: str, limit: int = 50) -> List[Job]:
        """Get jobs from a Lever company board"""
        try:
            url = f"{self.base_url}/{company_slug}"
            params = {"mode": "json", "limit": limit}
            
            response = httpx.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            jobs = []
            
            for job_data in data:
                # Normalize the job data
                created_at = job_data.get('createdAt')
                posted_date = created_at // 1000 if created_at else None
                team = job_data.get('categories', {}).get('team')
                job = self.normalize_job({
                    'id': str(job_data.get('id', '')),
                    'title': job_data.get('text', ''),
                    'company': company_slug,
                    'location': job_data.get('location', ''),
                    'description': job_data.get('description', ''),
                    'url': job_data.get('applyUrl', ''),
                    'posted_date': posted_date,
                    'tags': [team] if team else []
                })
                jobs.append(job)
                if len(jobs) >= limit:
                    break
                
            return jobs
            
        except Exception as e:
            logger.warning(f"Error fetching jobs from Lever: {e}")
            return []
    
    def get_job_detail(self, job_id: str) -> Optional[Job]:
        """Get detailed information about a Lever job"""
        # Lever jobs are usually retrieved by company slug; there is no single
        # job-detail endpoint to call directly.
        logger.warning("Lever job detail endpoint not implemented")
        return None
    
    def search_jobs(self, query: str, limit: int = 50) -> List[Job]:
        """Search for jobs using a query"""
        # Lever doesn't support a direct search endpoint
        # We could enhance this with company-specific searches
        return self.get_jobs(query, limit)
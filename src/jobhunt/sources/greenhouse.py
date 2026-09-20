"""
Greenhouse job board adapter
"""
import logging
from typing import List, Optional
from ..models import Job
from ..sources import SourceAdapter
import httpx

logger = logging.getLogger(__name__)


class GreenhouseAdapter(SourceAdapter):
    """Adapter for Greenhouse job board API"""
    
    def __init__(self, api_key: str = None):
        self.base_url = "https://boards-api.greenhouse.io/v1/boards"
        self.api_key = api_key
        self._company_slug: Optional[str] = None
    
    def get_jobs(self, company_slug: str, limit: int = 50, raise_errors: bool = False) -> List[Job]:
        """Get jobs from a Greenhouse company board"""
        try:
            self._company_slug = company_slug
            url = f"{self.base_url}/{company_slug}/jobs"
            params = {"limit": limit}
            
            # Add API key if provided
            if self.api_key:
                params["auth_token"] = self.api_key
                
            response = httpx.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            jobs = []
            
            if 'jobs' in data:
                for job_data in data['jobs']:
                    # Normalize the job data
                    job = self.normalize_job({
                        'id': str(job_data.get('id', '')),
                        'title': job_data.get('title', ''),
                        'company': job_data.get('company', {}).get('name', company_slug),
                        'location': job_data.get('location', {}).get('name'),
                        'description': job_data.get('content', ''),
                        'url': job_data.get('absolute_url'),
                        'posted_date': job_data.get('updated_at'),
                        'tags': [d.get('name') for d in job_data.get('departments', [])]
                    })
                    jobs.append(job)
                    
            return jobs
            
        except Exception as error:
            logger.warning(f"Error fetching jobs from Greenhouse: {error}")
            if raise_errors:
                raise
            return []
    
    def get_job_detail(self, job_id: str) -> Optional[Job]:
        """Get detailed information about a Greenhouse job"""
        try:
            if not self._company_slug:
                return None
            url = f"{self.base_url}/{self._company_slug}/jobs/{job_id}"
            response = httpx.get(url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Normalize the job data
            job = self.normalize_job({
                'id': str(data.get('id', '')),
                'title': data.get('title', ''),
                'company': data.get('company', {}).get('name', self._company_slug),
                'location': data.get('location', {}).get('name', ''),
                'description': data.get('content', ''),
                'url': data.get('absolute_url'),
                'posted_date': data.get('updated_at'),
                'tags': [d.get('name') for d in data.get('departments', [])]
            })
            
            return job
            
        except Exception as error:
            logger.warning(f"Error fetching job detail from Greenhouse: {error}")
            return None
    
    def search_jobs(self, query: str, limit: int = 50, raise_errors: bool = False) -> List[Job]:
        """Search for jobs using a query"""
        # Greenhouse doesn't have a direct search endpoint
        # We could enhance this with company-specific searches
        return self.get_jobs(query, limit, raise_errors=raise_errors)
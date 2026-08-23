"""
Source adapter interface for job boards
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from ..models import Job


class SourceAdapter(ABC):
    """Abstract base class for job board adapters"""
    
    @abstractmethod
    def get_jobs(self, company_slug: str, limit: int = 50, raise_errors: bool = False) -> List[Job]:
        """Get jobs from a specific company"""
        pass
    
    @abstractmethod
    def get_job_detail(self, job_id: str) -> Optional[Job]:
        """Get detailed information about a specific job"""
        pass
    
    @abstractmethod
    def search_jobs(self, query: str, limit: int = 50, raise_errors: bool = False) -> List[Job]:
        """Search for jobs using a query"""
        pass
    
    def normalize_job(self, job_data: dict) -> Job:
        """Normalize job data from different sources into our standard Job model"""
        # Default implementation, can be overridden by specific adapters
        return Job(
            id=job_data.get('id', ''),
            title=job_data.get('title', ''),
            company=job_data.get('company', ''),
            location=job_data.get('location'),
            description=job_data.get('description', ''),
            url=job_data.get('url'),
            posted_date=job_data.get('posted_date'),
            salary=job_data.get('salary'),
            remote=job_data.get('remote'),
            tags=job_data.get('tags', []),
            source=self.__class__.__name__.lower().replace('adapter', ''),
        )


def get_source_adapter(source_type: str, api_key: str = None, **kwargs) -> SourceAdapter:
    """Factory function to get a source adapter instance"""
    if source_type.lower() == 'greenhouse':
        from .greenhouse import GreenhouseAdapter
        return GreenhouseAdapter(api_key)
    elif source_type.lower() == 'lever':
        from .lever import LeverAdapter
        return LeverAdapter(api_key)
    elif source_type.lower() == 'ashby':
        from .ashby import AshbyAdapter
        return AshbyAdapter(api_key)
    elif source_type.lower() == 'linkedin':
        from .linkedin import LinkedInAdapter
        # LinkedIn signs in through the browser; the session is persisted in cache.
        return LinkedInAdapter()
    elif source_type.lower() == 'indeed':
        from .indeed import IndeedAdapter
        # Indeed doesn't require an API key
        return IndeedAdapter()
    else:
        raise ValueError(f"Unknown source type: {source_type}")

"""
Search screen for JobHunt application
"""
import asyncio
import logging
from typing import Optional

from textual.widgets import Static, Input, Button, TextArea
from textual.containers import Container

from .base import BaseScreen
from ...agent import JobHuntAgent
from ...db import JobHuntDB
from ...config.user_config import get_user_config

logger = logging.getLogger(__name__)


class SearchScreen(BaseScreen):
    """Search screen for job searching"""
    
    def __init__(self, db: Optional[JobHuntDB] = None):
        super().__init__(name="search")
        self.db = db
        self.agent: Optional[JobHuntAgent] = None
        
    def _get_content(self):
        return Container(
            Static("Job Search", id="search_title"),
            Static("Enter your search criteria:"),
            Input(placeholder="Job title, keywords, company...", id="search_input"),
            Button("Search", id="search_button"),
            Static("", id="search_results_title"),
            TextArea(id="search_results", read_only=True, show_line_numbers=False),
            id="search_content"
        )
    
    def on_button_pressed(self, event):
        """Handle button presses"""
        super().on_button_pressed(event)
        if event.button.id == "search_button":
            self._perform_search()
    
    def _perform_search(self):
        """Perform the job search"""
        search_input = self.query_one("#search_input", Input)
        query = search_input.value
        if not query:
            return
            
        # Disabling the button while searching
        button = self.query_one("#search_button", Button)
        button.disabled = True
        
        # Run the search in background to prevent UI freezing
        self.run_worker(self._async_perform_search, group="search", exclusive=True)
    
    async def _async_perform_search(self):
        """Asynchronous job search implementation"""
        try:
            # Get search input
            search_input = self.query_one("#search_input", Input)
            query = search_input.value
            
            # Run the agent search tool off the event loop to prevent UI freezing
            jobs = await asyncio.to_thread(self._search, query)
            
            # Format results
            results_text = f"Search results for: {query}\n\n"
            if jobs:
                for i, job in enumerate(jobs[:10]):  # Show top 10 results
                    # Add source tag for jobs
                    source_tag = f" [{job.source}]" if job.source else ""
                    results_text += f"{i+1}. {job.title} at {job.company}{source_tag}\n"
                    results_text += f"   Location: {job.location or 'N/A'}\n"
                    results_text += f"   URL: {job.url or 'N/A'}\n"
                    results_text += f"   Posted: {job.posted_date or 'N/A'}\n\n"
            else:
                results_text += "No jobs found matching your criteria.\n"
                # Add context about companies if no results found
                config = get_user_config()
                if not config.companies_for(config.sources.enabled[0] if config.sources.enabled else "greenhouse"):
                    results_text += "\nConfigure company slugs in Settings to see more results.\n"
            
            # Update UI
            self.call_after_refresh(self._update_results, results_text)
            
        except Exception as e:
            results_text = f"Error searching jobs: {e}\n"
            self.call_after_refresh(self._update_results, results_text)
        finally:
            # Re-enable button
            self.call_after_refresh(self._set_search_button_enabled, True)
    
    def _search(self, query: str):
        """Blocking search helper, run off the event loop."""
        if self.agent is None:
            self.agent = JobHuntAgent(self.db)
            
        # Get user config (imported at module level)
        config = get_user_config()
        
        # If no sources are enabled, return empty list
        if not config.sources.enabled:
            return []
            
        # Iterate through enabled sources
        all_jobs = []
        failed_sources = []
        
        for source in config.sources.enabled:
            try:
                # Use the agent's run_tool to get jobs from each source
                source_jobs = self.agent.run_tool(
                    "search_jobs", 
                    query=query, 
                    source=source, 
                    company="", 
                    limit=20,
                    raise_errors=True
                )
                all_jobs.extend(source_jobs)
            except Exception as e:
                # Log failed source but continue with others
                failed_sources.append(f"{source}: {str(e)}")
                continue
                
        # Deduplicate by (title, company) across all sources
        if all_jobs:
            seen_keys = set()
            deduped_jobs = []
            for job in all_jobs:
                title = job.title or ""
                company = job.company or ""
                if title or company:
                    key = (title.lower(), company.lower())
                else:
                    key = getattr(job, 'id', None)
                if key is not None and key not in seen_keys:
                    seen_keys.add(key)
                    deduped_jobs.append(job)
            all_jobs = deduped_jobs
            
        # If we have failed sources, add them to the result somehow (for display purposes)
        # This could be enhanced to show errors in the UI
        if failed_sources:
            # Use logger instead of print
            logger.warning("Failed sources: %s", failed_sources)
            
        return all_jobs
    
    def _set_search_button_enabled(self, enabled: bool):
        """Enable/disable the search button (callback for the event loop)."""
        self.query_one("#search_button", Button).disabled = not enabled
        
    def _update_results(self, text):
        """Update the results textarea with new content"""
        results_area = self.query_one("#search_results", TextArea)
        results_area.text = text
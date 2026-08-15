"""
Search screen for JobHunt application
"""
import asyncio
from typing import Optional

from textual.widgets import Static, Input, Button, TextArea
from textual.containers import Container

from .base import BaseScreen
from ...agent import JobHuntAgent
from ...db import JobHuntDB


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
                    results_text += f"{i+1}. {job.title} at {job.company}\n"
                    results_text += f"   Location: {job.location or 'N/A'}\n"
                    results_text += f"   URL: {job.url or 'N/A'}\n"
                    results_text += f"   Posted: {job.posted_date or 'N/A'}\n\n"
            else:
                results_text += "No jobs found matching your criteria.\n"
            
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
        return self.agent.run_tool("search_jobs", query=query, source="greenhouse", company="", limit=20)
    
    def _set_search_button_enabled(self, enabled: bool):
        """Enable/disable the search button (callback for the event loop)."""
        self.query_one("#search_button", Button).disabled = not enabled
        
    def _update_results(self, text):
        """Update the results textarea with new content"""
        results_area = self.query_one("#search_results", TextArea)
        results_area.text = text
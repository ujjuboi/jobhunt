"""
Search screen for JobHunt application
"""
from .base import BaseScreen
from textual.widgets import Static, Input, Button, TextArea
from textual.containers import Container, Vertical
from .. import jobhunt_app


class SearchScreen(BaseScreen):
    """Search screen for job searching"""
    
    def __init__(self):
        super().__init__(name="search")
        
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
        # This is a placeholder implementation
        # Will be fleshed out with actual agent integration
        search_input = self.query_one("#search_input", Input)
        query = search_input.value
        if not query:
            return
            
        # Display some mock results for now
        results_text = f"Search results for: {query}\n\nMock results would appear here"
        self.query_one("#search_results", TextArea).text = results_text
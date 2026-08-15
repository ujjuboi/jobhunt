"""
JobHunt - Local AI Job-Search Harness (TUI)
"""

from .app import JobHuntApp
from .db import JobHuntDB

# Global instances
jobhunt_app = None
db = None

def init_app():
    """Initialize the JobHunt application and database"""
    global jobhunt_app, db
    db = JobHuntDB()
    jobhunt_app = JobHuntApp()
    return jobhunt_app

def get_db():
    """Get the database instance"""
    return db

def main():
    """Run the JobHunt TUI application"""
    app = JobHuntApp()
    app.run()

if __name__ == "__main__":
    main()
"""
JobHunt - Local AI Job-Search Harness (TUI).
"""
from .app import JobHuntApp
from .db import JobHuntDB

# Global instances
jobhunt_app = None
_database = JobHuntDB()


def init_app():
    """Initialize the JobHunt application and a fresh database.

    Returns:
        The newly constructed :class:`JobHuntApp` instance.
    """
    global jobhunt_app, _database
    _database = JobHuntDB()
    jobhunt_app = JobHuntApp()
    return jobhunt_app


def get_db():
    """Get the current database instance.

    Returns:
        The shared :class:`JobHuntDB` instance.
    """
    return _database


def main():
    """Run the JobHunt TUI application."""
    app = JobHuntApp()
    app.run()


if __name__ == "__main__":
    main()
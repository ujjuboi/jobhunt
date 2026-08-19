"""
Logging setup for JobHunt.

Configures root logging so the app's module loggers (jobhunt.*) surface
warnings/errors in the TUI console and optionally to a file under ~/.config/
jobhunt/logs/.
"""
import logging
import os
import sys
from pathlib import Path


def setup_logging(level: int = logging.INFO, log_to_file: bool = True) -> None:
    """Configure root logging for JobHunt. Safe to call multiple times."""
    root = logging.getLogger()
    if getattr(root, "_jobhunt_configured", False):
        return

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    if log_to_file:
        log_dir = Path.home() / ".config" / "jobhunt" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_dir / "jobhunt.log")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            pass

    root.setLevel(level)

    env_level = os.environ.get("JOBHUNT_LOG_LEVEL")
    if env_level:
        root.setLevel(getattr(logging, env_level.upper(), level))

    root._jobhunt_configured = True
    logging.getLogger("jobhunt").info("JobHunt logging initialized")

"""
Tests for CLI module.
"""
import os
import sys
from pathlib import Path

# Add src to the path to import jobhunt modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jobhunt.cli import PROJECT_ROOT


def test_project_root_resolution():
    """Test that PROJECT_ROOT resolves to the correct directory."""
    # The cli.py file should be at src/jobhunt/cli.py
    # The project root should be at the parent of src
    assert PROJECT_ROOT.exists(), "PROJECT_ROOT should exist"
    
    # It should contain the smoke.py file
    smoke_path = PROJECT_ROOT / "smoke.py"
    assert smoke_path.exists(), "PROJECT_ROOT should contain smoke.py"
    
    # The project root should be at the directory containing src
    assert (PROJECT_ROOT / "src").exists(), "PROJECT_ROOT should contain a src directory"
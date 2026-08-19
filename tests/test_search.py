"""
Test cases for the search screen functionality.
"""
import pytest
from unittest.mock import Mock, patch

from jobhunt.app.screens.search import SearchScreen


def test_search_with_no_enabled_sources():
    """Test search when no sources are enabled."""
    # Mock the get_user_config function to return a config with no enabled sources
    mock_config = Mock()
    mock_config.sources.enabled = []
    
    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        jobs = screen._search("test query")
        assert jobs == []


def test_search_single_source():
    """Test search with a single enabled source."""
    # Mock the get_user_config function to return a config with one enabled source
    mock_config = Mock()
    mock_config.sources.enabled = ["greenhouse"]
    
    # Mock agent and its run_tool method
    mock_agent = Mock()
    mock_job = Mock()
    mock_job.title = "Software Engineer"
    mock_job.company = "Test Corp"
    mock_agent.run_tool.return_value = [mock_job]
    
    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent
        
        jobs = screen._search("test query")
        
        # Verify that run_tool was called correctly
        mock_agent.run_tool.assert_called_once_with(
            "search_jobs", 
            query="test query", 
            source="greenhouse", 
            company="", 
            limit=20,
            raise_errors=True
        )
        assert len(jobs) == 1


def test_search_multiple_sources():
    """Test search with multiple enabled sources."""
    # Mock the get_user_config function to return a config with multiple enabled sources
    mock_config = Mock()
    mock_config.sources.enabled = ["greenhouse", "lever"]
    
    # Mock agent and its run_tool method to return different jobs for each source
    mock_agent = Mock()
    mock_job1 = Mock()
    mock_job1.title = "Software Engineer"
    mock_job1.company = "Test Corp"
    mock_job2 = Mock()
    mock_job2.title = "Frontend Developer"
    mock_job2.company = "Another Corp"
    
    # Mock return values for both calls
    mock_agent.run_tool.side_effect = [[mock_job1], [mock_job2]]
    
    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent
        
        jobs = screen._search("test query")
        
        # Verify that run_tool was called for both sources
        assert mock_agent.run_tool.call_count == 2
        mock_agent.run_tool.assert_any_call(
            "search_jobs", 
            query="test query", 
            source="greenhouse", 
            company="", 
            limit=20,
            raise_errors=True
        )
        mock_agent.run_tool.assert_any_call(
            "search_jobs", 
            query="test query", 
            source="lever", 
            company="", 
            limit=20,
            raise_errors=True
        )
        assert len(jobs) == 2


def test_search_with_source_error():
    """Test search when one source fails."""
    # Mock the get_user_config function to return a config with multiple enabled sources
    mock_config = Mock()
    mock_config.sources.enabled = ["greenhouse", "lever"]
    
    # Mock agent that raises exception for one source
    mock_agent = Mock()
    mock_job = Mock()
    mock_job.title = "Software Engineer"
    mock_job.company = "Test Corp"
    mock_agent.run_tool.side_effect = [[mock_job], Exception("Source failed")]
    
    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent
        
        jobs = screen._search("test query")
        
        # Should return results from successful source
        assert len(jobs) == 1


def test_search_dedup_empty_title_falls_back_to_id():
    """Test that jobs with empty titles are deduplicated by job.id."""
    mock_config = Mock()
    mock_config.sources.enabled = ["greenhouse", "lever"]
    
    mock_agent = Mock()
    # Two jobs with empty title/company but different IDs
    mock_job1 = Mock()
    mock_job1.title = ""
    mock_job1.company = ""
    mock_job1.id = "job-1"
    mock_job2 = Mock()
    mock_job2.title = ""
    mock_job2.company = ""
    mock_job2.id = "job-2"
    # A duplicate with same ID as job1
    mock_job3 = Mock()
    mock_job3.title = ""
    mock_job3.company = ""
    mock_job3.id = "job-1"
    
    mock_agent.run_tool.side_effect = [[mock_job1, mock_job3], [mock_job2]]
    
    with patch('jobhunt.app.screens.search.get_user_config', return_value=mock_config):
        screen = SearchScreen()
        screen.agent = mock_agent
        
        jobs = screen._search("test query")
        
        # job-1 and job-2 should be kept, job-3 (duplicate of job-1) dropped
        assert len(jobs) == 2
        ids = [j.id for j in jobs]
        assert "job-1" in ids
        assert "job-2" in ids
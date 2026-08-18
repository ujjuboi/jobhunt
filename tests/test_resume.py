"""
Tests for the resume module functionality
"""
import pytest
from jobhunt.resume import ResumeManager
from jobhunt.resume.profile_parser import Profile, DocxParser
from jobhunt.resume.tailor import ResumeTailor, TailoredResume
from jobhunt.resume.cover_letter import CoverLetterGenerator, CoverLetter
from jobhunt.resume.pdf_converter import convert_docx_to_pdf, is_libreoffice_available


def test_resume_module_imports():
    """Test that all resume modules can be imported successfully"""
    # These should not raise ImportError
    assert ResumeManager is not None
    assert Profile is not None
    assert DocxParser is not None
    assert ResumeTailor is not None
    assert TailoredResume is not None
    assert CoverLetterGenerator is not None
    assert CoverLetter is not None
    assert convert_docx_to_pdf is not None
    assert is_libreoffice_available is not None


def test_resume_manager_instantiation():
    """Test that ResumeManager can be instantiated"""
    # This should work without raising an exception
    manager = ResumeManager()
    assert manager is not None


def test_resume_implementation_complete():
    """Test that all core resume components are present"""
    # Check basic functionality
    assert hasattr(ResumeManager, '__init__')
    assert hasattr(ResumeManager, 'list_available_resumes')
    assert hasattr(ResumeManager, 'load_profile_from_docx')
    assert hasattr(ResumeManager, 'generate_tailored_resume')
    assert hasattr(ResumeManager, 'create_tailored_docx')
    assert hasattr(ResumeManager, 'generate_pdf')
    assert hasattr(ResumeManager, 'generate_cover_letter')
    assert hasattr(ResumeManager, 'save_cover_letter')
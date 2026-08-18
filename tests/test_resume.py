"""
Tests for the resume module functionality
"""
import pytest
from jobhunt.resume import ResumeManager, PROJECT_ROOT
from jobhunt.resume.profile_parser import Profile, DocxParser, ResumeSection
from jobhunt.resume.tailor import ResumeTailor, TailoredResume
from jobhunt.resume.cover_letter import CoverLetterGenerator, CoverLetter
from jobhunt.resume.pdf_converter import convert_docx_to_pdf, is_libreoffice_available


def test_resume_module_imports():
    assert ResumeManager is not None
    assert Profile is not None
    assert DocxParser is not None
    assert ResumeTailor is not None
    assert TailoredResume is not None
    assert CoverLetterGenerator is not None
    assert CoverLetter is not None
    assert convert_docx_to_pdf is not None
    assert is_libreoffice_available is not None


def test_resume_manager_missing_dir(tmp_path):
    """ResumeManager raises FileNotFoundError when the base resume dir is absent."""
    with pytest.raises(FileNotFoundError):
        ResumeManager(base_resume_dir=str(tmp_path / "does-not-exist"))


def test_resume_manager_uses_real_resumes_dir():
    """ResumeManager resolves ../Resumes/ relative to the project root."""
    manager = ResumeManager()
    assert manager.base_resume_dir == (PROJECT_ROOT / ".." / "Resumes").resolve()


def test_resume_manager_api_surface():
    assert hasattr(ResumeManager, 'list_available_resumes')
    assert hasattr(ResumeManager, 'load_profile_from_docx')
    assert hasattr(ResumeManager, 'generate_tailored_resume')
    assert hasattr(ResumeManager, 'create_tailored_docx_from_template')
    assert hasattr(ResumeManager, 'generate_pdf')
    assert hasattr(ResumeManager, 'generate_cover_letter')
    assert hasattr(ResumeManager, 'save_cover_letter')
    assert hasattr(ResumeManager, 'get_output_dir')
    assert hasattr(ResumeManager, 'save_tailored_resume')
    assert hasattr(ResumeManager, 'save_cover_letter_to_output')


def test_heuristic_tailor():
    """ResumeTailor works without an agent (heuristic fallback)."""
    profile = Profile(
        name="Test User",
        email="test@example.com",
        phone="555-1234",
        summary="Python developer with 5 years experience.",
        skills=["Python", "FastAPI", "PostgreSQL"],
        experience=[
            ResumeSection(title="Acme Corp", content="Built stuff", bullets=[
                "Developed REST APIs using Python and FastAPI",
                "Managed PostgreSQL databases",
            ])
        ],
        education=[
            ResumeSection(title="BS Computer Science", content="University", bullets=[
                "Graduated with honors"
            ])
        ],
    )
    jd = "We need a Python developer experienced with FastAPI, Docker, and AWS."

    tailor = ResumeTailor(agent=None)
    result = tailor.tailor_resume(profile, jd)

    assert isinstance(result, TailoredResume)
    assert result.summary == profile.summary
    # Heuristic should keep original skills + add new ones from JD
    assert "Python" in result.updated_skills
    assert "FastAPI" in result.updated_skills
    assert len(result.tailored_sections["experience"]) > 0


def test_template_cover_letter():
    """CoverLetterGenerator works without an agent (template fallback)."""
    profile = Profile(
        name="Test User",
        email="test@example.com",
        phone="555-1234",
        summary="Developer",
        skills=["Python"],
    )
    jd = "Looking for a Python developer with experience in web development and APIs."

    gen = CoverLetterGenerator(agent=None)
    result = gen.generate_cover_letter(profile, jd, company_name="Acme Corp")

    assert isinstance(result, CoverLetter)
    assert "Acme Corp" in result.content
    assert "Test User" in result.content
    assert result.company_name == "Acme Corp"


def test_output_dir_creation(tmp_path):
    """get_output_dir creates the correct directory structure."""
    manager = ResumeManager.__new__(ResumeManager)
    manager.outputs_dir = tmp_path / "outputs"

    out = manager.get_output_dir("Acme Corp", "senior-dev-123")
    assert out.exists()
    assert out == tmp_path / "outputs" / "acme_corp" / "senior-dev-123"

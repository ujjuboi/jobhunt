"""
Main resume module for JobHunt application
"""
from pathlib import Path
from typing import Optional, List
from .profile_parser import Profile, parse_profile_from_docx, load_profile_from_cache, save_profile_to_cache
from .tailor import ResumeTailor, create_tailored_docx, TailoredResume
from .cover_letter import CoverLetterGenerator, CoverLetter
from .pdf_converter import convert_docx_to_pdf, is_libreoffice_available


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ResumeManager:
    """Main class for managing resumes in JobHunt"""

    def __init__(
        self,
        base_resume_dir: str = "../Resumes/",
        cache_dir: str = "cache/resume",
        outputs_dir: str = "outputs",
    ):
        self.base_resume_dir = (PROJECT_ROOT / base_resume_dir).resolve()
        self.cache_dir = (PROJECT_ROOT / cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir = (PROJECT_ROOT / outputs_dir).resolve()

        if not self.base_resume_dir.exists():
            raise FileNotFoundError(
                f"Base resume directory not found: {self.base_resume_dir}\n"
                f"Create it and place your DOCX resume(s) inside."
            )

    # ------------------------------------------------------------------
    # Listing / loading
    # ------------------------------------------------------------------

    def list_available_resumes(self) -> List[str]:
        if not self.base_resume_dir.exists():
            return []
        return [
            f.name
            for f in self.base_resume_dir.iterdir()
            if f.is_file() and f.suffix.lower() == ".docx"
        ]

    def load_profile_from_docx(self, docx_filename: str) -> Profile:
        docx_path = self.base_resume_dir / docx_filename
        cache_path = self.cache_dir / f"{docx_filename}.json"
        profile = load_profile_from_cache(str(cache_path))
        if profile is None:
            profile = parse_profile_from_docx(str(docx_path))
            save_profile_to_cache(profile, str(cache_path))
        return profile

    # ------------------------------------------------------------------
    # Tailoring
    # ------------------------------------------------------------------

    def generate_tailored_resume(
        self,
        profile: Profile,
        job_description: str,
        agent=None,
    ) -> TailoredResume:
        tailor = ResumeTailor(agent=agent)
        return tailor.tailor_resume(profile, job_description)

    def create_tailored_docx_from_template(
        self,
        template_path: str,
        tailored_resume: TailoredResume,
        output_path: str,
    ) -> bool:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            create_tailored_docx(template_path, tailored_resume, output_path)
            return True
        except Exception as e:
            print(f"Error creating tailored DOCX: {e}")
            return False

    # ------------------------------------------------------------------
    # PDF
    # ------------------------------------------------------------------

    def generate_pdf(self, docx_path: str, pdf_path: str) -> bool:
        if not is_libreoffice_available():
            raise RuntimeError(
                "LibreOffice is required for PDF generation. "
                "Install with: brew install libreoffice"
            )
        return convert_docx_to_pdf(docx_path, pdf_path)

    # ------------------------------------------------------------------
    # Cover letters
    # ------------------------------------------------------------------

    def generate_cover_letter(
        self,
        profile: Profile,
        job_description: str,
        company_name: Optional[str] = None,
        recipient_name: Optional[str] = None,
        agent=None,
    ) -> CoverLetter:
        generator = CoverLetterGenerator(agent=agent)
        return generator.generate_cover_letter(
            profile, job_description, company_name, recipient_name
        )

    def save_cover_letter(self, cover_letter: CoverLetter, output_path: str):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(cover_letter.content)

    # ------------------------------------------------------------------
    # Artifact output paths
    # ------------------------------------------------------------------

    def get_output_dir(self, company: str, job_slug: str) -> Path:
        """Return (and create) the output directory for a company/job pair."""
        safe_company = company.replace("/", "-").replace(" ", "_").lower()
        safe_job = job_slug.replace("/", "-").replace(" ", "_").lower()
        out = self.outputs_dir / safe_company / safe_job
        out.mkdir(parents=True, exist_ok=True)
        return out

    def save_tailored_resume(
        self,
        tailored: TailoredResume,
        company: str,
        job_slug: str,
        template_path: Optional[str] = None,
    ) -> dict:
        """Save tailored resume DOCX + optional PDF. Returns artifact paths."""
        out = self.get_output_dir(company, job_slug)
        docx_path = str(out / "resume.docx")
        pdf_path = str(out / "resume.pdf")

        tpl = template_path or str(self.base_resume_dir / next(iter(self.list_available_resumes())))
        self.create_tailored_docx_from_template(tpl, tailored, docx_path)

        pdf_ok = False
        if is_libreoffice_available():
            try:
                pdf_ok = self.generate_pdf(docx_path, pdf_path)
            except Exception:
                pdf_ok = False

        return {"docx": docx_path, "pdf": pdf_path if pdf_ok else None}

    def save_cover_letter_to_output(
        self,
        cover_letter: CoverLetter,
        company: str,
        job_slug: str,
    ) -> str:
        out = self.get_output_dir(company, job_slug)
        path = str(out / "cover_letter.txt")
        self.save_cover_letter(cover_letter, path)
        return path

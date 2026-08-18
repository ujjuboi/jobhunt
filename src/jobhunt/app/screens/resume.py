"""
Resume screen for JobHunt application
"""
from .base import BaseScreen
from textual.widgets import Static, Button, TextArea, Select
from textual.containers import Container
from jobhunt.resume import ResumeManager
from jobhunt.agent import JobHuntAgent
import logging

logger = logging.getLogger(__name__)


class ResumeScreen(BaseScreen):
    """Resume screen for resume management"""

    def __init__(self, db=None):
        super().__init__(name="resume")
        self.db = db
        self.resume_manager = None
        self._agent = None
        self._selected_resume = None
        self._selected_job_id = None
        self._selected_job_description = None
        self._selected_company = None

    @property
    def agent(self):
        if self._agent is None:
            try:
                self._agent = JobHuntAgent(db=self.db)
            except Exception:
                logger.warning("Could not create agent (oMLX may be unavailable)")
        return self._agent

    def _get_content(self):
        return Container(
            Static("Resume Management", id="resume_title"),
            Static("Select a resume file:", id="resume_select_label"),
            Select(
                options=[],
                id="resume_select",
            ),
            Static("", id="resume_status"),
            TextArea(id="resume_preview", read_only=True, show_line_numbers=False),
            Button("Generate Tailored Resume", id="generate_tailored_btn", disabled=True),
            Button("Generate Cover Letter", id="generate_cover_letter_btn", disabled=True),
            Button("Save to Outputs", id="save_outputs_btn", disabled=True),
            id="resume_content",
        )

    def on_mount(self):
        try:
            self.resume_manager = ResumeManager()
            resumes = self.resume_manager.list_available_resumes()
            select = self.query_one("#resume_select", Select)
            select.set_options([(name, name) for name in resumes])
        except FileNotFoundError as e:
            self.query_one("#resume_status").update(f"⚠ {e}")
        except Exception as e:
            logger.exception("ResumeScreen on_mount failed")
            self.query_one("#resume_status").update(f"Error: {e}")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self._selected_resume = event.value
        self._update_resume_preview(event.value)

    def _update_resume_preview(self, filename: str):
        try:
            profile = self.resume_manager.load_profile_from_docx(filename)
            lines = [
                f"Name: {profile.name}",
                f"Email: {profile.email}",
                f"Phone: {profile.phone}",
                "",
                f"Summary: {profile.summary}",
                "",
                "Skills:",
            ]
            for skill in profile.skills:
                lines.append(f"  • {skill}")
            lines.append("")
            lines.append("Experience:")
            for exp in profile.experience:
                lines.append(f"  {exp.title}:")
                for bullet in exp.bullets:
                    lines.append(f"    • {bullet}")

            self.query_one("#resume_preview", TextArea).text = "\n".join(lines)
            self.query_one("#generate_tailored_btn", Button).disabled = False
            self.query_one("#generate_cover_letter_btn", Button).disabled = False
        except Exception as e:
            logger.exception("Failed to load resume preview")
            self.query_one("#resume_status").update(f"Error loading resume: {e}")
            self.query_one("#resume_preview", TextArea).text = ""
            self.query_one("#generate_tailored_btn", Button).disabled = True
            self.query_one("#generate_cover_letter_btn", Button).disabled = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "generate_tailored_btn":
            self._generate_tailored_resume()
        elif event.button.id == "generate_cover_letter_btn":
            self._generate_cover_letter()
        elif event.button.id == "save_outputs_btn":
            self._save_outputs()

    def _generate_tailored_resume(self):
        if not self._selected_resume:
            self.query_one("#resume_status").update("Select a resume first")
            return
        if not self._selected_job_description:
            self.query_one("#resume_status").update(
                "Select a job from the Jobs screen first"
            )
            return

        self.query_one("#resume_status").update("Generating tailored resume...")
        try:
            profile = self.resume_manager.load_profile_from_docx(self._selected_resume)
            tailored = self.resume_manager.generate_tailored_resume(
                profile, self._selected_job_description, agent=self.agent,
            )

            lines = [f"Summary: {tailored.summary}", "", "Skills:"]
            for skill in tailored.updated_skills:
                lines.append(f"  • {skill}")
            lines.append("")
            lines.append("Tailored Experience:")
            for bullet in tailored.tailored_sections.get("experience", []):
                lines.append(f"  • {bullet}")

            self.query_one("#resume_preview", TextArea).text = "\n".join(lines)
            self.query_one("#resume_status").update("✓ Tailored resume generated")
            self.query_one("#save_outputs_btn", Button).disabled = False
        except Exception as e:
            logger.exception("Tailored resume generation failed")
            self.query_one("#resume_status").update(f"Error: {e}")

    def _generate_cover_letter(self):
        if not self._selected_resume:
            self.query_one("#resume_status").update("Select a resume first")
            return
        if not self._selected_job_description:
            self.query_one("#resume_status").update(
                "Select a job from the Jobs screen first"
            )
            return

        self.query_one("#resume_status").update("Generating cover letter...")
        try:
            profile = self.resume_manager.load_profile_from_docx(self._selected_resume)
            cover_letter = self.resume_manager.generate_cover_letter(
                profile, self._selected_job_description,
                company_name=self._selected_company, agent=self.agent,
            )

            self.query_one("#resume_preview", TextArea).text = cover_letter.content
            self.query_one("#resume_status").update("✓ Cover letter generated")
            self.query_one("#save_outputs_btn", Button).disabled = False
        except Exception as e:
            logger.exception("Cover letter generation failed")
            self.query_one("#resume_status").update(f"Error: {e}")

    def _save_outputs(self):
        self.query_one("#resume_status").update("Outputs feature coming soon")

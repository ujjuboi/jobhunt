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
        self._last_tailored = None
        self._last_cover_letter = None

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
            
            # Auto-save profile to database for Fit scoring
            if self.db is not None:
                try:
                    db_profile = self.resume_manager.to_db_profile(profile)
                    self.db.save_profile(db_profile)
                    self.query_one("#resume_status").update("✓ Profile synced for Fit scoring")
                except Exception as save_error:
                    logger.warning(f"Failed to save profile to database: {save_error}")
        except Exception as e:
            logger.exception("Failed to load resume preview")
            self.query_one("#resume_status").update(f"Error loading resume: {e}")
            self.query_one("#resume_preview", TextArea).text = ""
            self.query_one("#generate_tailored_btn", Button).disabled = True
            self.query_one("#generate_cover_letter_btn", Button).disabled = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        super().on_button_pressed(event)
        if event.button.id == "generate_tailored_btn":
            self._generate_tailored_resume()
        elif event.button.id == "generate_cover_letter_btn":
            self._generate_cover_letter()
        elif event.button.id == "save_outputs_btn":
            self._save_outputs()

    def _resolve_selected_job(self, job_id_override: str = None) -> tuple:
        """Helper function to resolve job details from selected job ID or override.
        
        Returns:
            tuple: (job, job_id, company) or (None, None, None) if not found
        """
        if job_id_override is not None:
            job_id = job_id_override
        elif self.app.selected_job_id is not None:
            job_id = self.app.selected_job_id
        else:
            return None, None, None

        # Get job from database
        if self.db is not None:
            job = self.db.get_job(job_id)
            if job:
                return job, job.id, job.company
            else:
                return None, None, None
        else:
            return None, None, None 

    def _generate_tailored_resume(self):
        if not self._selected_resume:
            self.query_one("#resume_status").update("Select a resume first")
            return
            
        # Check if a job is selected
        if self.app.selected_job_id is None:
            self.query_one("#resume_status").update(
                "Select a job row in the Jobs screen first"
            )
            return

        # Resolve job details from selected job ID
        job, job_id, company = self._resolve_selected_job()
        if job is None:
            self.query_one("#resume_status").update("Selected job not found in database")
            return

        self._selected_job_description = job.description
        self._selected_company = company
        self._selected_job_id = job_id

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
            self._last_tailored = tailored
            # Capture the job info when generation succeeds
            self._last_tailored_job_id = self._selected_job_id
            self._last_tailored_company = self._selected_company
            self.query_one("#save_outputs_btn", Button).disabled = False
        except Exception as e:
            logger.exception("Tailored resume generation failed")
            self.query_one("#resume_status").update(f"Error: {e}")

    def _generate_cover_letter(self):
        if not self._selected_resume:
            self.query_one("#resume_status").update("Select a resume first")
            return
            
        # Check if a job is selected
        if self.app.selected_job_id is None:
            self.query_one("#resume_status").update(
                "Select a job row in the Jobs screen first"
            )
            return

        # Resolve job details from selected job ID
        job, job_id, company = self._resolve_selected_job()
        if job is None:
            self.query_one("#resume_status").update("Selected job not found in database")
            return

        self._selected_job_description = job.description
        self._selected_company = company
        self._selected_job_id = job_id

        self.query_one("#resume_status").update("Generating cover letter...")
        try:
            profile = self.resume_manager.load_profile_from_docx(self._selected_resume)
            cover_letter = self.resume_manager.generate_cover_letter(
                profile, self._selected_job_description,
                company_name=self._selected_company, agent=self.agent,
            )

            self.query_one("#resume_preview", TextArea).text = cover_letter.content
            self.query_one("#resume_status").update("✓ Cover letter generated")
            self._last_cover_letter = cover_letter
            # Capture the job info when generation succeeds
            self._last_cover_letter_job_id = self._selected_job_id
            self._last_cover_letter_company = self._selected_company
            self.query_one("#save_outputs_btn", Button).disabled = False
        except Exception as e:
            logger.exception("Cover letter generation failed")
            self.query_one("#resume_status").update(f"Error: {e}")

    def _save_outputs(self):
        # Check if generation happened and job is selected
        if self._last_tailored is None and self._last_cover_letter is None:
            self.query_one("#resume_status").update("No generated output to save")
            return
            
        # Use the captured job info from generation time instead of current selection
        job_id = None
        company = None
        if self._last_tailored is not None:
            job_id = self._last_tailored_job_id
            company = self._last_tailored_company
        elif self._last_cover_letter is not None:
            job_id = self._last_cover_letter_job_id
            company = self._last_cover_letter_company
            
        if job_id is None or company is None:
            # Snapshots should always be set when generation succeeds.
            # If we reach here, something went wrong — warn rather than
            # silently falling back to the current selection.
            self.query_one("#resume_status").update(
                "Warning: Could not determine which job to save for. "
                "Please regenerate and save immediately."
            )
            return
            
        # Save tailored resume if available
        saved_paths = []
        if self._last_tailored is not None:
            try:
                paths = self.resume_manager.save_tailored_resume(
                    self._last_tailored, company, job_id
                )
                if paths["docx"]:
                    saved_paths.append(f"DOCX: {paths['docx']}")
                if paths["pdf"]:
                    saved_paths.append(f"PDF: {paths['pdf']}")
            except Exception as e:
                self.query_one("#resume_status").update(f"Error saving resume: {e}")
                return
                
        # Save cover letter if available
        if self._last_cover_letter is not None:
            try:
                path = self.resume_manager.save_cover_letter_to_output(
                    self._last_cover_letter, company, job_id
                )
                saved_paths.append(f"Cover letter: {path}")
            except Exception as e:
                self.query_one("#resume_status").update(f"Error saving cover letter: {e}")
                return
        
        # Report saved paths in status widget
        if saved_paths:
            status_msg = "✓ Saved: " + ", ".join(saved_paths)
            self.query_one("#resume_status").update(status_msg)
        else:
            self.query_one("#resume_status").update("No files saved")

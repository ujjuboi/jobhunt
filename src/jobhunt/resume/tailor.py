"""
Resume tailoring functionality — LLM-powered via oMLX
"""
from typing import List, Dict, Optional
from pydantic import BaseModel
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import json
import logging
from pathlib import Path

from .profile_parser import Profile

logger = logging.getLogger(__name__)

TAILOR_SYSTEM_PROMPT = """\
You are an expert ATS-optimized resume writer. Given a candidate's profile and a \
job description, produce a tailored resume.

Rules:
- Keep all facts truthful; do NOT fabricate experience.
- Reorder and rewrite bullets to emphasize skills/experience relevant to the JD.
- Use strong action verbs and quantify achievements where possible.
- Inject ATS keywords from the JD naturally.
- Return ONLY valid JSON matching the schema below.

Output schema:
{
  "summary": "<2-3 sentence professional summary tailored to the JD>",
  "skills": ["skill1", "skill2", ...],
  "experience_bullets": ["bullet1", "bullet2", ...],
  "education_bullets": ["bullet1", ...]
}
"""

TAILOR_USER_TEMPLATE = """\
## Candidate Profile

**Name:** {name}
**Summary:** {summary}
**Skills:** {skills}
**Experience:**
{experience}
**Education:**
{education}

## Job Description

{job_description}

Return the tailored resume as JSON only — no markdown fences, no commentary.
"""


class TailoredResume(BaseModel):
    """A resume tailored to a specific job description."""

    original_profile: Profile
    job_description: str
    tailored_sections: Dict[str, List[str]]
    summary: str
    updated_skills: List[str]


def _format_experience(profile: Profile) -> str:
    """Render the experience sections for an LLM prompt.

    Args:
        profile: The profile whose experience to format.

    Returns:
        A markdown-ish, newline-joined string of experience bullets.
    """
    lines = []
    for section in profile.experience:
        lines.append(f"### {section.title}")
        for bullet in section.bullets:
            lines.append(f"- {bullet}")
    return "\n".join(lines) if lines else "(none)"


def _format_education(profile: Profile) -> str:
    """Render the education sections for an LLM prompt.

    Args:
        profile: The profile whose education to format.

    Returns:
        A markdown-ish, newline-joined string of education bullets.
    """
    lines = []
    for section in profile.education:
        lines.append(f"### {section.title}")
        for bullet in section.bullets:
            lines.append(f"- {bullet}")
    return "\n".join(lines) if lines else "(none)"


class ResumeTailor:
    """Tailors a profile to a job description, LLM-first with heuristic fallback.

    Args:
        agent: Optional agent whose client is used for the LLM path.
        model: The oMLX model name used for tailoring.
    """

    def __init__(self, agent=None, model: str = "Qwen3-30B-A3B-6bit"):
        self.agent = agent
        self.model = model

    def tailor_resume(self, profile: Profile, job_description: str) -> TailoredResume:
        """Tailor a profile against a job description.

        Args:
            profile: The profile to tailor.
            job_description: The job posting text to tailor against.

        Returns:
            The tailored :class:`TailoredResume`.
        """
        if self.agent is not None:
            try:
                return self._llm_tailor(profile, job_description)
            except Exception:
                logger.exception("LLM tailoring failed, falling back to heuristic")
        return self._heuristic_tailor(profile, job_description)

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------

    def _llm_tailor(self, profile: Profile, job_description: str) -> TailoredResume:
        """Run the LLM tailoring path via the agent's OpenAI-compatible client.

        Args:
            profile: The profile to tailor.
            job_description: The job posting text.

        Returns:
            The tailored :class:`TailoredResume`.

        Raises:
            json.JSONDecodeError: When the LLM output cannot be parsed.
        """
        user_msg = TAILOR_USER_TEMPLATE.format(
            name=profile.name,
            summary=profile.summary or "(none)",
            skills=", ".join(profile.skills) if profile.skills else "(none)",
            experience=_format_experience(profile),
            education=_format_education(profile),
            job_description=job_description,
        )

        response = self.agent.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": TAILOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
        )

        raw = response.choices[0].message.content or "{}"
        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        data = json.loads(raw)

        tailored_exp = data.get("experience_bullets", [])
        tailored_edu = data.get("education_bullets", [])

        return TailoredResume(
            original_profile=profile,
            job_description=job_description,
            tailored_sections={
                "experience": tailored_exp,
                "education": tailored_edu,
            },
            summary=data.get("summary", profile.summary),
            updated_skills=data.get("skills", list(profile.skills)),
        )

    # ------------------------------------------------------------------
    # Heuristic fallback (no LLM available)
    # ------------------------------------------------------------------

    def _heuristic_tailor(self, profile: Profile, job_description: str) -> TailoredResume:
        """Tailor using keyword matching without an LLM.

        Args:
            profile: The profile to tailor.
            job_description: The job posting text.

        Returns:
            A :class:`TailoredResume` with JD-matched skills and unchanged
            experience bullets.
        """
        jd_lower = job_description.lower()

        # Skills: keep existing, add JD-matched keywords
        matched_skills = [s for s in profile.skills if s.lower() in jd_lower]
        new_skills = []
        common = {
            "the", "and", "for", "with", "have", "they", "this", "that",
            "are", "was", "were", "will", "would", "could", "should",
            "can", "may", "might", "in", "on", "at", "by", "to", "of",
            "from", "up", "down", "out", "off", "over", "under", "our",
            "your", "their", "its", "about", "into", "through", "during",
            "before", "after", "above", "below", "between", "same",
        }
        for token in jd_lower.split():
            clean = token.strip(".,;:()[]{}\"'")
            if (
                len(clean) > 3
                and clean.isalpha()
                and clean not in common
                and clean not in [s.lower() for s in profile.skills]
                and clean not in [s.lower() for s in new_skills]
            ):
                if len(new_skills) >= 5:
                    break
                # Capitalise for display
                new_skills.append(clean.title())

        updated_skills = list(profile.skills) + new_skills

        # Experience bullets: keep originals (LLM would rewrite)
        exp_bullets = profile.get_experience_bullets()

        # Education bullets
        edu_bullets = []
        for section in profile.education:
            edu_bullets.extend(section.bullets)

        return TailoredResume(
            original_profile=profile,
            job_description=job_description,
            tailored_sections={"experience": exp_bullets, "education": edu_bullets},
            summary=profile.summary,
            updated_skills=updated_skills,
        )


# ------------------------------------------------------------------
# DOCX rebuild
# ------------------------------------------------------------------

def create_tailored_docx(
    template_path: str,
    tailored_resume: TailoredResume,
    output_path: str,
):
    """Rebuild a DOCX from a template, embedding the tailored resume content.

    Args:
        template_path: Path to the template DOCX (used for section/page props).
        tailored_resume: The tailored resume to embed.
        output_path: Where to write the generated DOCX.
    """
    doc = Document(template_path)

    # Clear existing body elements (preserve section properties)
    body = doc.element.body
    for child in list(body):
        if child.tag.endswith("}bodyPr") or child.tag.endswith("}tblStyle"):
            continue
        body.remove(child)

    # Name
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(tailored_resume.original_profile.name)
    run.bold = True
    run.font.size = Pt(14)

    # Contact
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    contact = " | ".join(
        filter(None, [
            tailored_resume.original_profile.email,
            tailored_resume.original_profile.phone,
        ])
    )
    run = p.add_run(contact)
    run.font.size = Pt(10)

    # Summary
    p = doc.add_paragraph()
    r = p.add_run("SUMMARY\n")
    r.bold = True
    p.add_run(tailored_resume.summary)

    # Skills
    p = doc.add_paragraph()
    r = p.add_run("SKILLS\n")
    r.bold = True
    p.add_run(", ".join(tailored_resume.updated_skills))

    # Experience
    p = doc.add_paragraph()
    r = p.add_run("EXPERIENCE\n")
    r.bold = True
    for bullet in tailored_resume.tailored_sections.get("experience", []):
        doc.add_paragraph(bullet, style="List Bullet")

    # Education
    edu = tailored_resume.tailored_sections.get("education", [])
    if edu:
        p = doc.add_paragraph()
        r = p.add_run("EDUCATION\n")
        r.bold = True
        for bullet in edu:
            doc.add_paragraph(bullet, style="List Bullet")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)

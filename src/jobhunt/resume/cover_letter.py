"""
Cover letter generation — LLM-powered via oMLX
"""
from typing import Optional
from pydantic import BaseModel
from .profile_parser import Profile
import json
import logging

logger = logging.getLogger(__name__)

COVER_LETTER_SYSTEM_PROMPT = """\
You are a professional cover letter writer. Given a candidate's resume profile \
and a job description, write a compelling, concise cover letter.

Rules:
- Address the hiring manager (or use provided recipient name).
- Reference specific skills/experience from the profile that match the JD.
- Keep it to 3-4 paragraphs, ~250 words.
- Tone: professional, enthusiastic, specific.
- Do NOT fabricate experience.
- Return ONLY valid JSON matching the schema below.

Output schema:
{
  "content": "<full cover letter text>"
}
"""

COVER_LETTER_USER_TEMPLATE = """\
## Candidate Profile

**Name:** {name}
**Summary:** {summary}
**Key Skills:** {skills}

## Job Description

{job_description}

## Instructions

{instructions}

Return the cover letter as JSON only — no markdown fences, no commentary.
"""


class CoverLetter(BaseModel):
    profile: Profile
    job_description: str
    content: str
    recipient_name: Optional[str] = None
    company_name: Optional[str] = None


class CoverLetterGenerator:
    def __init__(self, agent=None, model: str = "Qwen3-30B-A3B-6bit"):
        self.agent = agent
        self.model = model

    def generate_cover_letter(
        self,
        profile: Profile,
        job_description: str,
        company_name: Optional[str] = None,
        recipient_name: Optional[str] = None,
        custom_instructions: Optional[str] = None,
    ) -> CoverLetter:
        if self.agent is not None:
            try:
                return self._llm_generate(
                    profile, job_description, company_name,
                    recipient_name, custom_instructions,
                )
            except Exception:
                logger.exception("LLM cover letter failed, falling back to template")
        return self._template_generate(
            profile, job_description, company_name, recipient_name,
        )

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------

    def _llm_generate(
        self,
        profile: Profile,
        job_description: str,
        company_name: Optional[str],
        recipient_name: Optional[str],
        custom_instructions: Optional[str],
    ) -> CoverLetter:
        instructions_lines = []
        if company_name:
            instructions_lines.append(f"Company: {company_name}")
        if recipient_name:
            instructions_lines.append(f"Recipient: {recipient_name}")
        if custom_instructions:
            instructions_lines.append(f"Additional instructions: {custom_instructions}")
        if not instructions_lines:
            instructions_lines.append("Write a general cover letter.")

        user_msg = COVER_LETTER_USER_TEMPLATE.format(
            name=profile.name,
            summary=profile.summary or "(none)",
            skills=", ".join(profile.skills[:10]) if profile.skills else "(none)",
            job_description=job_description,
            instructions="\n".join(instructions_lines),
        )

        response = self.agent.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": COVER_LETTER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
        )

        raw = response.choices[0].message.content or "{}"
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        data = json.loads(raw)
        content = data.get("content", "")

        return CoverLetter(
            profile=profile,
            job_description=job_description,
            content=content,
            recipient_name=recipient_name,
            company_name=company_name,
        )

    # ------------------------------------------------------------------
    # Template fallback (no LLM)
    # ------------------------------------------------------------------

    def _template_generate(
        self,
        profile: Profile,
        job_description: str,
        company_name: Optional[str],
        recipient_name: Optional[str],
    ) -> CoverLetter:
        company = company_name or "your company"
        recipient = recipient_name or "Hiring Manager"

        # Extract a few keywords from the JD for personalisation
        jd_words = [
            w.strip(".,;:()[]{}\"'")
            for w in job_description.lower().split()
            if len(w.strip(".,;:()[]{}\"'")) > 4
        ]
        keywords = list(dict.fromkeys(jd_words))[:5]
        keyword_str = ", ".join(keywords) if keywords else "the role"

        content = f"""\
{recipient},

I am writing to express my interest in the position at {company}. With my background in {keyword_str} and proven success in delivering results, I am confident I can make meaningful contributions to your team.

My experience aligns closely with the requirements outlined in your posting. I have a strong track record of tackling challenges similar to those described, and I am eager to bring that expertise to {company}.

I am particularly drawn to {company} because of its mission and the opportunity to work alongside talented colleagues. I would welcome the chance to discuss how my skills and experience align with your needs.

Thank you for your consideration. I look forward to hearing from you.

Sincerely,
{profile.name}
{profile.email}
{profile.phone}
"""
        return CoverLetter(
            profile=profile,
            job_description=job_description,
            content=content,
            recipient_name=recipient_name,
            company_name=company_name,
        )

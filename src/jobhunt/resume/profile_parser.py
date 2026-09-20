"""
Profile parsing and resume handling
"""
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from pydantic import BaseModel, Field
import re


class ResumeSection(BaseModel):
    """A section of a resume"""
    title: str
    content: str
    bullets: List[str] = Field(default_factory=list)


class Profile(BaseModel):
    """Structured profile parsed from a resume"""
    name: str = ""
    email: str = ""
    phone: str = ""
    summary: str = ""
    experience: List[ResumeSection] = Field(default_factory=list)
    education: List[ResumeSection] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    projects: List[ResumeSection] = Field(default_factory=list)

    def get_experience_bullets(self) -> List[str]:
        """Extract all experience bullets"""
        bullets = []
        for section in self.experience:
            bullets.extend(section.bullets)
        return bullets

    def get_skills_str(self) -> str:
        """Get skills as a comma-separated string"""
        return ", ".join(self.skills)

    def get_summary(self) -> str:
        """Get summary text"""
        return self.summary


class DocxParser:
    """Parse DOCX files into structured Profile objects"""
    
    def __init__(self, docx_path: str):
        self.docx_path = docx_path
        self.doc = Document(docx_path)
        self.profile = Profile()
        
    def parse(self) -> Profile:
        """Parse the DOCX file and return a Profile object"""
        self._parse_metadata()
        self._parse_sections()
        self._clean_profile()
        return self.profile
        
    def _parse_metadata(self):
        """Parse name, email, phone from document"""
        # Get document paragraphs
        paragraphs = [paragraph.text.strip() for paragraph in self.doc.paragraphs if paragraph.text.strip()]
        
        # Look for email pattern
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        for paragraph in paragraphs:
            emails = re.findall(email_pattern, paragraph)
            if emails:
                self.profile.email = emails[0]
                
        # Look for phone number pattern
        phone_pattern = r'(\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9})'
        for paragraph in paragraphs:
            phones = re.findall(phone_pattern, paragraph)
            if phones:
                self.profile.phone = phones[0]
                
    def _parse_sections(self):
        """Parse document sections"""
        # Get all paragraphs
        paragraphs = [paragraph for paragraph in self.doc.paragraphs if paragraph.text.strip()]
        
        # Look for section headers
        section_headers = ["experience", "work experience", "professional experience", 
                          "education", "skills", "certifications", "projects", "summary"]
        
        current_section = None
        current_section_content = []
        
        for i, paragraph in enumerate(paragraphs):
            text = paragraph.text.strip()
            if not text:
                continue
                
            # Check if this is a section header
            lower_text = text.lower()
            if any(header in lower_text for header in section_headers):
                # Save previous section if exists
                if current_section and current_section_content:
                    self._save_section(current_section, current_section_content)
                
                # Set new section
                current_section = self._normalize_section_name(lower_text)
                current_section_content = []
            elif current_section:
                # If we have a current section, add content
                if self._is_bullet_point(paragraph):
                    # Handle bullet points
                    if current_section == "summary":
                        # For summary, treat as continuous text
                        current_section_content.append(text)
                    else:
                        current_section_content.append(text)
                elif self._is_experience_timeline(paragraph) and current_section == "experience":
                    # If it's an experience timeline with no bullet, add as content
                    current_section_content.append(text)  
                else:
                    # This continues the previous section
                    current_section_content.append(text)
        
        # Save final section
        if current_section and current_section_content:
            self._save_section(current_section, current_section_content)
                
    def _normalize_section_name(self, name: str) -> str:
        """Normalize section names"""
        # Use word boundaries to avoid partial matches
        if any(re.search(r'\b' + re.escape(word) + r'\b', name) for word in ["experience", "work"]):
            return "experience"
        elif re.search(r'\b' + re.escape("education") + r'\b', name):
            return "education"
        elif re.search(r'\b' + re.escape("skills") + r'\b', name):
            return "skills"
        elif re.search(r'\b' + re.escape("certifications") + r'\b', name) or re.search(r'\b' + re.escape("certification") + r'\b', name):
            return "certifications"
        elif re.search(r'\b' + re.escape("projects") + r'\b', name):
            return "projects"
        elif re.search(r'\b' + re.escape("summary") + r'\b', name) or re.search(r'\b' + re.escape("profile") + r'\b', name):
            return "summary"
        else:
            return "experience"  # Default fallback
            
    def _is_bullet_point(self, paragraph) -> bool:
        """Check if paragraph is a bullet point"""
        if paragraph.style.name.startswith('List'):
            return True
        
        # Check for bullet markers in the paragraph
        bullet_chars = ['•', '·', '◦', '▪', '▸', '►', '➢', '➣']
        if len(paragraph.runs) > 0:
            first_run_text = paragraph.runs[0].text
            return any(char in first_run_text for char in bullet_chars)
            
        return False
        
    def _is_experience_timeline(self, paragraph) -> bool:
        """Check if paragraph is an experience timeline (e.g., "2020 - 2022")"""
        # Require year range with dash for a timeline
        timeline_pattern = r'\d{4}\s*-\s*\d{4}'
        return bool(re.search(timeline_pattern, paragraph.text))
        
    def _save_section(self, section_name: str, content: List[str]):
        """Save a parsed section to profile"""
        text_content = " ".join(content).strip()
        
        if section_name == "summary":
            self.profile.summary = text_content
        elif section_name == "skills":
            self.profile.skills = self._extract_skills(text_content)
        elif section_name == "certifications":
            self.profile.certifications = content
        elif section_name == "experience":
            # Process experience as a section with bullets
            section = self._parse_experience_section(content)
            self.profile.experience.append(section)
        elif section_name == "education":
            # Process education as a section with bullets
            section = self._parse_education_section(content)
            self.profile.education.append(section)
        elif section_name == "projects":
            # Process projects as a section with bullets
            section = self._parse_projects_section(content)
            self.profile.projects.append(section)
            
    def _extract_skills(self, text: str) -> List[str]:
        """Extract skills from text"""
        # Simple approach: split on commas or catch words that appear to be skills
        skills = []
        # Split on commas for lists and remove extra whitespace
        for skill in text.split(','):
            skill = skill.strip()
            if skill:
                skills.append(skill)
        # Return unique skills, in order of appearance
        return list(dict.fromkeys(skills))  # Remove duplicates while preserving order
        
    def _parse_experience_section(self, content: List[str]) -> ResumeSection:
        """Parse experience section into structured data"""
        title = "Experience"
        bullets = []
        
        for item in content:
            if item.lower() in ["experience", "work experience"]:
                continue
            bullets.append(item)
        
        return ResumeSection(title=title, content=" ".join(content), bullets=bullets)
        
    def _parse_education_section(self, content: List[str]) -> ResumeSection:
        """Parse education section into structured data"""
        title = "Education"
        return ResumeSection(title=title, content=" ".join(content), bullets=list(content))
        
    def _parse_projects_section(self, content: List[str]) -> ResumeSection:
        """Parse projects section into structured data"""
        title = "Projects"
        return ResumeSection(title=title, content=" ".join(content), bullets=list(content))
        
    def _clean_profile(self):
        """Clean and finalize the profile"""
        # Get first paragraph for name, if it's in a heading style or looks like a name
        if not self.profile.name:
            for paragraph in self.doc.paragraphs:
                if paragraph.style.name in ['Heading 1', 'Heading 2']:
                    self.profile.name = paragraph.text.strip()
                    break
                elif len(paragraph.text.strip()) < 50 and not paragraph.text.strip().startswith("@"):
                    # Assume first short paragraph is likely name
                    self.profile.name = paragraph.text.strip()
                    break


def load_profile_from_cache(cache_path: str) -> Optional[Profile]:
    """Load profile from cache file"""
    try:
        with open(cache_path, 'r') as f:
            data = json.load(f)
            return Profile(**data)
    except Exception:
        return None


def save_profile_to_cache(profile: Profile, cache_path: str):
    """Save profile to cache file"""
    with open(cache_path, 'w') as f:
        json.dump(profile.model_dump(), f, indent=2)


def find_resume_files(resume_dir: str) -> List[str]:
    """Find all DOCX files in resume directory"""
    files = []
    for file in os.listdir(resume_dir):
        if file.lower().endswith('.docx'):
            files.append(file)
    return files


def select_resume_file(resume_dir: str) -> str:
    """Select a resume from the directory"""
    files = find_resume_files(resume_dir)
    if not files:
        raise FileNotFoundError(f"No DOCX files found in {resume_dir}")
    
    # For now, return the first one
    return os.path.join(resume_dir, files[0])


def parse_profile_from_docx(docx_path: str) -> Profile:
    """Parse a DOCX file and return a Profile object"""
    parser = DocxParser(docx_path)
    return parser.parse()
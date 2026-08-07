"""Pydantic schemas for resume extraction and gap analysis."""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class WorkExperience(BaseModel):
    role: str
    organization: str
    duration: Optional[str] = Field(description="Dates or length as written, null if absent")
    highlights: list[str] = Field(description="Responsibilities and achievements, each as its own item")


class Education(BaseModel):
    credential: str = Field(description="Degree or diploma name")
    institution: str
    dates: Optional[str] = Field(description="As written, null if absent")
    coursework: list[str] = Field(description="Relevant courses named on the resume. Empty if none listed.")


class Project(BaseModel):
    name: str
    description: str = Field(description="What it is and what was built")
    technologies: list[str] = Field(description="Tools and languages used")


class Resume(BaseModel):
    """Structured resume data using categories that map to how postings are written."""

    name: str
    location: Optional[str]
    hard_skills: list[str] = Field(description="Languages, frameworks, tools, platforms. Individual items only.")
    soft_skills: list[str] = Field(description="Communication, leadership, collaboration, and similar")
    work_experience: list[WorkExperience]
    education: list[Education]
    certifications: list[str] = Field(description="Certifications and completed training, including in-progress ones")
    projects: list[Project]
    domain_keywords: list[str] = Field(
        description="Methodologies and domain terms such as Agile, CI/CD, REST API design, microservices"
    )


class Gap(BaseModel):
    """One thing the market wants that the resume does not show well."""

    skill_or_requirement: str
    market_evidence: str = Field(description="How often and where this appears in the postings")
    current_state: str = Field(description="What the resume shows about this today, honestly")
    level: Literal["quick win", "short-term", "medium-term", "long-term"]
    action: str = Field(
        description="One specific action with a named resource and rough time cost. Not generic advice."
    )


class GapAnalysis(BaseModel):
    strengths: list[str] = Field(description="Resume qualifications that match frequent market demands, with counts")
    gaps: list[Gap]
    unique_value: list[str] = Field(description="Differentiators not commonly asked for in the postings")
    summary: str = Field(description="Two or three sentences on where this candidate stands")

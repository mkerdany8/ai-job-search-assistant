"""Pydantic schemas for job posting extraction and analysis."""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class SalaryRange(BaseModel):
    """Salary info as listed in the posting. All fields null if not listed."""
    min_amount: Optional[float] = Field(description="Lower bound of the range, null if not listed")
    max_amount: Optional[float] = Field(description="Upper bound of the range, null if not listed")
    currency: Optional[str] = Field(description="Currency code such as CAD or USD, null if not listed")
    period: Optional[Literal["hourly", "monthly", "yearly"]] = Field(
        description="Pay period, null if not listed"
    )


class ExperienceLevel(BaseModel):
    """Experience the posting asks for."""
    min_years: Optional[int] = Field(description="Minimum years of experience required, null if not stated")
    seniority: Optional[Literal["intern", "junior", "mid", "senior", "lead", "not stated"]] = Field(
        description="Seniority level of the role"
    )


class JobPosting(BaseModel):
    """Structured data extracted from a single job posting."""

    job_title: str = Field(description="Exact job title as written in the posting")
    company_name: str = Field(description="Name of the hiring company")
    location: str = Field(description="City and province/state, or 'not listed'")
    remote_status: Literal["remote", "hybrid", "on-site", "not listed"] = Field(
        description="Work arrangement stated in the posting"
    )
    posting_age_days: Optional[int] = Field(
        description="How many days old the posting is, calculated from the reference date given. Null if no date info appears in the posting."
    )
    required_skills: list[str] = Field(
        description="Hard skills and technologies explicitly required. Individual items only, no combined phrases."
    )
    preferred_skills: list[str] = Field(
        description="Nice-to-have skills listed as preferred, bonus, or an asset. Empty list if none listed."
    )
    experience: ExperienceLevel
    education: Optional[str] = Field(
        description="Education requirement as stated, for example 'Bachelor's in Computer Science'. Null if not listed."
    )
    salary: SalaryRange
    responsibilities: list[str] = Field(
        description="Key responsibilities of the role, each as a short phrase"
    )

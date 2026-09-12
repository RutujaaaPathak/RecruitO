# pyrefly: ignore [missing-import]
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Literal
from datetime import datetime, date

from app.models import (
    RoleEnum,
    JobStatusEnum,
    ApplicationStatusEnum,
    InterviewStatusEnum,
)


# -----------------------------
# User / Profile
# -----------------------------
class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    category: Optional[str] = None
    skills: Optional[List[str]] = None


class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: RoleEnum
    is_active: bool = True
    phone: Optional[str] = None
    category: Optional[str] = None
    skills: Optional[List[str]] = None
    created_at: datetime

    class Config:
        from_attributes = True


# -----------------------------
# Company
# -----------------------------
class CompanyCreate(BaseModel):
    name: str
    website: Optional[str] = None
    registration_number: Optional[str] = None
    industry: Optional[str] = None
    location: Optional[str] = None
    size: Optional[str] = None
    about: Optional[str] = None
    logo_url: Optional[str] = None


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    website: Optional[str] = None
    registration_number: Optional[str] = None
    industry: Optional[str] = None
    location: Optional[str] = None
    size: Optional[str] = None
    about: Optional[str] = None
    logo_url: Optional[str] = None


class CompanyOut(BaseModel):
    id: int
    user_id: int
    name: str
    website: Optional[str] = None
    registration_number: Optional[str] = None
    industry: Optional[str] = None
    location: Optional[str] = None
    size: Optional[str] = None
    about: Optional[str] = None
    logo_url: Optional[str] = None
    approved: bool
    created_at: datetime

    class Config:
        from_attributes = True


# -----------------------------
# Job
# -----------------------------
class JobCreate(BaseModel):
    title: str
    department: Optional[str] = None
    location: Optional[str] = None
    type: Optional[str] = None
    experience: Optional[str] = None
    salary: Optional[str] = None
    skills: Optional[List[str]] = None
    vacancies: Optional[int] = 1
    description: Optional[str] = None
    deadline: Optional[date] = None
    status: Optional[JobStatusEnum] = JobStatusEnum.open


class JobUpdate(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    location: Optional[str] = None
    type: Optional[str] = None
    experience: Optional[str] = None
    salary: Optional[str] = None
    skills: Optional[List[str]] = None
    vacancies: Optional[int] = None
    description: Optional[str] = None
    deadline: Optional[date] = None
    status: Optional[JobStatusEnum] = None


class JobOut(BaseModel):
    id: int
    company_id: int
    title: str
    department: Optional[str] = None
    location: Optional[str] = None
    type: Optional[str] = None
    experience: Optional[str] = None
    salary: Optional[str] = None
    skills: Optional[List[str]] = None
    vacancies: int
    description: Optional[str] = None
    deadline: Optional[date] = None
    status: JobStatusEnum
    posted_on: datetime
    company_name: Optional[str] = None
    applicant_count: int = 0

    class Config:
        from_attributes = True


# -----------------------------
# Resume
# -----------------------------
class ResumeOut(BaseModel):
    id: int
    user_id: int
    original_filename: str
    extension: Optional[str] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True


# -----------------------------
# Application
# -----------------------------
class ApplicationCreate(BaseModel):
    job_id: int


class ApplicationOut(BaseModel):
    id: int
    job_id: int
    user_id: int
    status: ApplicationStatusEnum
    match_score: Optional[int] = None
    created_at: datetime
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    applicant_name: Optional[str] = None
    applicant_email: Optional[EmailStr] = None
    applicant_phone: Optional[str] = None
    applicant_skills: Optional[List[str]] = None

    class Config:
        from_attributes = True


class ApplicationUpdate(BaseModel):
    status: ApplicationStatusEnum


# -----------------------------
# Skill Gap
# -----------------------------
class SkillGapItem(BaseModel):
    skill: str
    recommendation: str


class SkillGapReport(BaseModel):
    application_id: int
    job_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    required_skills: List[str] = []
    matched_skills: List[str] = []
    missing_skills: List[SkillGapItem] = []
    matched_count: int = 0
    missing_count: int = 0
    coverage_percent: int = 0
    summary: str = ""


# -----------------------------
# Semantic match
# -----------------------------
class SemanticMatchOut(BaseModel):
    application_id: int
    job_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    candidate_name: Optional[str] = None
    # Existing rule-based ATS score, returned unchanged.
    match_score: Optional[int] = None
    # New, independent semantic similarity score (0-100).
    semantic_score: Optional[int] = None
    cosine_similarity: Optional[float] = None
    embedding_model: Optional[str] = None
    used_fallback: bool = False
    explanation: Optional[str] = None


# -----------------------------
# AI Career Recommendations
# -----------------------------
class SkillLearningPriority(BaseModel):
    skill: str
    reason: str = ""
    priority: Literal["high", "medium", "low"] = "medium"


class LearningStep(BaseModel):
    step: str
    detail: str = ""


class ProjectIdea(BaseModel):
    title: str
    description: str = ""


class CareerRecommendationsOut(BaseModel):
    application_id: int
    job_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    # Context used to ground the recommendations.
    ats_score: Optional[int] = None
    semantic_score: Optional[int] = None
    matched_skills: List[str] = []
    missing_skills: List[str] = []
    # Generated plan (validated structured JSON).
    summary: str = ""
    priority_skills: List[SkillLearningPriority] = []
    learning_path: List[LearningStep] = []
    project_ideas: List[ProjectIdea] = []
    resume_improvements: List[str] = []
    # Source of the plan: "llm" or "fallback".
    generated_by: Literal["llm", "fallback"] = "fallback"
    notice: Optional[str] = None
    # RAG sources: the retrieved resume chunks used to ground the plan.
    sources: List["ChunkSource"] = []


class ChunkSource(BaseModel):
    chunk_id: int
    chunk_index: int
    section: Optional[str] = None
    score: Optional[int] = None
    content: str


class RetrievedChunkOut(BaseModel):
    chunk_id: int
    chunk_index: int
    section: Optional[str] = None
    score: Optional[int] = None
    content: str


class RetrievedChunksOut(BaseModel):
    application_id: int
    job_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    # Embedding model used for retrieval, or "fallback"/"none".
    model_used: str = "none"
    used_fallback: bool = False
    chunks: List[RetrievedChunkOut] = []


# -----------------------------
# Interview
# -----------------------------
class InterviewCreate(BaseModel):
    application_id: int
    scheduled_at: datetime
    notes: Optional[str] = None


class InterviewUpdate(BaseModel):
    scheduled_at: Optional[datetime] = None
    status: Optional[InterviewStatusEnum] = None
    notes: Optional[str] = None
    score: Optional[int] = None


class InterviewOut(BaseModel):
    id: int
    application_id: int
    job_id: int
    user_id: int
    scheduled_at: Optional[datetime] = None
    status: InterviewStatusEnum
    notes: Optional[str] = None
    score: Optional[int] = None
    created_at: datetime
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    applicant_name: Optional[str] = None
    applicant_email: Optional[str] = None
    applicant_phone: Optional[str] = None

    class Config:
        from_attributes = True

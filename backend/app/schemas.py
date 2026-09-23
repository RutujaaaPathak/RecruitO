# pyrefly: ignore [missing-import]
from pydantic import BaseModel, EmailStr, Field, model_validator
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime, date

from app.models import (
    RoleEnum,
    JobStatusEnum,
    ApplicationStatusEnum,
    InterviewStatusEnum,
    MockInterviewStatusEnum,
    AssessmentStatusEnum,
    CodingTestStatusEnum,
    NotificationType,
    CompanyAssessmentStatusEnum,
    AssessmentSectionTypeEnum,
    AssessmentAssignmentStatusEnum,
    AssessmentQuestionTypeEnum,
)
from app.services.coding_tests import SUPPORTED_LANGUAGES


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


# -----------------------------
# AI Chatbot
# -----------------------------
class ChatSendIn(BaseModel):
    message: str
    # Optional application context; forwarded to the RAG pipeline when given.
    application_id: Optional[int] = None
    # Optional existing session to continue; a new session is created when absent.
    session_id: Optional[int] = None


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    sources: List[ChunkSource] = []
    model_used: Optional[str] = None
    generated_by: Optional[str] = None
    created_at: datetime


class ChatSessionOut(BaseModel):
    id: int
    application_id: Optional[int] = None
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ChatReplyOut(BaseModel):
    session_id: int
    application_id: Optional[int] = None
    message: ChatMessageOut
    sources: List[ChunkSource] = []
    generated_by: Literal["llm", "fallback"] = "fallback"
    notice: Optional[str] = None
    model_used: str = "none"


# -----------------------------
# AI Mock Interview
# -----------------------------
class MockInterviewStartIn(BaseModel):
    application_id: int


class MockInterviewAnswerIn(BaseModel):
    answer_text: str = Field(..., min_length=1, max_length=6000)


class MockInterviewQuestionOut(BaseModel):
    id: int
    question_index: int
    category: str
    question_text: str
    generated_by: Literal["llm", "fallback"] = "fallback"
    notice: Optional[str] = None
    sources: List[ChunkSource] = []


class EvaluationOut(BaseModel):
    score: int  # 0-10
    correctness: str = ""
    strengths: List[str] = []
    weaknesses: List[str] = []
    missing_points: List[str] = []
    feedback: str = ""
    generated_by: Literal["llm", "fallback"] = "fallback"
    notice: Optional[str] = None


class AnsweredQuestionOut(BaseModel):
    question: MockInterviewQuestionOut
    answer: str
    evaluation: EvaluationOut


class CategoryScoreOut(BaseModel):
    category: str
    score: int = 0
    comment: str = ""


class MockInterviewReportOut(BaseModel):
    overall_score: int = 0
    category_scores: List[CategoryScoreOut] = []
    strengths: List[str] = []
    weaknesses: List[str] = []
    recommended_topics: List[str] = []
    summary: str = ""
    generated_by: Literal["llm", "fallback"] = "fallback"
    notice: Optional[str] = None


class MockInterviewListOut(BaseModel):
    id: int
    application_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    status: MockInterviewStatusEnum
    max_questions: int
    answered_count: int = 0
    overall_score: Optional[int] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class MockInterviewDetailOut(BaseModel):
    id: int
    application_id: int
    user_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    status: MockInterviewStatusEnum
    max_questions: int
    current_question: Optional[MockInterviewQuestionOut] = None
    answered: List[AnsweredQuestionOut] = []
    matched_skills: List[str] = []
    missing_skills: List[str] = []
    model_used: str = "none"
    used_fallback: bool = False
    report: Optional[MockInterviewReportOut] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class MockInterviewAnswerResponse(BaseModel):
    interview: MockInterviewDetailOut
    evaluation: EvaluationOut
    next_question: Optional[MockInterviewQuestionOut] = None
    report: Optional[MockInterviewReportOut] = None


# -----------------------------
# AI MCQ Assessment
# -----------------------------
class McqAssessmentStartIn(BaseModel):
    application_id: int


class McqAnswerIn(BaseModel):
    question_index: int = Field(..., ge=0)
    selected_option: int = Field(..., ge=0, le=3)


class McqQuestionOut(BaseModel):
    """A question as delivered to the candidate DURING the test.

    Deliberately omits ``correct_option_index`` so correct answers are never
    exposed before submission. ``selected_option`` is the candidate's own saved
    choice (their data), not the answer key.
    """

    id: int
    question_index: int
    category: str
    question_text: str
    options: List[str]  # exactly 4; correct answer is never in this payload
    generated_by: Literal["llm", "fallback"] = "fallback"
    notice: Optional[str] = None
    selected_option: Optional[int] = None  # 0-3


class McqCategoryPerformanceOut(BaseModel):
    category: str
    total: int
    correct: int
    percentage: int


class McqResultsOut(BaseModel):
    score: int
    total: int
    percentage: int  # 0-100
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    passed: bool
    pass_percentage: int
    category_performance: List[McqCategoryPerformanceOut] = []
    expired: bool = False  # True when the timer ran out before submit
    model_used: str = "none"
    generated_by: Literal["llm", "mixed", "fallback"] = "fallback"
    used_fallback: bool = False
    notice: Optional[str] = None


class McqAssessmentListOut(BaseModel):
    id: int
    application_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    status: AssessmentStatusEnum
    total_questions: int
    answered_count: int = 0
    time_limit_minutes: int
    score: Optional[int] = None
    percentage: Optional[int] = None
    passed: Optional[bool] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class McqAssessmentDetailOut(BaseModel):
    id: int
    application_id: int
    user_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    status: AssessmentStatusEnum
    total_questions: int
    answered_count: int = 0
    time_limit_minutes: int
    started_at: datetime
    expires_at: Optional[datetime] = None
    questions: List[McqQuestionOut] = []
    results: Optional[McqResultsOut] = None
    generated_by: Literal["llm", "mixed", "fallback"] = "fallback"
    used_fallback: bool = False
    model_used: str = "none"
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# -----------------------------
# Coding Test
# -----------------------------
class CodingTestStartIn(BaseModel):
    application_id: int


class CodingRunIn(BaseModel):
    language: Literal["python", "java", "cpp"]
    code: str = Field(..., min_length=1)
    problem_index: int = Field(..., ge=0)


class CodingSubmitIn(CodingRunIn):
    pass


class CodingTestCaseResultOut(BaseModel):
    case_index: int
    passed: bool
    status: str  # passed | wrong_answer | runtime_error | timeout | compile_error
    stdout: str = ""
    stderr: str = ""
    time_ms: int = 0


class CodingRunOut(BaseModel):
    problem_index: int
    language: str
    compile_error: bool = False
    compile_stderr: str = ""
    test_results: List[CodingTestCaseResultOut] = []


class CodingSubmissionOut(BaseModel):
    problem_index: int
    language: str
    status: str  # passed | failed | error | timeout
    passed_cases: int
    total_cases: int
    score: int  # 0-100
    execution_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    results: List[CodingTestCaseResultOut] = []
    created_at: datetime


class CodingProblemOut(BaseModel):
    """A problem as delivered to the candidate DURING the test.

    Deliberately omits ``hidden_cases`` so graded cases are never exposed.
    ``sample_cases`` are public (shown in the problem statement).
    """

    id: int
    problem_index: int
    title: str
    category: str
    difficulty: str
    description: str
    input_format: str
    output_format: str
    constraints: str
    sample_cases: List[dict]
    supported_languages: List[str]
    submission: Optional[CodingSubmissionOut] = None


class CodingTestListOut(BaseModel):
    id: int
    application_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    status: CodingTestStatusEnum
    total_problems: int
    solved_count: int
    score: Optional[int] = None
    passed: Optional[bool] = None
    pass_percentage: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CodingTestDetailOut(BaseModel):
    id: int
    application_id: int
    user_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    status: CodingTestStatusEnum
    total_problems: int
    solved_count: int
    score: Optional[int] = None
    passed: Optional[bool] = None
    pass_percentage: int
    problems: List[CodingProblemOut] = []
    started_at: datetime
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# -----------------------------
# Aptitude Test
# -----------------------------
class AptitudeTestStartIn(BaseModel):
    application_id: int


class AptitudeAnswerIn(BaseModel):
    question_index: int = Field(..., ge=0)
    selected_option: int = Field(..., ge=0, le=3)


class AptitudeQuestionOut(BaseModel):
    """A question as delivered to the candidate DURING the test.

    Deliberately omits ``correct_option_index`` so correct answers are never
    exposed before submission. ``selected_option`` is the candidate's own saved
    choice (their data), not the answer key.
    """

    id: int
    question_index: int
    category: str  # quantitative | logical_reasoning | verbal
    question_text: str
    options: List[str]  # exactly 4; correct answer is never in this payload
    generated_by: Literal["llm", "fallback"] = "fallback"
    notice: Optional[str] = None
    selected_option: Optional[int] = None  # 0-3


class AptitudeCategoryPerformanceOut(BaseModel):
    category: str
    total: int
    correct: int
    percentage: int


class AptitudeResultsOut(BaseModel):
    score: int
    total: int
    percentage: int  # 0-100
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    passed: bool
    pass_percentage: int
    category_performance: List[AptitudeCategoryPerformanceOut] = []
    expired: bool = False  # True when the timer ran out before submit
    model_used: str = "none"
    generated_by: Literal["llm", "mixed", "fallback"] = "fallback"
    used_fallback: bool = False
    notice: Optional[str] = None


class AptitudeTestListOut(BaseModel):
    id: int
    application_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    status: AssessmentStatusEnum
    total_questions: int
    answered_count: int = 0
    time_limit_minutes: int
    score: Optional[int] = None
    percentage: Optional[int] = None
    passed: Optional[bool] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AptitudeTestDetailOut(BaseModel):
    id: int
    application_id: int
    user_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    status: AssessmentStatusEnum
    total_questions: int
    answered_count: int = 0
    time_limit_minutes: int
    started_at: datetime
    expires_at: Optional[datetime] = None
    questions: List[AptitudeQuestionOut] = []
    results: Optional[AptitudeResultsOut] = None
    generated_by: Literal["llm", "mixed", "fallback"] = "fallback"
    used_fallback: bool = False
    model_used: str = "none"
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# -----------------------------
# Technical Video Interview
# -----------------------------
class VideoInterviewStartIn(BaseModel):
    """Body used to create a video interview session for an application.

    ``interview_type`` selects the interview flavour: ``"technical"`` (default)
    for the technical AI interview or ``"hr"`` for the HR mock interview. The
    camera/microphone enablement is recorded from the candidate's live device
    state at the moment the room is entered.
    """

    application_id: int
    interview_type: Literal["technical", "hr"] = "technical"
    camera_enabled: bool = True
    microphone_enabled: bool = True


class VideoInterviewDeviceStateIn(BaseModel):
    """The candidate's current camera/microphone toggles, synced from the room."""

    camera_enabled: bool
    microphone_enabled: bool


class VideoInterviewAnswerIn(BaseModel):
    """Body used to submit the candidate's text answer to the current
    technical video-interview question."""

    answer_text: str = Field(..., min_length=1, max_length=6000)


class VideoInterviewListOut(BaseModel):
    id: int
    application_id: int
    interview_type: str = "technical"
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    status: AssessmentStatusEnum
    camera_enabled: bool
    microphone_enabled: bool
    overall_score: Optional[int] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class VideoInterviewDetailOut(BaseModel):
    id: int
    application_id: int
    user_id: int
    interview_type: str = "technical"
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    status: AssessmentStatusEnum
    camera_enabled: bool
    microphone_enabled: bool
    max_questions: int = 0
    answered_count: int = 0
    current_question: Optional[MockInterviewQuestionOut] = None
    answered: List[AnsweredQuestionOut] = []
    overall_score: Optional[int] = None
    category_scores: List[CategoryScoreOut] = []
    strengths: List[str] = []
    weaknesses: List[str] = []
    recommended_topics: List[str] = []
    summary: str = ""
    report_generated_by: Literal["llm", "fallback"] = "fallback"
    report_notice: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class VideoInterviewAnswerResponse(BaseModel):
    """Response after the candidate answers the current question: the refreshed
    session (with the new current question and updated history), the evaluation
    of the answered question, and the next question when available."""

    session: VideoInterviewDetailOut
    evaluation: EvaluationOut
    next_question: Optional[MockInterviewQuestionOut] = None


# -----------------------------
# Notifications
# -----------------------------
class NotificationOut(BaseModel):
    id: int
    type: NotificationType
    title: str
    message: str
    link: Optional[str] = None
    read: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


# -----------------------------
# Company Assessments (recruitment pipeline)
# -----------------------------
class AssessmentAssignmentCreate(BaseModel):
    """Hand a published assessment to a candidate.

    ``candidate_id`` is the candidate *user* who must take the assessment. The
    shared (assessment_id, candidate_id) unique constraint guarantees the same
    assessment can never be assigned to the same candidate twice, even under
    concurrent requests.
    """

    assessment_id: int
    candidate_id: int


class AssessmentSectionOut(BaseModel):
    """A serialized section of an assessment (Out contract).

    ``settings`` is opaque JSON (per-section parameters the fulfillment engine
    will interpret); no engine-specific fields leak into this contract.
    """

    id: int
    assessment_id: int
    section_type: AssessmentSectionTypeEnum
    title: str
    section_order: int
    marks: Optional[int] = None
    settings: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AssessmentAssignmentOut(BaseModel):
    """A serialized assignment of an assessment to a candidate (Out contract)."""

    id: int
    assessment_id: int
    candidate_id: int
    status: AssessmentAssignmentStatusEnum
    assigned_at: datetime
    started_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AssessmentOut(BaseModel):
    """A serialized company assessment (Out contract; list/detail base)."""

    id: int
    company_id: int
    title: str
    description: Optional[str] = None
    instructions: Optional[str] = None
    status: CompanyAssessmentStatusEnum
    duration_minutes: Optional[int] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AssessmentDetailOut(AssessmentOut):
    """Full assessment detail: its ordered sections + outstanding assignments."""

    sections: List[AssessmentSectionOut] = []
    assignments: List[AssessmentAssignmentOut] = []


class AssessmentCreate(BaseModel):
    """Create a company assessment (catalog entry — no sections/assignments yet).

    ``status`` defaults to draft. ``duration_minutes`` must be positive and,
    when both ``starts_at`` and ``ends_at`` are supplied, the validity window
    must be ordered (ends_at on or after starts_at).
    """

    title: str
    description: Optional[str] = None
    instructions: Optional[str] = None
    status: Optional[CompanyAssessmentStatusEnum] = CompanyAssessmentStatusEnum.draft
    duration_minutes: Optional[int] = Field(default=None, ge=1)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _validate_validity_window(self):
        if (
            self.ends_at is not None
            and self.starts_at is not None
            and self.ends_at < self.starts_at
        ):
            raise ValueError("ends_at must be on or after starts_at")
        return self


class AssessmentUpdate(BaseModel):
    """Update an assessment. All fields optional (partial update)."""

    title: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    status: Optional[CompanyAssessmentStatusEnum] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _validate_validity_window(self):
        if (
            self.ends_at is not None
            and self.starts_at is not None
            and self.ends_at < self.starts_at
        ):
            raise ValueError("ends_at must be on or after starts_at")
        return self


class AssessmentSectionCreate(BaseModel):
    """Add a section to an assessment.

    ``section_type`` is validated against the existing enum. ``section_order``
    is optional — when omitted the route appends the section at the end.
    """

    section_type: AssessmentSectionTypeEnum
    title: str
    section_order: Optional[int] = Field(default=None, ge=1)
    marks: Optional[int] = Field(default=None, ge=0)
    settings: Optional[dict] = None


class AssessmentSectionUpdate(BaseModel):
    """Update a section. All fields optional (partial update)."""

    section_type: Optional[AssessmentSectionTypeEnum] = None
    title: Optional[str] = None
    section_order: Optional[int] = Field(default=None, ge=1)
    marks: Optional[int] = Field(default=None, ge=0)
    settings: Optional[dict] = None


class AssessmentSectionReorderIn(BaseModel):
    """Reorder the sections of an assessment: section ids in their new order.

    Every section of the assessment must appear exactly once; duplicate ids
    are rejected here.
    """

    ordered_section_ids: List[int]

    @model_validator(mode="after")
    def _reject_duplicate_ids(self):
        if len(self.ordered_section_ids) != len(set(self.ordered_section_ids)):
            raise ValueError("ordered_section_ids must not contain duplicates")
        return self


class AssessmentAssignIn(BaseModel):
    """Assign one or more candidate users to an assessment.

    The assessment is identified by URL; only candidate *user* ids are listed.
    An empty list or duplicated ids is rejected up front so a bulk request is
    validated completely before anything is written.
    """

    candidate_ids: List[int]

    @model_validator(mode="after")
    def _reject_empty_and_duplicate_ids(self):
        if not self.candidate_ids:
            raise ValueError("candidate_ids must not be empty")
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("candidate_ids must not contain duplicates")
        return self


class AssessmentAssignmentDetailOut(BaseModel):
    """A serialized assignment enriched with candidate identity + assessment.

    Used by the company-facing assignment endpoints (assign / list / detail)
    so the company sees who was assigned what, when, and in which state,
    alongside the raw assignment timestamps.
    """

    id: int
    assessment_id: int
    candidate_id: int
    status: AssessmentAssignmentStatusEnum
    assigned_at: datetime
    started_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None
    assessment_title: Optional[str] = None


class CandidateAssessmentSectionOut(BaseModel):
    """A candidate-facing section of an assessment: the ordered stage list.

    Deliberately omits per-section ``marks`` and opaque engine ``settings``
    (JSON) — both are scoring/engine configuration that stays private until a
    section fulfilment engine is attached.
    """

    id: int
    section_type: AssessmentSectionTypeEnum
    title: str
    section_order: int


class CandidateAssessmentAssignmentOut(BaseModel):
    """One of the candidate's assigned assessments (list / status contract).

    Melds the assessment's candidate-visible details (title, description,
    instructions, company name, duration, scheduled window) with the
    candidate's own assignment state and timestamps. No company/admin
    internals (assessment lifecycle status, company id), no scoring
    configuration, and nothing belonging to other candidates.
    """

    id: int
    assessment_id: int
    title: str
    description: Optional[str] = None
    instructions: Optional[str] = None
    company_name: str
    duration_minutes: Optional[int] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    status: AssessmentAssignmentStatusEnum
    assigned_at: datetime
    started_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CandidateAssessmentAssignmentDetailOut(CandidateAssessmentAssignmentOut):
    """Full candidate-facing detail: the list contract plus the ordered
    sections of the assessment."""

    sections: List[CandidateAssessmentSectionOut] = []


class CandidateAssessmentQuestionOut(BaseModel):
    """A candidate-safe question rendered inside a started attempt.

    Deliberately omits the private evaluation data stored on the question bank:
    no ``correct_index`` (MCQ), no ``hidden_cases`` (coding), no ``marks`` or
    ``explanation`` (scoring/answer-revealing configuration). Sample cases are
    shown (they are the public examples), exactly like the existing coding
    engine does. ``question_text`` carries the statement for both types.
    """

    id: int
    question_type: AssessmentQuestionTypeEnum
    question_text: str
    question_order: int

    # MCQ (candidate-visible subset).
    options: Optional[List[str]] = None

    # Coding (candidate-visible subset).
    title: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    input_format: Optional[str] = None
    output_format: Optional[str] = None
    constraints: Optional[str] = None
    sample_cases: Optional[List[Dict[str, Any]]] = None
    time_limit_seconds: Optional[int] = None
    supported_languages: Optional[List[str]] = None


class CandidateAssessmentSectionDetailOut(BaseModel):
    """A candidate-facing section of a started attempt: the ordered stage list
    plus its questions in their configured order."""

    id: int
    section_type: AssessmentSectionTypeEnum
    title: str
    section_order: int
    questions: List[CandidateAssessmentQuestionOut] = []


class CandidateAssessmentStartOut(BaseModel):
    """The full candidate-facing content returned when an assessment starts.

    `attempt_id` is the assignment id: the existing ``assessment_assignments``
    row is the attempt/session container (status + started_at/submitted_at), so
    no separate attempt table is created. Includes everything the frontend
    needs to render the test: title/instructions, ordered sections + questions,
    duration, and start/deadline information (``started_at``, ``deadline_at`` =
    the earlier of window end and start+duration).
    """

    attempt_id: int
    assessment_id: int
    title: str
    description: Optional[str] = None
    instructions: Optional[str] = None
    company_name: str
    status: AssessmentAssignmentStatusEnum
    duration_minutes: Optional[int] = None
    started_at: datetime
    deadline_at: Optional[datetime] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    sections: List[CandidateAssessmentSectionDetailOut] = []


class AssessmentAnswerSaveIn(BaseModel):
    """Save/update the candidate's answer to one question of an attempt.

    Exactly one answer mode must be supplied:
    - MCQ/aptitude/technical questions: ``selected_option`` (0-based index).
    - Coding questions: ``language`` + ``code`` (graded server-side in the
      Docker sandbox). The correct answer is NEVER accepted from the client —
      correctness is computed server-side from the stored question.
    """

    question_id: int
    selected_option: Optional[int] = Field(default=None, ge=0)
    language: Optional[Literal["python", "java", "cpp"]] = None
    code: Optional[str] = None

    @model_validator(mode="after")
    def _validate_answer_mode(self):
        has_mcq = self.selected_option is not None
        has_coding = self.language is not None or self.code is not None
        if has_mcq and has_coding:
            raise ValueError(
                "Provide either selected_option or code+language, not both"
            )
        if not has_mcq and not has_coding:
            raise ValueError("Provide selected_option or code+language")
        if has_coding:
            if self.language is None or self.code is None:
                raise ValueError("Coding answers require both language and code")
            if not self.code.strip():
                raise ValueError("Code cannot be empty")
        return self


class AssessmentAnswerOut(BaseModel):
    """The candidate's own saved answer (candidate-safe).

    Deliberately omits every piece of private evaluation data: no
    ``is_correct`` or ``correct_index`` (MCQ), no ``hidden_cases`` / expected
    outputs. For coding, per-case ``results`` carry only case index / passed /
    status / time — like the existing coding module, never the hidden-case I/O.
    """

    question_id: int
    question_type: AssessmentQuestionTypeEnum
    selected_option: Optional[int] = None
    # Coding verdict (passed | failed | error).
    language: Optional[str] = None
    status: Optional[str] = None
    passed_cases: Optional[int] = None
    total_cases: Optional[int] = None
    score: Optional[int] = None
    execution_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    results: List[CodingTestCaseResultOut] = []
    created_at: datetime
    updated_at: datetime


class CandidateAssessmentSubmitOut(BaseModel):
    """The final state returned once an attempt is submitted (explicitly or
    by the deadline). ``answered_count`` is scoped to the candidate's own
    attempt."""

    attempt_id: int
    assessment_id: int
    status: AssessmentAssignmentStatusEnum
    submitted_at: Optional[datetime] = None
    answered_count: int = 0


# ---------------------------------------------------------------------------
# Question bank (company-only)
# ---------------------------------------------------------------------------
def validate_test_cases(
    cases: Optional[List[Dict[str, Any]]], label: str
) -> None:
    """Validate a coding test-case list: each entry is ``{"input", "expected"}``
    with string values, matching the contract consumed by ``code_executor``."""
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{label} must be a non-empty list")
    for i, case in enumerate(cases):
        if not isinstance(case, dict) or set(case.keys()) != {"input", "expected"}:
            raise ValueError(
                f"{label}[{i}] must be a dict with exactly 'input' and 'expected'"
            )
        if not isinstance(case.get("input"), str) or not isinstance(
            case.get("expected"), str
        ):
            raise ValueError(f"{label}[{i}] 'input' and 'expected' must be strings")


def validate_mcq_contract(
    options: Optional[List[str]], correct_index: Optional[int]
) -> None:
    """Validate the MCQ question contract (2+ options, in-range correct index)."""
    if not options or len(options) < 2:
        raise ValueError("MCQ questions require at least 2 options")
    if any(not isinstance(o, str) or not o.strip() for o in options):
        raise ValueError("options must be non-empty strings")
    if correct_index is None:
        raise ValueError("MCQ questions require correct_index")
    if not 0 <= correct_index < len(options):
        raise ValueError("correct_index must point to one of the options")


def validate_coding_contract(
    hidden_cases: Optional[List[Dict[str, Any]]],
    sample_cases: Optional[List[Dict[str, Any]]],
    time_limit_seconds: Optional[int],
    supported_languages: Optional[List[str]],
) -> None:
    """Validate the coding question contract (hidden grading cases, and
    optional sample cases / languages) against the existing coding engine."""
    validate_test_cases(hidden_cases, "hidden_cases")
    if sample_cases is not None:
        validate_test_cases(sample_cases, "sample_cases")
    if time_limit_seconds is not None and time_limit_seconds < 1:
        raise ValueError("time_limit_seconds must be positive")
    if supported_languages is not None:
        if not supported_languages or not all(
            lang in SUPPORTED_LANGUAGES for lang in supported_languages
        ):
            raise ValueError(
                f"supported_languages must be a subset of {SUPPORTED_LANGUAGES}"
            )


def validate_question_contract(
    question_type: AssessmentQuestionTypeEnum,
    options: Optional[List[str]] = None,
    correct_index: Optional[int] = None,
    hidden_cases: Optional[List[Dict[str, Any]]] = None,
    sample_cases: Optional[List[Dict[str, Any]]] = None,
    time_limit_seconds: Optional[int] = None,
    supported_languages: Optional[List[str]] = None,
) -> None:
    """Dispatch contract validation by question type (shared by the create
    schema and the update route's final-state check)."""
    if question_type == AssessmentQuestionTypeEnum.mcq:
        validate_mcq_contract(options, correct_index)
    else:
        validate_coding_contract(
            hidden_cases,
            sample_cases,
            time_limit_seconds,
            supported_languages,
        )


class AssessmentQuestionOut(BaseModel):
    """A serialized company question-bank entry (company/admin view only).

    Includes the private evaluation data (``correct_index``,
    ``hidden_cases``) — this contract is never used by a candidate-facing
    endpoint.
    """

    id: int
    section_id: int
    question_type: AssessmentQuestionTypeEnum
    question_text: str
    question_order: int

    options: Optional[List[str]] = None
    correct_index: Optional[int] = None
    marks: Optional[int] = None
    explanation: Optional[str] = None

    title: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    input_format: Optional[str] = None
    output_format: Optional[str] = None
    constraints: Optional[str] = None
    sample_cases: Optional[List[Dict[str, Any]]] = None
    hidden_cases: Optional[List[Dict[str, Any]]] = None
    time_limit_seconds: Optional[int] = None
    supported_languages: Optional[List[str]] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AssessmentQuestionCreate(BaseModel):
    """Create a question in an assessment section (question bank).

    ``question_type`` must match the section type (the route enforces that);
    MCQ fields (``options`` + ``correct_index``) and coding fields reuse the
    existing engines' contracts. Coding defaults mirror the coding engine:
    a 5-second per-case time limit and python/java/cpp.
    """

    question_type: AssessmentQuestionTypeEnum
    question_text: str
    question_order: Optional[int] = Field(default=None, ge=1)

    options: Optional[List[str]] = None
    correct_index: Optional[int] = Field(default=None, ge=0)
    marks: Optional[int] = Field(default=None, ge=0)
    explanation: Optional[str] = None

    title: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    input_format: Optional[str] = None
    output_format: Optional[str] = None
    constraints: Optional[str] = None
    sample_cases: Optional[List[Dict[str, Any]]] = None
    hidden_cases: Optional[List[Dict[str, Any]]] = None
    time_limit_seconds: Optional[int] = Field(default=None, ge=1)
    supported_languages: Optional[List[str]] = None

    @model_validator(mode="after")
    def _validate_question(self):
        validate_question_contract(
            self.question_type,
            options=self.options,
            correct_index=self.correct_index,
            hidden_cases=self.hidden_cases,
            sample_cases=self.sample_cases,
            time_limit_seconds=self.time_limit_seconds,
            supported_languages=self.supported_languages,
        )
        return self


class AssessmentQuestionUpdate(BaseModel):
    """Update a question-bank entry. All fields optional (partial update);
    the final row is re-validated against its question type by the route."""

    question_type: Optional[AssessmentQuestionTypeEnum] = None
    question_text: Optional[str] = None
    question_order: Optional[int] = Field(default=None, ge=1)

    options: Optional[List[str]] = None
    correct_index: Optional[int] = Field(default=None, ge=0)
    marks: Optional[int] = Field(default=None, ge=0)
    explanation: Optional[str] = None

    title: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    input_format: Optional[str] = None
    output_format: Optional[str] = None
    constraints: Optional[str] = None
    sample_cases: Optional[List[Dict[str, Any]]] = None
    hidden_cases: Optional[List[Dict[str, Any]]] = None
    time_limit_seconds: Optional[int] = Field(default=None, ge=1)
    supported_languages: Optional[List[str]] = None


class AssessmentQuestionReorderIn(BaseModel):
    """Reorder the questions of a section: question ids in their new order.

    Every question of the section must appear exactly once; duplicate ids
    are rejected here.
    """

    ordered_question_ids: List[int]

    @model_validator(mode="after")
    def _reject_duplicate_ids(self):
        if len(self.ordered_question_ids) != len(set(self.ordered_question_ids)):
            raise ValueError("ordered_question_ids must not contain duplicates")
        return self

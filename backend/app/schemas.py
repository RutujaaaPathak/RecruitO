# pyrefly: ignore [missing-import]
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Literal
from datetime import datetime, date

from app.models import (
    RoleEnum,
    JobStatusEnum,
    ApplicationStatusEnum,
    InterviewStatusEnum,
    MockInterviewStatusEnum,
    AssessmentStatusEnum,
    CodingTestStatusEnum,
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

    The camera/microphone enablement is recorded from the candidate's live
    device state at the moment the room is entered.
    """

    application_id: int
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
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    status: AssessmentStatusEnum
    camera_enabled: bool
    microphone_enabled: bool
    started_at: datetime
    ended_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class VideoInterviewDetailOut(BaseModel):
    id: int
    application_id: int
    user_id: int
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    status: AssessmentStatusEnum
    camera_enabled: bool
    microphone_enabled: bool
    max_questions: int = 0
    answered_count: int = 0
    current_question: Optional[MockInterviewQuestionOut] = None
    answered: List[AnsweredQuestionOut] = []
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

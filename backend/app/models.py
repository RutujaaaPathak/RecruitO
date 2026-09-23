# pyrefly: ignore [missing-import]
from sqlalchemy import (
    Column,
    Integer,
    String,
    Enum,
    DateTime,
    ForeignKey,
    JSON,
    Text,
    Boolean,
    Date,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from app.database import Base
import enum
from datetime import datetime

# pgvector: SQLAlchemy type for the resume-chunk embedding column. Requires the
# `pgvector` python package + the `vector` PostgreSQL extension.
from pgvector.sqlalchemy import Vector  # pyrefly: ignore [missing-import]

# Dimension of the embeddings produced by the All-MiniLM-L6-v2 model shared with
# the semantic matcher. Columns and migrations must stay in sync with this.
VECTOR_DIM = 384


# -----------------------------
# Enums
# -----------------------------
class RoleEnum(str, enum.Enum):
    user = "user"
    admin = "admin"
    company = "company"


class JobStatusEnum(str, enum.Enum):
    open = "Open"
    closed = "Closed"


class ApplicationStatusEnum(str, enum.Enum):
    applied = "applied"
    shortlisted = "shortlisted"
    interviewed = "interviewed"
    accepted = "accepted"
    rejected = "rejected"
    withdrawn = "withdrawn"


class InterviewStatusEnum(str, enum.Enum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"


class CompanyAssessmentStatusEnum(str, enum.Enum):
    """Lifecycle of a company-authored assessment (draft → published → closed)."""

    draft = "draft"
    published = "published"
    closed = "closed"


class AssessmentSectionTypeEnum(str, enum.Enum):
    """Type of a section inside a company assessment.

    Mirrors the candidate-side engines (aptitude / coding / technical video
    interview / HR) so each section can later be wired to the matching engine
    without coupling the assessment model to them.
    """

    aptitude = "aptitude"
    technical = "technical"
    coding = "coding"
    hr = "hr"
    technical_interview = "technical_interview"


class AssessmentAssignmentStatusEnum(str, enum.Enum):
    """Lifecycle of a company assessment assigned to a candidate."""

    assigned = "assigned"
    in_progress = "in_progress"
    submitted = "submitted"


class AssessmentQuestionTypeEnum(str, enum.Enum):
    """Fulfilment type of a company-assessment question (engine discriminator).

    Mirrors the fields of the existing candidate engines: MCQ covers aptitude
    and technical sections, coding covers programming sections. HR and
    technical-interview sections are interview-based and have no question
    bank entries yet.
    """

    mcq = "mcq"
    coding = "coding"


# -----------------------------
# User Table
# -----------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(
        Enum(RoleEnum, name="roleenum"),
        default=RoleEnum.user,
        nullable=False,
    )
    phone = Column(String, nullable=True)
    category = Column(String, nullable=True)
    skills = Column(JSON, nullable=True, default=list)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # One-to-one for company users
    company = relationship(
        "Company",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    resumes = relationship(
        "Resume", back_populates="user", cascade="all, delete-orphan"
    )
    applications = relationship(
        "Application", back_populates="user", cascade="all, delete-orphan"
    )
    chat_sessions = relationship(
        "ChatSession", back_populates="user", cascade="all, delete-orphan"
    )
    mock_interviews = relationship(
        "MockInterview", back_populates="user", cascade="all, delete-orphan"
    )
    mcq_assessments = relationship(
        "McqAssessment", back_populates="user", cascade="all, delete-orphan"
    )
    coding_tests = relationship(
        "CodingTest", back_populates="user", cascade="all, delete-orphan"
    )
    coding_submissions = relationship(
        "CodingSubmission", back_populates="user", cascade="all, delete-orphan"
    )
    aptitude_tests = relationship(
        "AptitudeTest", back_populates="user", cascade="all, delete-orphan"
    )
    video_interviews = relationship(
        "VideoInterview", back_populates="user", cascade="all, delete-orphan"
    )
    assessment_assignments = relationship(
        "AssessmentAssignment", back_populates="candidate", cascade="all, delete-orphan"
    )

    notifications = relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )


# -----------------------------
# Company Table
# -----------------------------
class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    # owner/user id that manages this company profile
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    name = Column(String, nullable=False)
    website = Column(String, nullable=True)
    registration_number = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    location = Column(String, nullable=True)
    size = Column(String, nullable=True)
    about = Column(Text, nullable=True)
    logo_url = Column(String, nullable=True)
    approved = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="company")
    jobs = relationship(
        "Job", back_populates="company", cascade="all, delete-orphan"
    )
    assessments = relationship(
        "Assessment", back_populates="company", cascade="all, delete-orphan"
    )


# -----------------------------
# Job Table
# -----------------------------
class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True
    )
    title = Column(String, nullable=False)
    department = Column(String, nullable=True)
    location = Column(String, nullable=True)
    type = Column(String, nullable=True)  # Full-time / Internship / Contract
    experience = Column(String, nullable=True)
    salary = Column(String, nullable=True)
    skills = Column(JSON, nullable=True, default=list)
    vacancies = Column(Integer, default=1, nullable=False)
    description = Column(Text, nullable=True)
    deadline = Column(Date, nullable=True)
    status = Column(
        Enum(JobStatusEnum, name="jobstatusenum"),
        default=JobStatusEnum.open,
        nullable=False,
    )
    posted_on = Column(DateTime, default=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="jobs")
    applications = relationship(
        "Application", back_populates="job", cascade="all, delete-orphan"
    )


# -----------------------------
# Resume Table
# -----------------------------
class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    original_filename = Column(String, nullable=False)
    stored_path = Column(String, nullable=False)
    extension = Column(String, nullable=True)
    parsed_text = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="resumes")
    chunks = relationship(
        "ResumeChunk",
        back_populates="resume",
        cascade="all, delete-orphan",
        order_by="ResumeChunk.chunk_index",
    )


# -----------------------------
# Resume chunks (RAG index)
# -----------------------------
class ResumeChunk(Base):
    """One indexed section of a parsed resume, with an embedding for retrieval.

    Populated when a resume is uploaded. `embedding` is a `VECTOR(384)` pgvector
    column (All-MiniLM-L6-v2). It is NULL when the embedding model was
    unavailable at upload time; retrieval then falls back to keyword scoring.
    """

    __tablename__ = "resume_chunks"
    __table_args__ = (
        UniqueConstraint("resume_id", "chunk_index", name="uq_resume_chunk_index"),
    )

    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(
        Integer, ForeignKey("resumes.id"), nullable=False, index=True
    )
    chunk_index = Column(Integer, nullable=False)
    section = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=True)
    embedding = Column(Vector(VECTOR_DIM), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    resume = relationship("Resume", back_populates="chunks")


# -----------------------------
# Application Table
# -----------------------------
class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("job_id", "user_id", name="uq_application_job_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    status = Column(
        Enum(ApplicationStatusEnum, name="applicationstatusenum"),
        default=ApplicationStatusEnum.applied,
        nullable=False,
    )
    match_score = Column(Integer, nullable=True)  # 0-100 placeholder
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    job = relationship("Job", back_populates="applications")
    user = relationship("User", back_populates="applications")
    interview = relationship(
        "Interview",
        back_populates="application",
        uselist=False,
        cascade="all, delete-orphan",
    )
    mock_interviews = relationship(
        "MockInterview", back_populates="application", cascade="all, delete-orphan"
    )
    mcq_assessments = relationship(
        "McqAssessment", back_populates="application", cascade="all, delete-orphan"
    )
    coding_tests = relationship(
        "CodingTest", back_populates="application", cascade="all, delete-orphan"
    )
    aptitude_tests = relationship(
        "AptitudeTest", back_populates="application", cascade="all, delete-orphan"
    )
    video_interviews = relationship(
        "VideoInterview", back_populates="application", cascade="all, delete-orphan"
    )


# -----------------------------
# Interview Table
# -----------------------------
class Interview(Base):
    __tablename__ = "interviews"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(
        Integer,
        ForeignKey("applications.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    scheduled_at = Column(DateTime, nullable=True)
    status = Column(
        Enum(InterviewStatusEnum, name="interviewstatusenum"),
        default=InterviewStatusEnum.scheduled,
        nullable=False,
    )
    notes = Column(Text, nullable=True)
    score = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    application = relationship("Application", back_populates="interview")
    job = relationship("Job")
    user = relationship("User")


# -----------------------------
# Email OTP Table
# -----------------------------
class EmailOTP(Base):
    __tablename__ = "email_otps"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)
    otp = Column(String, nullable=False)
    # Timestamp used for OTP expiry check
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# -----------------------------
# Password Reset Token Table
# -----------------------------
class PasswordResetToken(Base):
    """One short-lived, single-use password-reset token per account.

    Only a SHA-256 digest of the raw token is stored (never the token itself),
    so the raw value cannot be recovered from the database. The digest allows
    O(1) lookup on /reset-password; the raw 256-bit token is only sent to the
    user's inbox and is infeasible to brute force. Tokens expire and are
    deleted after a single successful use.
    """

    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)
    token_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# -----------------------------
# AI Chatbot: conversation sessions + messages
# -----------------------------
class ChatSession(Base):
    """One candidate chatbot conversation, anchored to an optional application.

    Stores the selected application context (`application_id`) so every turn in
    the session is grounded in the same job. A session always belongs to the
    authenticated candidate (`user_id`); ownership is enforced at the route layer.
    """

    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    application_id = Column(
        Integer, ForeignKey("applications.id"), nullable=True, index=True
    )
    title = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="chat_sessions")
    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )


class ChatMessage(Base):
    """A single persisted turn (user question or assistant reply) in a session.

    `role` is "user" or "assistant". Assistant messages carry the retrieved
    resume-chunk `sources` that grounded the reply, plus the `model_used` and
    `generated_by` (llm|fallback) metadata for transparency.
    """

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer, ForeignKey("chat_sessions.id"), nullable=False, index=True
    )
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    sources = Column(JSON, nullable=True)
    model_used = Column(String, nullable=True)
    generated_by = Column(String, nullable=True)  # "llm" | "fallback"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("ChatSession", back_populates="messages")


# -----------------------------
# AI Mock Interview: sessions + questions
# -----------------------------
class MockInterviewStatusEnum(str, enum.Enum):
    in_progress = "in_progress"
    completed = "completed"


class MockInterview(Base):
    """One text-based AI mock interview session for an application.

    Anchored to the candidate's application (and therefore its job) so every
    question is grounded in the same resume + job context. Stores the RAG
    sources and skill-gap snapshot used at start time for auditability, and the
    final report once the interview is completed.
    """

    __tablename__ = "mock_interviews"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    application_id = Column(
        Integer, ForeignKey("applications.id"), nullable=False, index=True
    )
    status = Column(
        Enum(MockInterviewStatusEnum, name="mockinterviewstatusenum"),
        default=MockInterviewStatusEnum.in_progress,
        nullable=False,
    )
    # Fixed at creation so the question count is stable across refreshes.
    max_questions = Column(Integer, default=8, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # Final report (populated when the interview is completed).
    overall_score = Column(Integer, nullable=True)  # 0-10
    category_scores = Column(JSON, nullable=True)
    strengths = Column(JSON, nullable=True)
    weaknesses = Column(JSON, nullable=True)
    recommended_topics = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    report = Column(JSON, nullable=True)  # raw validated report (audit)
    report_generated_by = Column(String, nullable=True)  # "llm" | "fallback"
    report_notice = Column(Text, nullable=True)

    # Auditability: the grounded context captured at session start.
    skill_gap = Column(JSON, nullable=True)  # {"matched": [...], "missing": [...]}
    sources = Column(JSON, nullable=True)  # retrieved resume chunks (RAG)
    model_used = Column(String, nullable=True)
    used_fallback = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="mock_interviews")
    application = relationship("Application", back_populates="mock_interviews")
    questions = relationship(
        "MockInterviewQuestion",
        back_populates="interview",
        cascade="all, delete-orphan",
        order_by="MockInterviewQuestion.question_index",
    )


class MockInterviewQuestion(Base):
    """One grounded interview question and, after answering, its evaluation.

    Shared by the text-based AI mock interview and the AI video interview
    (technical and HR modes). ``interview_id`` anchors it to a mock interview,
    ``video_interview_id`` anchors it to a video session (exactly one of the
    two is set).

    `category` is one of: technical, project_experience, problem_solving,
    behavioral (rotated by the service for technical mode) or communication,
    work_experience, motivation, behavioral (HR mode). The unanswered question
    in a session is the "current" question; resuming a session picks it up
    again.
    """

    __tablename__ = "mock_interview_questions"
    __table_args__ = (
        UniqueConstraint(
            "interview_id", "question_index", name="uq_mock_interview_question_index"
        ),
        UniqueConstraint(
            "video_interview_id",
            "question_index",
            name="uq_video_interview_question_index",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    interview_id = Column(
        Integer, ForeignKey("mock_interviews.id"), nullable=True, index=True
    )
    video_interview_id = Column(
        Integer, ForeignKey("video_interviews.id"), nullable=True, index=True
    )
    question_index = Column(Integer, nullable=False)
    category = Column(String, nullable=False)
    question_text = Column(Text, nullable=False)
    generated_by = Column(String, nullable=True)  # "llm" | "fallback"
    notice = Column(Text, nullable=True)
    question_sources = Column(JSON, nullable=True)  # RAG chunks grounding it

    # Candidate answer + AI evaluation.
    answer_text = Column(Text, nullable=True)
    score = Column(Integer, nullable=True)  # 0-10
    correctness = Column(Text, nullable=True)
    strengths = Column(JSON, nullable=True)
    weaknesses = Column(JSON, nullable=True)
    missing_points = Column(JSON, nullable=True)
    feedback = Column(Text, nullable=True)
    evaluation = Column(JSON, nullable=True)  # raw validated evaluation (audit)
    evaluation_generated_by = Column(String, nullable=True)  # "llm" | "fallback"
    evaluation_notice = Column(Text, nullable=True)
    evaluated_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    interview = relationship("MockInterview", back_populates="questions")
    video_interview = relationship("VideoInterview", back_populates="questions")


# -----------------------------
# AI MCQ Assessment: tests + questions + candidate answers
# -----------------------------
class AssessmentStatusEnum(str, enum.Enum):
    in_progress = "in_progress"
    completed = "completed"


class CodingTestStatusEnum(str, enum.Enum):
    in_progress = "in_progress"
    completed = "completed"


class McqAssessment(Base):
    """One timed, 20-question multiple-choice assessment anchored to an
    application (and therefore a job). Questions are generated per-attempt by
    the LLM (grounded in the candidate's resume + job) or by a deterministic
    fallback question bank, and persisted with their correct answer so results
    can be computed server-side at submission/expiry time.

    The candidate's selected options live in `answers`. Correct answers are
    stored on `McqQuestion.correct_option_index` but are NEVER serialized — the
    API only ever returns the four options (and the candidate's own selection).
    """

    __tablename__ = "mcq_assessments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    application_id = Column(
        Integer, ForeignKey("applications.id"), nullable=False, index=True
    )
    status = Column(
        Enum(AssessmentStatusEnum, name="assessmentstatusenum"),
        default=AssessmentStatusEnum.in_progress,
        nullable=False,
    )
    total_questions = Column(Integer, default=20, nullable=False)
    time_limit_minutes = Column(Integer, default=20, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    # True when the test was finalized automatically because the timer ran out.
    expired = Column(Boolean, default=False, nullable=False)

    # Final results (populated when the assessment is completed).
    score = Column(Integer, nullable=True)  # number of correct answers
    total_scored = Column(Integer, nullable=True)  # max possible score
    percentage = Column(Integer, nullable=True)  # 0-100
    correct_count = Column(Integer, nullable=True)
    incorrect_count = Column(Integer, nullable=True)
    unanswered_count = Column(Integer, nullable=True)
    passed = Column(Boolean, nullable=True)
    pass_percentage = Column(Integer, nullable=True)  # threshold used
    category_performance = Column(JSON, nullable=True)  # aggregate by category
    result_notice = Column(Text, nullable=True)

    # Transparency: how the questions were produced.
    generated_by = Column(String, nullable=True)  # "llm" | "mixed" | "fallback"
    model_used = Column(String, nullable=True)
    used_fallback = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="mcq_assessments")
    application = relationship("Application", back_populates="mcq_assessments")
    questions = relationship(
        "McqQuestion",
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="McqQuestion.question_index",
    )
    answers = relationship(
        "McqAnswer",
        back_populates="assessment",
        cascade="all, delete-orphan",
    )


class McqQuestion(Base):
    """One persisted MCQ question for an assessment.

    `options` holds exactly four answer strings; `correct_option_index` holds
    the single correct option. The correct index is server-side only and is
    never included in any API response.
    """

    __tablename__ = "mcq_questions"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "question_index", name="uq_mcq_question_index"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(
        Integer, ForeignKey("mcq_assessments.id"), nullable=False, index=True
    )
    question_index = Column(Integer, nullable=False)
    category = Column(String, nullable=False)
    question_text = Column(Text, nullable=False)
    options = Column(JSON, nullable=False)  # exactly 4 strings
    correct_option_index = Column(Integer, nullable=False)  # server-side only
    generated_by = Column(String, nullable=True)  # "llm" | "fallback"
    notice = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    assessment = relationship("McqAssessment", back_populates="questions")


class McqAnswer(Base):
    """The candidate's selected option for one question of one assessment.

    `(assessment_id, question_id)` is unique: an answer is an upsert, never a
    second row, so double-submissions cannot create duplicate rows.
    """

    __tablename__ = "mcq_answers"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "question_id", name="uq_mcq_answer_question"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(
        Integer, ForeignKey("mcq_assessments.id"), nullable=False, index=True
    )
    question_id = Column(
        Integer, ForeignKey("mcq_questions.id"), nullable=False, index=True
    )
    selected_option = Column(Integer, nullable=False)  # 0-3
    is_correct = Column(Boolean, nullable=False)  # snapshot at answer time
    answered_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    assessment = relationship("McqAssessment", back_populates="answers")
    question = relationship("McqQuestion")


# -----------------------------
# Coding Test: tests + problems + submissions
# -----------------------------
class CodingTest(Base):
    """One coding test session anchored to a candidate's application.

    Created from a deterministic question bank of programming problems.  Each
    problem carries sample cases (shown to the candidate) plus hidden cases
    (used only server-side for scoring — never serialized).
    """

    __tablename__ = "coding_tests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    application_id = Column(
        Integer, ForeignKey("applications.id"), nullable=False, index=True
    )
    status = Column(
        Enum(CodingTestStatusEnum, name="codingteststatusenum"),
        default=CodingTestStatusEnum.in_progress,
        nullable=False,
    )
    total_problems = Column(Integer, nullable=False)
    solved_count = Column(Integer, default=0, nullable=False)
    # Final aggregate results (populated when the test is completed).
    score = Column(Integer, nullable=True)
    passed = Column(Boolean, nullable=True)
    pass_percentage = Column(Integer, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="coding_tests")
    application = relationship("Application", back_populates="coding_tests")
    problems = relationship(
        "CodingProblem",
        back_populates="test",
        cascade="all, delete-orphan",
        order_by="CodingProblem.problem_index",
    )
    submissions = relationship(
        "CodingSubmission",
        back_populates="test",
        cascade="all, delete-orphan",
    )


class CodingProblem(Base):
    """One programming problem for a coding test.

    ``sample_cases`` are shown to the candidate; ``hidden_cases`` are the
    grading tests, stored server-side and NEVER serialized.
    """

    __tablename__ = "coding_problems"
    __table_args__ = (
        UniqueConstraint(
            "coding_test_id", "problem_index", name="uq_coding_problem_index"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    coding_test_id = Column(
        Integer, ForeignKey("coding_tests.id"), nullable=False, index=True
    )
    problem_index = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    category = Column(String, nullable=False)
    difficulty = Column(String, nullable=False)  # easy | medium | hard
    description = Column(Text, nullable=False)
    input_format = Column(Text, nullable=False)
    output_format = Column(Text, nullable=False)
    constraints = Column(Text, nullable=False)
    sample_cases = Column(JSON, nullable=False)  # [{"input", "expected"}]
    hidden_cases = Column(JSON, nullable=False)  # server-side only
    time_limit_seconds = Column(Integer, default=5, nullable=False)
    supported_languages = Column(
        JSON, nullable=False, default=["python", "java", "cpp"]
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    test = relationship("CodingTest", back_populates="problems")
    submissions = relationship(
        "CodingSubmission", back_populates="problem", cascade="all, delete-orphan"
    )


class CodingSubmission(Base):
    """The candidate's latest code + grading result for one problem.

    ``(coding_test_id, problem_id)`` is unique: a submit overwrites the
    previous submission for that problem rather than creating a duplicate row.
    """

    __tablename__ = "coding_submissions"
    __table_args__ = (
        UniqueConstraint(
            "coding_test_id", "problem_id", name="uq_coding_submission_problem"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    coding_test_id = Column(
        Integer, ForeignKey("coding_tests.id"), nullable=False, index=True
    )
    problem_id = Column(
        Integer, ForeignKey("coding_problems.id"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    language = Column(String, nullable=False)  # python | java | cpp
    code = Column(Text, nullable=False)
    status = Column(String, nullable=False)  # passed | failed | error | timeout
    passed_cases = Column(Integer, nullable=False)
    total_cases = Column(Integer, nullable=False)
    score = Column(Integer, nullable=False)  # 0-100
    execution_time_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    results = Column(JSON, nullable=True)  # per-case pass/fail detail
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    test = relationship("CodingTest", back_populates="submissions")
    problem = relationship("CodingProblem", back_populates="submissions")
    user = relationship("User", back_populates="coding_submissions")


# -----------------------------
# Aptitude Test: tests + questions + answers
# -----------------------------
class AptitudeTest(Base):
    """One timed, 20-question aptitude test anchored to a candidate's
    application (and therefore a job). Questions span three fixed sections —
    quantitative, logical reasoning and verbal — and are generated per-attempt
    by the LLM (grounded in the candidate's resume + job) or by a deterministic
    fallback question bank. The correct answer is persisted server-side only.

    Reuses AssessmentStatusEnum (in_progress | completed) so the shared
    PostgreSQL enum type stays a single source of truth across assessments.
    """

    __tablename__ = "aptitude_tests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    application_id = Column(
        Integer, ForeignKey("applications.id"), nullable=False, index=True
    )
    status = Column(
        Enum(AssessmentStatusEnum, name="assessmentstatusenum"),
        default=AssessmentStatusEnum.in_progress,
        nullable=False,
    )
    total_questions = Column(Integer, default=20, nullable=False)
    time_limit_minutes = Column(Integer, default=20, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    # True when the test was finalized automatically because the timer ran out.
    expired = Column(Boolean, default=False, nullable=False)

    # Final results (populated when the test is completed).
    score = Column(Integer, nullable=True)  # number of correct answers
    total_scored = Column(Integer, nullable=True)  # max possible score
    percentage = Column(Integer, nullable=True)  # 0-100
    correct_count = Column(Integer, nullable=True)
    incorrect_count = Column(Integer, nullable=True)
    unanswered_count = Column(Integer, nullable=True)
    passed = Column(Boolean, nullable=True)
    pass_percentage = Column(Integer, nullable=True)  # threshold used
    category_performance = Column(JSON, nullable=True)  # aggregate by category
    result_notice = Column(Text, nullable=True)

    # Transparency: how the questions were produced.
    generated_by = Column(String, nullable=True)  # "llm" | "mixed" | "fallback"
    model_used = Column(String, nullable=True)
    used_fallback = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="aptitude_tests")
    application = relationship("Application", back_populates="aptitude_tests")
    questions = relationship(
        "AptitudeQuestion",
        back_populates="test",
        cascade="all, delete-orphan",
        order_by="AptitudeQuestion.question_index",
    )
    answers = relationship(
        "AptitudeAnswer",
        back_populates="test",
        cascade="all, delete-orphan",
    )


class AptitudeQuestion(Base):
    """One persisted aptitude MCQ question for a test.

    ``options`` holds exactly four answer strings; ``correct_option_index``
    holds the single correct option. The correct index is server-side only and
    is never included in any API response.
    """

    __tablename__ = "aptitude_questions"
    __table_args__ = (
        UniqueConstraint(
            "aptitude_test_id", "question_index", name="uq_aptitude_question_index"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    aptitude_test_id = Column(
        Integer, ForeignKey("aptitude_tests.id"), nullable=False, index=True
    )
    question_index = Column(Integer, nullable=False)
    category = Column(String, nullable=False)  # quantitative|logical_reasoning|verbal
    question_text = Column(Text, nullable=False)
    options = Column(JSON, nullable=False)  # exactly 4 strings
    correct_option_index = Column(Integer, nullable=False)  # server-side only
    generated_by = Column(String, nullable=True)  # "llm" | "fallback"
    notice = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    test = relationship("AptitudeTest", back_populates="questions")
    answers = relationship(
        "AptitudeAnswer", back_populates="question", cascade="all, delete-orphan"
    )


class AptitudeAnswer(Base):
    """The candidate's selected option for one question of one test.

    ``(aptitude_test_id, question_id)`` is unique: an answer is an upsert, never
    a second row, so double-submissions cannot create duplicate rows.
    """

    __tablename__ = "aptitude_answers"
    __table_args__ = (
        UniqueConstraint(
            "aptitude_test_id", "question_id", name="uq_aptitude_answer_question"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    aptitude_test_id = Column(
        Integer, ForeignKey("aptitude_tests.id"), nullable=False, index=True
    )
    question_id = Column(
        Integer, ForeignKey("aptitude_questions.id"), nullable=False, index=True
    )
    selected_option = Column(Integer, nullable=False)  # 0-3
    is_correct = Column(Boolean, nullable=False)  # snapshot at answer time
    answered_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    test = relationship("AptitudeTest", back_populates="answers")
    question = relationship("AptitudeQuestion", back_populates="answers")


# -----------------------------
# Technical Video Interview: a candidate's live interview session
# -----------------------------
class VideoInterview(Base):
    """A live AI video interview session anchored to one of the candidate's
    applications.

    ``interview_type`` discriminates the interview flavour: ``"technical"``
    (technical, project, problem-solving, behavioral questions) or ``"hr"``
    (communication, work-history, motivation, behavioral questions). The room
    persists camera + microphone enablement and the session start/end
    timestamps so an interrupted session can be resumed. The live questions,
    candidate answers and AI evaluations are stored on the shared
    ``mock_interview_questions`` table via ``video_interview_id``.

    ``interview_type`` is plain text (not an enum) so the shared question +
    engine config stays free-form; the report columns below mirror the
    text-based MockInterview report so both interview flavours can produce a
    final report at completion.

    Reuses AssessmentStatusEnum (in_progress | completed) so the shared
    PostgreSQL enum type stays a single source of truth across assessments.
    """

    __tablename__ = "video_interviews"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    application_id = Column(
        Integer, ForeignKey("applications.id"), nullable=False, index=True
    )
    status = Column(
        Enum(AssessmentStatusEnum, name="assessmentstatusenum"),
        default=AssessmentStatusEnum.in_progress,
        nullable=False,
    )
    interview_type = Column(String(20), default="technical", nullable=False)
    camera_enabled = Column(Boolean, default=True, nullable=False)
    microphone_enabled = Column(Boolean, default=True, nullable=False)

    # Final report (populated when the session is completed).
    overall_score = Column(Integer, nullable=True)  # 0-10
    category_scores = Column(JSON, nullable=True)
    strengths = Column(JSON, nullable=True)
    weaknesses = Column(JSON, nullable=True)
    recommended_topics = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    report = Column(JSON, nullable=True)  # raw validated report (audit)
    report_generated_by = Column(String, nullable=True)  # "llm" | "fallback"
    report_notice = Column(Text, nullable=True)

    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user = relationship("User", back_populates="video_interviews")
    application = relationship("Application", back_populates="video_interviews")
    questions = relationship(
        "MockInterviewQuestion",
        back_populates="video_interview",
        cascade="all, delete-orphan",
        order_by="MockInterviewQuestion.question_index",
    )


# -----------------------------
# Notifications
# -----------------------------
class NotificationType(str, enum.Enum):
    application = "application"
    interview = "interview"
    assessment = "assessment"
    system = "system"


class Notification(Base):
    """A persistent in-app notification delivered to a single user.

    Created when an important event happens (new application, interview
    scheduled/completed/cancelled, company approval, ...) and consumed via the
    /notifications endpoints. Always scoped to ``user_id``: every read/mutation
    is filtered by the current user so one account can never see another's.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # Fast unread-listing / unread-count for a user's inbox.
        Index("ix_notifications_user_read", "user_id", "read"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    type = Column(
        Enum(NotificationType, name="notificationtypeenum"),
        nullable=False,
    )
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    link = Column(String, nullable=True)
    read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="notifications")


# -----------------------------
# Company Assessments (recruitment pipeline)
# -----------------------------
class Assessment(Base):
    """A company-authored assessment for screening candidates.

    This is the *catalog* / assignment layer of the recruitment pipeline. A
    company publishes an assessment (title, instructions, validity window,
    total duration) made of ordered sections (aptitude / technical / coding /
    HR / technical interview) and then assigns it to candidate users. It is
    deliberately kept separate from the Mock Practice subsystem (aptitude /
    coding / video interview): there is no question bank, attempt, answer,
    scoring or report here — sections simply *reference* a section type that a
    future engine can fulfil.

    Lifecycle/status is company-facing (draft → published → closed) and lives
    in its own enum intentionally: it is not the candidate-facing
    ``AssessmentStatusEnum`` (in_progress/completed) reused by video
    interviews and mcq/video mock practice.
    """

    __tablename__ = "assessments"
    __table_args__ = (
        # Fast per-company listing + draft/active counting, plus a cheap
        # status-filtered scan inside one company.
        Index(
            "ix_assessments_company_status", "company_id", "status"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True
    )
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    instructions = Column(Text, nullable=True)
    status = Column(
        Enum(CompanyAssessmentStatusEnum, name="companyassessmentstatusenum"),
        default=CompanyAssessmentStatusEnum.draft,
        nullable=False,
    )
    duration_minutes = Column(Integer, nullable=True)
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    company = relationship("Company", back_populates="assessments")
    sections = relationship(
        "AssessmentSection",
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="AssessmentSection.section_order",
    )
    assignments = relationship(
        "AssessmentAssignment",
        back_populates="assessment",
        cascade="all, delete-orphan",
    )


class AssessmentSection(Base):
    """One ordered section of a company assessment.

    A section *describes* a stage of the assessment (aptitude, technical,
    coding, HR, or technical interview) together with its ordinal position and,
    optionally, the marks it carries and per-section JSON settings. ``section_type``
    is a discriminator only — no questions/attempts/answers live here; a future
    engine keyed on the section type owns those. ``section_order`` is unique per
    assessment (`uq_assessment_section_order`) so sections cannot collide on
    position.
    """

    __tablename__ = "assessment_sections"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "section_order", name="uq_assessment_section_order"
        ),
        # Ordered section scan for one assessment.
        Index(
            "ix_assessment_sections_assessment_order",
            "assessment_id",
            "section_order",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(
        Integer, ForeignKey("assessments.id"), nullable=False, index=True
    )
    section_type = Column(
        Enum(AssessmentSectionTypeEnum, name="assessmentsectiontypeenum"),
        nullable=False,
    )
    title = Column(String, nullable=False)
    section_order = Column(Integer, nullable=False)
    marks = Column(Integer, nullable=True)
    settings = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    assessment = relationship("Assessment", back_populates="sections")
    questions = relationship(
        "AssessmentQuestion",
        back_populates="section",
        cascade="all, delete-orphan",
        order_by="AssessmentQuestion.question_order",
    )


class AssessmentAssignment(Base):
    """Assignment of a published company assessment to a candidate user.

    ``(assessment_id, candidate_id)`` is unique (`uq_assessment_assignment_candidate`)
    so the same assessment can never be handed to the same candidate twice —
    duplicate assignments are rejected at the database level. Status is
    candidate-facing across the assignment lifecycle (assigned → in_progress →
    submitted); ``submitted`` captures completion without borrowing the
    in_progress/completed semantics of the shared attempt-status enum.
    """

    __tablename__ = "assessment_assignments"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id",
            "candidate_id",
            name="uq_assessment_assignment_candidate",
        ),
        # Per-candidate inbox scan + per-candidate status filter.
        Index(
            "ix_assessment_assignments_candidate_status",
            "candidate_id",
            "status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(
        Integer, ForeignKey("assessments.id"), nullable=False, index=True
    )
    candidate_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    status = Column(
        Enum(AssessmentAssignmentStatusEnum, name="assessmentassignmentstatusenum"),
        default=AssessmentAssignmentStatusEnum.assigned,
        nullable=False,
    )
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    assessment = relationship("Assessment", back_populates="assignments")
    candidate = relationship("User", back_populates="assessment_assignments")
    answers = relationship(
        "AssessmentAnswer",
        back_populates="assignment",
        cascade="all, delete-orphan",
    )


class AssessmentAnswer(Base):
    """The candidate's latest answer to one question of one assessment attempt.

    The attempt is the ``AssessmentAssignment`` row itself: an answer always
    belongs to exactly one (assignment, question) pair, and the pair is unique
    (`uq_assessment_answer_question`) so saving is an upsert — a second save for
    the same question overwrites the latest answer, never a duplicate row.

    ``question_type`` discriminates which side of the row is used: MCQ answers
    set ``selected_option`` (+ the server-computed ``is_correct`` snapshot,
    never serialized); coding answers set ``language``/``code`` plus the grading
    verdict from the shared Docker sandbox (``status``/``passed_cases``/...
    and per-case ``results`` carrying only case index/pass/status/time — never
    hidden-case I/O or expected output).
    """

    __tablename__ = "assessment_answers"
    __table_args__ = (
        # One latest answer per (attempt, question) — idempotent upsert.
        UniqueConstraint(
            "assignment_id", "question_id", name="uq_assessment_answer_question"
        ),
        # This-attempt scan + guard against cross-assessment answers.
        Index(
            "ix_assessment_answers_assignment_question",
            "assignment_id",
            "question_id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(
        Integer,
        ForeignKey("assessment_assignments.id"),
        nullable=False,
        index=True,
    )
    question_id = Column(
        Integer,
        ForeignKey("assessment_questions.id"),
        nullable=False,
        index=True,
    )

    # MCQ answer (server-side only: correctness is never serialized).
    selected_option = Column(Integer, nullable=True)  # 0-based option index
    is_correct = Column(Boolean, nullable=True)  # snapshot at answer time

    # Coding answer + grading verdict (from the Docker sandbox).
    language = Column(String, nullable=True)  # python | java | cpp
    code = Column(Text, nullable=True)
    status = Column(String, nullable=True)  # passed | failed | error
    passed_cases = Column(Integer, nullable=True)
    total_cases = Column(Integer, nullable=True)
    score = Column(Integer, nullable=True)  # 0-100
    execution_time_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    results = Column(JSON, nullable=True)  # [{case_index, passed, status, time_ms}]

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    assignment = relationship("AssessmentAssignment", back_populates="answers")
    question = relationship("AssessmentQuestion", back_populates="answers")


class AssessmentQuestion(Base):
    """One company-authored question belonging to an assessment section.

    ``question_type`` discriminates the fulfilment engine (mirroring the
    section types): MCQ questions carry ``options`` + ``correct_index`` (the
    single correct option — server-side only, never serialized to candidates)
    exactly like ``McqQuestion``; coding questions carry the same contracts as
    ``CodingProblem`` (``sample_cases`` shown to candidates, ``hidden_cases``
    grading tests used only server-side). ``description``-style statements map
    to the shared ``question_text`` column.

    ``(section_id, question_order)`` is unique so questions cannot collide on
    position. This is the *bank* layer — answers, submissions and scoring
    deliberately live elsewhere.
    """

    __tablename__ = "assessment_questions"
    __table_args__ = (
        # Fast ordered scan inside one section + order-collision guard.
        UniqueConstraint(
            "section_id", "question_order", name="uq_assessment_question_order"
        ),
        Index(
            "ix_assessment_questions_section_order",
            "section_id",
            "question_order",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    section_id = Column(
        Integer, ForeignKey("assessment_sections.id"), nullable=False, index=True
    )
    question_type = Column(
        Enum(AssessmentQuestionTypeEnum, name="assessmentquestiontypeenum"),
        nullable=False,
    )
    question_text = Column(Text, nullable=False)
    question_order = Column(Integer, nullable=False)

    # MCQ contracts (mirrors McqQuestion).
    options = Column(JSON, nullable=True)  # list of answer strings (>= 2)
    correct_index = Column(Integer, nullable=True)  # server-side only
    marks = Column(Integer, nullable=True)
    explanation = Column(Text, nullable=True)

    # Coding contracts (mirrors CodingProblem).
    title = Column(String, nullable=True)
    category = Column(String, nullable=True)
    difficulty = Column(String, nullable=True)
    input_format = Column(Text, nullable=True)
    output_format = Column(Text, nullable=True)
    constraints = Column(Text, nullable=True)
    sample_cases = Column(JSON, nullable=True)  # [{"input", "expected"}]
    hidden_cases = Column(JSON, nullable=True)  # server-side only
    time_limit_seconds = Column(Integer, nullable=True)
    supported_languages = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    section = relationship("AssessmentSection", back_populates="questions")
    answers = relationship(
        "AssessmentAnswer",
        back_populates="question",
        cascade="all, delete-orphan",
    )

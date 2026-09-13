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

    `category` is one of: technical, project_experience, problem_solving,
    behavioral (rotated by the service). The unanswered question in a session
    is the "current" question; resuming a session picks it up again.
    """

    __tablename__ = "mock_interview_questions"
    __table_args__ = (
        UniqueConstraint(
            "interview_id", "question_index", name="uq_mock_interview_question_index"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    interview_id = Column(
        Integer, ForeignKey("mock_interviews.id"), nullable=False, index=True
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

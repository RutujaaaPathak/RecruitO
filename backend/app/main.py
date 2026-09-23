# pyrefly: ignore [missing-import]
from fastapi import FastAPI
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
import logging

# Load environment variables before importing any module that reads them,
# anchored to the project root so it works regardless of the working directory.
from app.config import load_env, cors_origins

load_env()

from app.database import engine
from app import models
from app.routes import (
    auth_routes,
    companies,
    jobs,
    applications,
    interviews,
    profile,
    admin,
    chat,
    mock_interviews,
    mcq_assessments,
    coding_tests,
    aptitude_tests,
    video_interviews,
    notifications,
    company_assessments,
    candidate_assessments,
    candidate_assessment_start,
    candidate_assessment_answer,
    company_assessment_questions,
    company_assessment_results,
)

from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-20s  %(levelname)-7s  %(message)s",
)
logging.getLogger("recruito").setLevel(logging.INFO)

# Ensure the pgvector extension exists before bootstrap create_all so the
# VECTOR columns on `resume_chunks` can be created. Idempotent; migrations
# (`0002_resume_chunks`) also create it for deployed environments.
with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    conn.commit()

# Create tables (idempotent bootstrap). Prefer Alembic migrations for schema
# changes; this ensures a fresh checkout can start in development.
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# Enable CORS (VERY IMPORTANT for frontend connection)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(auth_routes.router)
app.include_router(companies.router)
app.include_router(jobs.router)
app.include_router(applications.router)
app.include_router(interviews.router)
app.include_router(profile.router)
app.include_router(chat.router)
app.include_router(mock_interviews.router)
app.include_router(mcq_assessments.router)
app.include_router(coding_tests.router)
app.include_router(aptitude_tests.router)
app.include_router(video_interviews.router)
app.include_router(admin.router)
app.include_router(notifications.router)
app.include_router(company_assessments.router)
app.include_router(company_assessment_questions.router)
app.include_router(candidate_assessments.router)
app.include_router(candidate_assessment_start.router)
app.include_router(candidate_assessment_answer.router)
app.include_router(company_assessment_results.router)

@app.get("/")
def read_root():
    return {"message": "RecruitO backend running"}
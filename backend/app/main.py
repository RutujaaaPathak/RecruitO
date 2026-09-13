# pyrefly: ignore [missing-import]
from fastapi import FastAPI
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
import logging

# Load environment variables before importing any module that reads them,
# anchored to the project root so it works regardless of the working directory.
from app.config import load_env

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
    allow_origins=["http://localhost:5173"],  # React Vite default
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
app.include_router(admin.router)

@app.get("/")
def read_root():
    return {"message": "RecruitO backend running"}
"""Tests: RAG integration in career recommendations (sources, context, fallback)."""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.career_recommendations import (  # noqa: E402
    build_prompt,
    generate_career_recommendations,
)
from app.services.resume_retriever import build_source, RetrievedChunk  # noqa: E402
from app.schemas import CareerRecommendationsOut, ChunkSource  # noqa: E402

RESUME = "Python developer with Django and PostgreSQL, building REST APIs deployed with Docker."
SKILLS = ["python", "django", "aws", "kubernetes"]
JD = "Backend engineer. Requires Python, Django, AWS and Kubernetes experience."

RETRIEVED = [
    RetrievedChunk(chunk_id=11, chunk_index=0, section="experience", score=88,
                   content="Built Django REST APIs on AWS with PostgreSQL."),
    RetrievedChunk(chunk_id=12, chunk_index=1, section="skills", score=55,
                   content="Su seguridad de Docker and CI/CD tooling."),
]


def bump_payload(plan):
    return {
        k: v for k, v in plan.items()
        if k in {"matched_skills", "missing_skills", "summary", "priority_skills",
                 "learning_path", "project_ideas", "resume_improvements"}
    }


# ---------------------------------------------------------------------------
# Prompt building with retrieved context
# ---------------------------------------------------------------------------

def test_build_prompt_omits_retrieved_section_when_absent():
    prompt = build_prompt(RESUME, "Backend Engineer", SKILLS, JD, ["python"], ["aws"],
                          ats_score=62, semantic_score=71)
    assert "RETRIEVED RESUME SECTIONS" not in prompt
    assert "62" in prompt


def test_build_prompt_includes_retrieved_context_when_provided():
    context = "\n\n".join(
        f"--- Resume section: {c.section} ---\n{c.content}" for c in RETRIEVED
    )
    prompt = build_prompt(RESUME, "Backend Engineer", SKILLS, JD, ["python"], ["aws"],
                          ats_score=62, semantic_score=71,
                          retrieved_resume_context=context)
    assert "RETRIEVED RESUME SECTIONS" in prompt
    assert "Built Django REST APIs on AWS" in prompt


# ---------------------------------------------------------------------------
# Sources plumbing
# ---------------------------------------------------------------------------

def test_sources_serialize_through_response_schema():
    plan = generate_career_recommendations(
        RESUME, SKILLS, JD, "Backend Engineer", retrieved_chunks=RETRIEVED,
        llm_call=lambda prompt, system=None: {
            "summary": "Focus on cloud.",
            "priority_skills": [],
            "learning_path": [],
            "project_ideas": [],
            "resume_improvements": [],
        },
    )
    assert plan["generated_by"] == "llm"
    assert len(plan["sources"]) == 2
    out = CareerRecommendationsOut(
        application_id=1, job_id=2, **bump_payload(plan),
        generated_by=plan["generated_by"], sources=[ChunkSource(**s) for s in plan["sources"]],
    )
    assert out.sources[0].chunk_id == 11
    assert out.sources[0].section == "experience"
    assert out.sources[0].score == 88


def test_sources_empty_by_default():
    plan = generate_career_recommendations(
        RESUME, SKILLS, JD, "Backend Engineer",
        llm_call=lambda prompt, system=None: {"summary": "s", "priority_skills": [], "learning_path": [], "project_ideas": [], "resume_improvements": []},
    )
    assert plan["sources"] == []


# ---------------------------------------------------------------------------
# Fallback behavior preserved
# ---------------------------------------------------------------------------

def test_rag_fallback_still_returns_sources_on_llm_failure():
    def broken_llm(prompt, system=None):
        raise RuntimeError("llm down")

    plan = generate_career_recommendations(
        RESUME, SKILLS, JD, "Backend Engineer", 62, 71,
        retrieved_chunks=RETRIEVED, llm_call=broken_llm,
    )
    assert plan["generated_by"] == "fallback"
    assert "llm down" in plan["notice"]
    assert plan["missing_skills"] == ["aws", "kubernetes"]
    # sources KEY remains structured even though the LLM path failed
    assert len(plan["sources"]) == 2
    assert plan["sources"][0]["chunk_id"] == 11


def test_rag_respects_build_source_truncation():
    long = RetrievedChunk(chunk_id=99, chunk_index=0, section="general",
                          score=10, content="x" * 5000)
    src = build_source(long)
    assert len(src["content"]) <= 2000
    assert src["chunk_id"] == 99


def test_existing_no_rag_signature_still_works():
    # Original call signature (no retrieved_chunks) returns a valid plan.
    plan = generate_career_recommendations(RESUME, SKILLS, JD, "Backend Engineer")
    out = CareerRecommendationsOut(
        application_id=1, job_id=2, **bump_payload(plan),
        generated_by=plan["generated_by"],
    )
    assert out.generated_by in {"llm", "fallback"}
    assert out.sources == []
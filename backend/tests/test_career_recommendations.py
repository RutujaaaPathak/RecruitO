"""Unit tests for the LLM client and AI career recommendations service."""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services import llm_client  # noqa: E402
from app.services.career_recommendations import (  # noqa: E402
    FALLBACK_NOTICE,
    build_fallback_recommendations,
    build_prompt,
    generate_career_recommendations,
    parse_llm_recommendations,
)
from app.schemas import CareerRecommendationsOut  # noqa: E402

RESUME = (
    "Python developer with Django and PostgreSQL, building REST APIs "
    "deployed with Docker."
)
SKILLS = ["python", "django", "aws", "kubernetes"]
JD = "Backend engineer. Requires Python, Django, AWS and Kubernetes experience."


# ---------------------------------------------------------------------------
# LLM client: config & JSON extraction
# ---------------------------------------------------------------------------

def test_extract_json_plain(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert llm_client._extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_markdown_fence(monkeypatch):
    assert llm_client._extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_prose_wrapped():
    assert llm_client._extract_json('Here you go: {"b": 2} thanks') == {"b": 2}


def test_extract_json_invalid_raises():
    with pytest.raises(llm_client.LLMError):
        llm_client._extract_json("not json at all")


def test_generate_json_no_key_raises_not_configured(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(llm_client.LLMNotConfigured):
        llm_client.generate_json("hello")


def test_generate_json_http_error_raises_llm_error(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    class FakeResp:
        status_code = 401
        text = "unauthorized"

        def raise_for_status(self):
            from httpx import HTTPStatusError, Request

            raise HTTPStatusError(
                "401 Unauthorized",
                request=Request("POST", "http://x"),
                response=self,
            )

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResp()

    monkeypatch.setattr(llm_client.httpx, "Client", lambda **kw: FakeClient())
    with pytest.raises(llm_client.LLMError):
        llm_client.generate_json("hello")


def test_generate_json_success_path(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

        @property
        def text(self):
            return ""

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResp()

    monkeypatch.setattr(llm_client.httpx, "Client", lambda **kw: FakeClient())
    assert llm_client.generate_json("hello") == {"ok": True}


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def test_build_prompt_includes_context():
    prompt = build_prompt(
        resume_text=RESUME,
        job_title="Backend Engineer",
        job_skills=SKILLS,
        job_description=JD,
        matched_skills=["python", "django"],
        missing_skills=["aws", "kubernetes"],
        ats_score=62,
        semantic_score=71,
    )
    assert "Backend Engineer" in prompt
    assert "python" in prompt
    assert "aws, kubernetes" in prompt
    assert "62" in prompt and "71" in prompt


# ---------------------------------------------------------------------------
# Lenient parse of LLM output
# ---------------------------------------------------------------------------

def test_parse_llm_recommendations_handles_strings_and_objects():
    data = {
        "summary": "Focus on cloud.",
        "priority_skills": ["react", {"skill": "node", "reason": "x", "priority": "CRAZY"}],
        "learning_path": ["learn React", {"step": "build app", "detail": "d"}],
        "project_ideas": ["idea one", {"title": "t", "description": "desc"}],
        "resume_improvements": ["a", "", "b"],
        "unknown_extra": 123,
    }
    plan = parse_llm_recommendations(data)
    assert plan["summary"] == "Focus on cloud."
    assert plan["priority_skills"] == [
        {"skill": "react", "reason": "", "priority": "medium"},
        {"skill": "node", "reason": "x", "priority": "medium"},
    ]
    assert plan["resume_improvements"] == ["a", "b"]
    assert plan["project_ideas"][0]["title"] == "idea one"


def test_parse_llm_recommendations_non_dict():
    plan = parse_llm_recommendations("nope")
    assert plan["priority_skills"] == []
    assert plan["summary"] == ""


# ---------------------------------------------------------------------------
# Fallback builder
# ---------------------------------------------------------------------------

def test_fallback_prioritizes_missing_skills():
    plan = build_fallback_recommendations(["python"], ["aws", "kubernetes"], 62, 71)
    assert [p["skill"] for p in plan["priority_skills"]] == ["aws", "kubernetes"]
    assert all(p["priority"] == "high" for p in plan["priority_skills"])
    assert len(plan["learning_path"]) >= 2
    assert len(plan["project_ideas"]) >= 1
    assert len(plan["resume_improvements"]) >= 3
    assert "62%" in plan["summary"] and "71%" in plan["summary"]


def test_fallback_when_no_gaps():
    plan = build_fallback_recommendations(["python", "django"], [], None, None)
    assert plan["priority_skills"] == []
    assert "already cover every required skill" in plan["summary"]


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

def test_service_llm_path_success():
    def fake_llm(prompt, system=None):
        return {
            "summary": "Cloud focus needed.",
            "priority_skills": [{"skill": "AWS", "reason": "r", "priority": "high"}],
            "learning_path": [{"step": "Learn AWS", "detail": "do tutorial"}],
            "project_ideas": [{"title": "Deploy app", "description": "on AWS"}],
            "resume_improvements": ["Quantify impact"],
        }

    plan = generate_career_recommendations(
        RESUME, SKILLS, JD, "Backend Engineer", 62, 71, llm_call=fake_llm
    )
    assert plan["generated_by"] == "llm"
    assert plan["notice"] is None
    assert plan["matched_skills"] == ["python", "django"]
    assert plan["missing_skills"] == ["aws", "kubernetes"]
    # Must serialize through the Pydantic response model.
    out = CareerRecommendationsOut(
        application_id=1, job_id=2, matched_skills=plan["matched_skills"],
        missing_skills=plan["missing_skills"], summary=plan["summary"],
        priority_skills=plan["priority_skills"], learning_path=plan["learning_path"],
        project_ideas=plan["project_ideas"],
        resume_improvements=plan["resume_improvements"],
        generated_by=plan["generated_by"],
    )
    assert out.generated_by == "llm"
    assert out.priority_skills[0].skill == "AWS"


def test_service_falls_back_on_llm_error():
    def broken_llm(prompt, system=None):
        raise RuntimeError("connection refused")

    plan = generate_career_recommendations(
        RESUME, SKILLS, JD, "Backend Engineer", 62, 71, llm_call=broken_llm
    )
    assert plan["generated_by"] == "fallback"
    assert "connection refused" in plan["notice"]
    assert FALLBACK_NOTICE in plan["notice"]
    assert plan["missing_skills"] == ["aws", "kubernetes"]


def test_service_falls_back_on_empty_llm_output():
    def empty_llm(prompt, system=None):
        return {"summary": "", "priority_skills": [], "learning_path": [], "project_ideas": [], "resume_improvements": []}

    plan = generate_career_recommendations(
        RESUME, SKILLS, JD, "Backend Engineer", llm_call=empty_llm
    )
    assert plan["generated_by"] == "fallback"
    assert plan["missing_skills"] == ["aws", "kubernetes"]


def test_service_default_llm_unconfigured_uses_fallback(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    plan = generate_career_recommendations(
        RESUME, SKILLS, JD, "Backend Engineer", 62, 71
    )
    assert plan["generated_by"] == "fallback"
    assert "LLM_API_KEY" in plan["notice"]


def test_service_plan_is_always_serializable():
    plan = generate_career_recommendations(RESUME, SKILLS, JD, "Backend Engineer")
    out = CareerRecommendationsOut(
        application_id=1, job_id=2, **{
            k: v for k, v in plan.items()
            if k in {"matched_skills", "missing_skills", "summary", "priority_skills",
                     "learning_path", "project_ideas", "resume_improvements"}
        },
        generated_by=plan["generated_by"],
    )
    payload = out.model_dump()
    assert isinstance(payload["priority_skills"], list)
    assert payload["generated_by"] in {"llm", "fallback"}
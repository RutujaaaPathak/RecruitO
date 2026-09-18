"""Tests for the AI Mock Interview (Phase 1): context/prompt building, adaptive
question generation, evaluation, final report, fallbacks, persistence helpers,
and RBAC (hermetic — no DB / API).
"""
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.auth import RoleChecker  # noqa: E402
from app.models import (  # noqa: E402
    MockInterview,
    MockInterviewQuestion,
    MockInterviewStatusEnum,
    RoleEnum,
    User,
)
from app.routes.mock_interviews import (  # noqa: E402
    _detail,
    _evaluation_out,
    _owned_interview,
    _question_out,
)
from app.services.mock_interview import (  # noqa: E402
    CATEGORIES,
    DEFAULT_MAX_QUESTIONS,
    EVALUATION_SYSTEM_PROMPT,
    FALLBACK_NOTICE,
    HR_CATEGORIES,
    HR_EVALUATION_SYSTEM_PROMPT,
    HR_QUESTION_SYSTEM_PROMPT,
    HR_REPORT_SYSTEM_PROMPT,
    QUESTION_SYSTEM_PROMPT,
    REPORT_SYSTEM_PROMPT,
    apply_evaluation,
    apply_report,
    build_context_section,
    build_evaluation_prompt,
    build_qa_pairs,
    build_question_prompt,
    build_question_row,
    build_report_prompt,
    category_for_index,
    evaluate_answer,
    fallback_evaluation,
    fallback_question,
    fallback_report,
    generate_question,
    generate_report,
    interview_categories,
    max_questions,
    parse_evaluation_json,
    parse_question_json,
    parse_report_json,
)

RESUME = (
    "Sara Chen. Python developer with Django, PostgreSQL and Docker experience. "
    "Built REST APIs on AWS and deployed microservices."
)
JOB_TITLE = "Backend Engineer"
JOB_COMPANY = "Acme Inc"
JOB_SKILLS = ["python", "django", "aws", "kubernetes"]
JOB_DESC = "Backend engineer. Requires Python, Django, AWS and Kubernetes experience."
CHUNKS = [
    SimpleNamespace(chunk_id=1, chunk_index=0, section="experience", score=88,
                    content="Built Django REST APIs on AWS with PostgreSQL."),
    SimpleNamespace(chunk_id=2, chunk_index=1, section="skills", score=40,
                    content="Docker and CI/CD tooling."),
]


def _ctx(**overrides):
    base = dict(
        user_name="Sara Chen",
        user_email="sara@example.com",
        profile_skills=["python", "django"],
        resume_text=RESUME,
        job_title=JOB_TITLE,
        job_company=JOB_COMPANY,
        job_skills=list(JOB_SKILLS),
        job_description=JOB_DESC,
        ats_score=62,
        semantic_score=71,
        retrieved_chunks=list(CHUNKS),
        model_used="all-MiniLM-L6-v2",
        used_fallback=False,
        matched_skills=["python", "django"],
        missing_skills=["aws", "kubernetes"],
    )
    base.update(overrides)
    from app.services.mock_interview import InterviewContext

    return InterviewContext(**base)


def _qapair(score, category="technical"):
    return {
        "category": category,
        "question": "Explain your Django experience.",
        "answer": "I built REST APIs with Django.",
        "score": score,
        "strengths": [f"Strength-{score}"],
        "weaknesses": [f"Weakness-{score}"],
        "missing_points": ["Details"],
    }


# ---------------------------------------------------------------------------
# Configuration: category rotation + question cap
# ---------------------------------------------------------------------------

def test_category_rotation_repeats_cycle():
    order = [category_for_index(i) for i in range(8)]
    assert order == ["technical", "project_experience", "problem_solving",
                     "behavioral"] * 2
    assert CATEGORIES[:4] == [
        "technical", "project_experience", "problem_solving", "behavioral"
    ]


def test_max_questions_env_parsing(monkeypatch):
    monkeypatch.setenv("MOCK_INTERVIEW_MAX_QUESTIONS", "5")
    assert max_questions() == 5
    monkeypatch.setenv("MOCK_INTERVIEW_MAX_QUESTIONS", "100")
    assert max_questions() == 30  # capped
    monkeypatch.setenv("MOCK_INTERVIEW_MAX_QUESTIONS", "abc")
    assert max_questions() == DEFAULT_MAX_QUESTIONS
    monkeypatch.delenv("MOCK_INTERVIEW_MAX_QUESTIONS", raising=False)
    assert max_questions() == DEFAULT_MAX_QUESTIONS


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def test_build_context_section_includes_resume_job_chunks_and_skills():
    section = build_context_section(_ctx())
    assert "Sara Chen" in section
    assert "LATEST RESUME TEXT" in section and "PostgreSQL" in section
    assert JOB_TITLE in section and "Acme Inc" in section
    assert "Built Django REST APIs on AWS" in section  # retrieved chunk grounded
    assert "ATS MATCH SCORE: 62" in section
    assert "SEMANTIC SCORE: 71" in section
    assert "aws, kubernetes" in section  # missing skills listed


def test_build_context_section_handles_no_resume_and_no_job():
    ctx = _ctx(resume_text=None, job_title=None, job_company=None,
               job_skills=[], job_description=None, retrieved_chunks=[],
               ats_score=None, semantic_score=None,
               matched_skills=[], missing_skills=[])
    section = build_context_section(ctx)
    assert "(none uploaded)" in section
    assert "None listed" in section


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def test_build_question_prompt_is_grounded_and_adaptive():
    prompt = build_question_prompt(
        _ctx(), "technical", 0, 8, previous_answer="I used fastAPI once."
    )
    assert "SUPPLIED CONTEXT" in prompt
    assert "Sara Chen" in prompt and "PostgreSQL" in prompt
    assert "CATEGORY: technical" in prompt
    assert "QUESTION NUMBER: 1 of 8" in prompt
    assert "I used fastAPI once." in prompt  # adaptive follow-up
    assert "only in the supplied context" not in prompt  # rules live in system prompt


def test_build_question_prompt_without_previous_answer():
    prompt = build_question_prompt(_ctx(), "behavioral", 3, 8)
    assert "PREVIOUS ANSWER" not in prompt


def test_build_evaluation_prompt_includes_question_answer_and_category():
    prompt = build_evaluation_prompt(_ctx(), "Explain Django.", "technical", "I built APIs.")
    assert "EXPLAIN DJANGO.".lower() in prompt.lower()
    assert "I built APIs." in prompt
    assert "QUESTION CATEGORY: technical" in prompt
    assert "CANDIDATE'S ANSWER" in prompt


def test_build_report_prompt_includes_qa_pairs_and_aggregates():
    prompt = build_report_prompt(_ctx(), [_qapair(8)], {"overall_score": 8, "category_scores": []})
    assert "Q1 [technical]" in prompt
    assert "Score: 8/10" in prompt
    assert "OVERALL: 8/10" in prompt


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------

def test_parse_question_json_accepts_common_shape():
    assert parse_question_json({"question": "What is X?"})["question_text"] == "What is X?"
    assert parse_question_json({"question_text": "Y?"})["question_text"] == "Y?"


def test_parse_question_json_rejects_empty_or_non_object():
    with pytest.raises(ValueError):
        parse_question_json({"question": "   "})
    with pytest.raises(ValueError):
        parse_question_json([])


def test_generate_question_llm_path_uses_grounding_system_prompt():
    def fake_llm(prompt, system=None):
        assert system == QUESTION_SYSTEM_PROMPT
        assert "Sara Chen" in prompt and "PostgreSQL" in prompt
        return {"question": "Walk me through the Django APIs you built."}

    result = generate_question(_ctx(), "technical", 0, 8, llm_call=fake_llm)
    assert result["generated_by"] == "llm"
    assert "Django" in result["question_text"]
    assert result["notice"] is None


def test_generate_question_pass_previous_answer_to_llm():
    captured = {}

    def fake_llm(prompt, system=None):
        captured["prompt"] = prompt
        return {"question": "Adaptive follow-up?"}

    generate_question(_ctx(), "project_experience", 2, 8,
                      previous_answer="I used agile in my project.", llm_call=fake_llm)
    assert "I used agile in my project." in captured["prompt"]


def test_generate_question_fallback_when_llm_broken_is_grounded():
    def broken(prompt, system=None):
        raise RuntimeError("connection refused")

    result = generate_question(_ctx(), "technical", 0, 8, llm_call=broken)
    assert result["generated_by"] == "fallback"
    assert "connection refused" in result["notice"]
    # Fallback anchors on the first required skill — never an invented one.
    assert "python" in result["question_text"].lower()
    for invented in ("rust", "blockchain", "machine learning"):
        assert invented not in result["question_text"].lower()


def test_fallback_question_all_categories_non_empty():
    for index in range(8):
        result = fallback_question(_ctx(), category_for_index(index), index, 8)
        assert result["question_text"].strip()
        assert result["generated_by"] == "fallback"
        assert FALLBACK_NOTICE in result["notice"]


def test_fallback_question_without_skills_uses_strict_generic_phrasing():
    ctx = _ctx(job_skills=[], matched_skills=[], missing_skills=[])
    result = fallback_question(ctx, "technical", 0, 8)
    assert "actually listed in your resume" in result["question_text"]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def test_parse_evaluation_json_clamps_score_and_defaults():
    data = parse_evaluation_json({
        "score": 99,
        "correctness": "Excellent",
        "strengths": ["a", "b"],
        "weaknesses": [],
        "missing_points": None,
        "feedback": "Keep going",
    })
    assert data["score"] == 10
    assert data["strengths"] == ["a", "b"]
    assert data["weaknesses"] == []
    assert data["missing_points"] == []
    assert parse_evaluation_json({})["score"] == 0


def test_evaluate_answer_llm_path():
    def fake_llm(prompt, system=None):
        assert system == EVALUATION_SYSTEM_PROMPT
        return {
            "score": 7,
            "correctness": "Solid and relevant.",
            "strengths": ["Good example"],
            "weaknesses": ["Could add outcome"],
            "missing_points": ["Metrics"],
            "feedback": "Quantify the impact.",
        }

    result = evaluate_answer(_ctx(), "Explain Django.", "technical", "Answer...", llm_call=fake_llm)
    assert result["generated_by"] == "llm"
    assert result["score"] == 7
    assert result["feedback"] == "Quantify the impact."


def test_evaluate_answer_fallback_on_llm_error():
    def broken(prompt, system=None):
        raise RuntimeError("rate limited")

    result = evaluate_answer(_ctx(), "Explain Django.", "technical", "Answer...", llm_call=broken)
    assert result["generated_by"] == "fallback"
    assert "rate limited" in result["notice"]
    assert 0 <= result["score"] <= 10


def test_fallback_evaluation_deterministic_and_bounded():
    e = fallback_evaluation(
        _ctx(),
        "Explain your Python experience for this role.",
        "technical",
        "I used Python and Django at my internship to build REST APIs.",
    )
    assert 0 <= e["score"] <= 10
    assert e["generated_by"] == "fallback"
    # References the required skill present in the answer, nothing invented.
    assert any("python" in s.lower() for s in e["strengths"])
    for invented in ("rust", "blockchain", "machine learning"):
        text = " ".join([e["correctness"], e["feedback"]]
                        + e["strengths"] + e["weaknesses"]
                        + e["missing_points"]).lower()
        assert invented not in text


def test_fallback_evaluation_empty_answer_scores_low():
    e = fallback_evaluation(_ctx(), "Question?", "behavioral", "   ")
    assert e["score"] == 1
    assert any("no answer was provided" in p.lower()
               for p in [e["correctness"]] + e["weaknesses"])


def test_fallback_evaluation_short_answer_flagged():
    e = fallback_evaluation(_ctx(), "Describe your resume project.", "project_experience", "did stuff")
    assert e["score"] <= 5
    assert any("brief" in w.lower() for w in e["weaknesses"])


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

def test_parse_report_json_lenient():
    data = parse_report_json({
        "overall_score": 8,
        "category_scores": [{"category": "technical", "score": 9, "comment": "c"}],
        "strengths": ["A"],
        "weaknesses": ["B"],
        "recommended_topics": ["T"],
        "summary": "Fine",
    })
    assert data["overall_score"] == 8
    assert data["category_scores"][0]["score"] == 9
    assert parse_report_json({})["overall_score"] == 0


def test_generate_report_llm_path():
    def fake_llm(prompt, system=None):
        assert system == REPORT_SYSTEM_PROMPT
        return {
            "overall_score": 8,
            "category_scores": [{"category": "technical", "score": 9, "comment": ""}],
            "strengths": ["Strong Python"],
            "weaknesses": ["Needs Kubernetes"],
            "recommended_topics": ["Kubernetes"],
            "summary": "Overall strong technical depth.",
        }

    report = generate_report(_ctx(), [_qapair(8)], llm_call=fake_llm)
    assert report["generated_by"] == "llm"
    assert report["overall_score"] == 8
    assert report["summary"] == "Overall strong technical depth."


def test_generate_report_fallback_when_llm_down():
    def broken(prompt, system=None):
        raise RuntimeError("down")

    report = generate_report(_ctx(), [_qapair(8), _qapair(6, "behavioral")], llm_call=broken)
    assert report["generated_by"] == "fallback"
    assert "down" in report["notice"]
    # Fallback still produces a valid aggregate report.
    assert report["overall_score"] == 7


def test_fallback_report_aggregates_scores_categories_and_feedback():
    pairs = [
        _qapair(8, "technical"),
        _qapair(6, "behavioral"),
        _qapair(8, "technical"),
    ]
    report = fallback_report(_ctx(), pairs)
    assert report["generated_by"] == "fallback"
    assert report["overall_score"] == 7  # (8+6+8)/3 -> 7.33 -> 7
    cats = {c["category"]: c["score"] for c in report["category_scores"]}
    assert cats["technical"] == 8
    assert cats["behavioral"] == 6
    # Strengths/weaknesses carried over from the evaluations.
    assert "Strength-8" in report["strengths"]
    assert "Weakness-6" in report["weaknesses"]
    # Recommended topics grounded in the missing required skills.
    joined = " ".join(report["recommended_topics"]).lower()
    assert "kubernetes" in joined or "aws" in joined


def test_fallback_report_empty_interview_is_baseline():
    report = fallback_report(_ctx(), [])
    assert report["overall_score"] == 0
    assert report["category_scores"] == []
    assert "baseline" in report["summary"].lower()


def test_fallback_report_suggestions_from_weak_categories():
    pairs = [_qapair(2, "behavioral")]
    report = fallback_report(_ctx(), pairs)
    joined = " ".join(report["recommended_topics"]).lower()
    assert "behavioral" in joined


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def test_build_question_row_maps_fields():
    row = build_question_row(
        5, 1, "problem_solving",
        {"question_text": "Solve this.", "generated_by": "llm", "notice": None},
        [{"chunk_id": 1, "chunk_index": 0, "section": "skills", "score": 10, "content": "x"}],
    )
    assert row.interview_id == 5
    assert row.question_index == 1
    assert row.category == "problem_solving"
    assert row.question_text == "Solve this."
    assert row.generated_by == "llm"
    assert row.question_sources[0]["chunk_id"] == 1


def test_apply_evaluation_flattens_fields():
    question = MockInterviewQuestion(
        id=1, interview_id=1, question_index=0, category="technical", question_text="Q"
    )
    apply_evaluation(question, "My answer", {
        "score": 7, "correctness": "ok", "strengths": ["s"],
        "weaknesses": ["w"], "missing_points": ["m"], "feedback": "fb",
        "generated_by": "llm", "notice": None,
    })
    assert question.answer_text == "My answer"
    assert question.score == 7
    assert question.correctness == "ok"
    assert question.strengths == ["s"]
    assert question.weaknesses == ["w"]
    assert question.missing_points == ["m"]
    assert question.feedback == "fb"
    assert question.evaluation_generated_by == "llm"
    assert question.evaluated_at is not None


def test_apply_report_flattens_fields():
    interview = MockInterview(
        id=1, user_id=1, application_id=2,
        status=MockInterviewStatusEnum.in_progress, max_questions=2,
    )
    apply_report(interview, {
        "overall_score": 9, "category_scores": [{"category": "technical", "score": 9, "comment": ""}],
        "strengths": ["s"], "weaknesses": ["w"], "recommended_topics": ["t"],
        "summary": "sum", "generated_by": "llm", "notice": None,
    }, completed_at="2026-01-01")
    assert interview.overall_score == 9
    assert interview.report_generated_by == "llm"
    assert interview.completed_at == "2026-01-01"


def test_build_qa_pairs_skips_unanswered():
    answered = MockInterviewQuestion(
        question_index=0, category="technical", question_text="q",
        answer_text="a", score=8, strengths=["s"], weaknesses=[], missing_points=[],
    )
    unanswered = MockInterviewQuestion(
        question_index=1, category="behavioral", question_text="q"
    )
    pairs = build_qa_pairs([answered, unanswered])
    assert len(pairs) == 1
    assert pairs[0]["score"] == 8
    assert pairs[0]["strengths"] == ["s"]


# ---------------------------------------------------------------------------
# Serialization of sessions to response schemas
# ---------------------------------------------------------------------------

def _in_progress_interview():
    interview = MockInterview(
        id=1, user_id=1, application_id=2,
        status=MockInterviewStatusEnum.in_progress, max_questions=4,
        started_at=datetime(2026, 1, 1),
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    q1 = MockInterviewQuestion(
        id=10, interview_id=1, question_index=0, category="technical",
        question_text="Q1", generated_by="llm",
        question_sources=[{"chunk_id": 1, "chunk_index": 0, "section": "s", "score": 5, "content": "c"}],
        answer_text="A1", score=8, correctness="good", strengths=["s1"],
        weaknesses=["w1"], missing_points=["m1"], feedback="f1",
        evaluation_generated_by="llm",
    )
    q2 = MockInterviewQuestion(
        id=11, interview_id=1, question_index=1, category="project_experience",
        question_text="Q2", generated_by="fallback",
    )
    interview.questions = [q1, q2]
    return interview


def test_question_out_message_serialization():
    q = _in_progress_interview().questions[0]
    out = _question_out(q)
    assert out.id == 10
    assert out.generated_by == "llm"
    assert out.sources[0].chunk_id == 1


def test_detail_exposes_current_question_and_answered():
    detail = _detail(_in_progress_interview())
    assert detail.status == MockInterviewStatusEnum.in_progress
    assert detail.current_question is not None
    assert detail.current_question.id == 11
    assert detail.current_question.category == "project_experience"
    assert len(detail.answered) == 1
    answered = detail.answered[0]
    assert answered.answer == "A1"
    assert answered.evaluation.score == 8
    assert answered.evaluation.strengths == ["s1"]
    assert detail.report is None


def test_detail_exposes_report_when_completed():
    interview = MockInterview(
        id=3, user_id=1, application_id=2,
        status=MockInterviewStatusEnum.completed, max_questions=2,
        overall_score=7,
        category_scores=[{"category": "technical", "score": 7, "comment": ""}],
        strengths=["s"], weaknesses=["w"], recommended_topics=["t"],
        summary="sum", report={"overall_score": 7}, report_generated_by="fallback",
        report_notice="notice",
        started_at=datetime(2026, 1, 1),
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    interview.questions = []
    detail = _detail(interview)
    assert detail.report is not None
    assert detail.report.overall_score == 7
    assert detail.report.generated_by == "fallback"
    assert detail.report.category_scores[0].category == "technical"
    assert detail.current_question is None


def test_evaluation_out_defaults_when_unanswered():
    q = MockInterviewQuestion(
        id=1, interview_id=1, question_index=0, category="technical", question_text="Q"
    )
    out = _evaluation_out(q)
    assert out.score == 0
    assert out.strengths == []
    assert out.generated_by == "fallback"


# ---------------------------------------------------------------------------
# RBAC / ownership
# ---------------------------------------------------------------------------

class FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._result[0] if self._result else None


class FakeSession:
    def __init__(self, result):
        self._result = result

    def query(self, model):
        return FakeQuery(self._result)


def _user(role, id_=1):
    return User(id=id_, name="x", email=f"{id_}@x.com", password="p", role=role)


def _interview(user_id=1, id_=10):
    return MockInterview(
        id=id_, user_id=user_id, application_id=2,
        status=MockInterviewStatusEnum.in_progress, max_questions=2,
    )


def test_role_checker_blocks_non_candidates():
    assert RoleChecker(["user"])(current_user=_user(RoleEnum.user)) is not None
    with pytest.raises(Exception) as exc:
        RoleChecker(["user"])(current_user=_user(RoleEnum.admin))
    assert getattr(getattr(exc.value, "status_code", None), "value", 0) or exc.value.status_code == 403


def test_owned_interview_missing_returns_404():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _owned_interview(FakeSession([]), _user(RoleEnum.user), 10)
    assert exc.value.status_code == 404


def test_owned_interview_other_users_returns_403():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _owned_interview(FakeSession([_interview(user_id=2)]),
                         _user(RoleEnum.user, id_=1), 10)
    assert exc.value.status_code == 403


def test_owned_interview_owner_allowed():
    interview = _owned_interview(FakeSession([_interview(user_id=1)]),
                                 _user(RoleEnum.user, id_=1), 10)
    assert interview.id == 10


# ---------------------------------------------------------------------------
# HR mode: categories, prompts, fallbacks, personas
# ---------------------------------------------------------------------------

def test_hr_category_rotation_repeats_cycle():
    assert HR_CATEGORIES == [
        "communication", "work_experience", "motivation", "behavioral"
    ]
    order = [category_for_index(i, "hr") for i in range(8)]
    assert order == [
        "communication", "work_experience", "motivation", "behavioral"
    ] * 2
    assert interview_categories("hr") == HR_CATEGORIES
    assert interview_categories("technical") == CATEGORIES


def test_build_question_prompt_advertises_hr_vocabulary():
    prompt_hr = build_question_prompt(
        _ctx(), "communication", 0, 8, interview_type="hr"
    )
    assert "communication, work_experience, motivation, behavioral" in prompt_hr
    prompt_tech = build_question_prompt(_ctx(), "technical", 0, 8)
    assert "technical, project_experience, problem_solving, behavioral" in prompt_tech
    assert "communication" not in prompt_tech


def test_generate_question_hr_uses_hr_persona_prompt():
    captured = {}

    def llm(prompt, system=None):
        captured["system"] = system
        return {
            "question": "Describe a time you explained engineering work to a non-engineer."
        }

    result = generate_question(
        _ctx(), "communication", 0, 8, llm_call=llm, interview_type="hr"
    )
    assert captured["system"] == HR_QUESTION_SYSTEM_PROMPT
    assert result["generated_by"] == "llm"


def test_generate_question_default_uses_technical_persona():
    captured = {}

    def llm(prompt, system=None):
        captured["system"] = system
        return {"question": "Explain your Django experience."}

    generate_question(_ctx(), "technical", 0, 8, llm_call=llm)
    assert captured["system"] == QUESTION_SYSTEM_PROMPT


def test_generate_question_hr_falls_back_grounded_on_llm_failure():
    def llm(prompt, system=None):
        raise RuntimeError("down")

    result = generate_question(
        _ctx(), "communication", 0, 8, llm_call=llm, interview_type="hr"
    )
    assert result["generated_by"] == "fallback"
    assert "non-technical audience" in result["question_text"]
    assert result["notice"]


def test_hr_fallback_questions_stay_grounded_in_category():
    hr = _ctx()
    checks = {
        "communication": "non-technical",
        "work_experience": "work history",
        "motivation": "role",
        "behavioral": "difficult situation",
    }
    for category, needle in checks.items():
        q = fallback_question(hr, category, 0, 8, interview_type="hr")
        assert needle.lower() in q["question_text"].lower()


def test_fallback_question_default_stays_technical():
    q = fallback_question(_ctx(), "technical", 0, 8)
    assert "resume" in q["question_text"]


def test_evaluate_answer_hr_uses_hr_persona_prompt():
    captured = {}

    def llm(prompt, system=None):
        captured["system"] = system
        return {
            "score": 8,
            "correctness": "good",
            "strengths": ["clear"],
            "weaknesses": [],
            "missing_points": [],
            "feedback": "keep going",
        }

    result = evaluate_answer(
        _ctx(),
        "Tell me about X.",
        "communication",
        "I led a demo for stakeholders.",
        llm_call=llm,
        interview_type="hr",
    )
    assert captured["system"] == HR_EVALUATION_SYSTEM_PROMPT
    assert result["score"] == 8
    assert result["generated_by"] == "llm"


def test_generate_report_hr_uses_hr_persona_prompt():
    captured = {}

    def llm(prompt, system=None):
        captured["system"] = system
        return {
            "overall_score": 8,
            "category_scores": [
                {"category": "communication", "score": 8, "comment": "good"}
            ],
            "strengths": ["clear"],
            "weaknesses": [],
            "recommended_topics": ["public speaking"],
            "summary": "Strong communicator.",
        }

    report = generate_report(
        _ctx(), [_qapair(8, "communication")], llm_call=llm, interview_type="hr"
    )
    assert captured["system"] == HR_REPORT_SYSTEM_PROMPT
    assert report["overall_score"] == 8
    assert report["generated_by"] == "llm"


def test_generate_report_default_uses_technical_persona():
    captured = {}

    def llm(prompt, system=None):
        captured["system"] = system
        return {
            "overall_score": 7,
            "category_scores": [
                {"category": "technical", "score": 7, "comment": "good"}
            ],
            "strengths": [],
            "weaknesses": [],
            "recommended_topics": [],
            "summary": "Solid.",
        }

    generate_report(_ctx(), [_qapair(7)], llm_call=llm)
    assert captured["system"] == REPORT_SYSTEM_PROMPT
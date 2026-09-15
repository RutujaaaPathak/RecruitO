"""Tests for the AI MCQ Assessment (Phase 1): configuration, question
generation (LLM + fallback bank), scoring, the backend-enforced timer, answer
upserts (no duplicate submissions), RBAC/ownership, and answer security (the
correct answer is never serialized) — hermetic, no DB / API.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.auth import RoleChecker  # noqa: E402
from app.models import (  # noqa: E402
    AssessmentStatusEnum,
    McqAnswer,
    McqAssessment,
    McqQuestion,
    RoleEnum,
    User,
)
from app.routes.mcq_assessments import (  # noqa: E402
    _detail,
    _ensure_answerable,
    _finalize_if_expired,
    _owned_assessment,
    _owned_application,
    _question_out,
    _results_out,
    _selected_map,
)
from app.services.mcq_assessment import (  # noqa: E402
    CATEGORIES,
    DEFAULT_PASS_PERCENTAGE,
    DEFAULT_QUESTION_COUNT,
    DEFAULT_TIME_LIMIT_MINUTES,
    EXPIRY_NOTICE,
    FALLBACK_NOTICE,
    MCQ_SYSTEM_PROMPT,
    build_answer_row,
    build_generation_prompt,
    build_question_row,
    category_for_index,
    compute_results,
    expires_at,
    fallback_question_at,
    finalize_assessment,
    generate_questions,
    is_expired,
    parse_generation_json,
    pass_threshold,
    question_count,
    record_answer,
    time_limit_minutes,
)


def _question_dict(index, correct, category="technical"):
    return {
        "question_index": index,
        "category": category,
        "correct_option_index": correct,
    }


def _ctx(**overrides):
    base = dict(
        user_name="Sara Chen",
        user_email="sara@example.com",
        profile_skills=["python", "django"],
        resume_text="Python developer with Django and Docker experience.",
        job_title="Backend Engineer",
        job_company="Acme Inc",
        job_skills=["python", "aws", "kubernetes"],
        job_description="Backend engineer. Requires Python and AWS.",
        ats_score=62,
        semantic_score=71,
        retrieved_chunks=[],
        model_used="all-MiniLM-L6-v2",
        used_fallback=False,
        matched_skills=["python"],
        missing_skills=["aws", "kubernetes"],
    )
    base.update(overrides)
    from app.services.mock_interview import InterviewContext

    return InterviewContext(**base)


def _assessment(**kw):
    defaults = dict(
        id=1,
        user_id=1,
        application_id=2,
        status=AssessmentStatusEnum.in_progress,
        total_questions=2,
        time_limit_minutes=20,
        pass_percentage=DEFAULT_PASS_PERCENTAGE,
        started_at=datetime(2026, 1, 1, 10, 0, 0),
        created_at=datetime(2026, 1, 1, 10, 0, 0),
        updated_at=datetime(2026, 1, 1, 10, 0, 0),
        generated_by="llm",
        used_fallback=False,
        model_used="all-MiniLM-L6-v2",
    )
    defaults.update(kw)
    return McqAssessment(**defaults)


def _question(qid, index, correct=0, options=None, category="technical", **kw):
    defaults = dict(
        id=qid,
        assessment_id=1,
        question_index=index,
        category=category,
        question_text=f"Question {index}",
        options=options or ["opt-a", "opt-b", "opt-c", "opt-d"],
        correct_option_index=correct,
        generated_by="llm",
        notice=None,
    )
    defaults.update(kw)
    return McqQuestion(**defaults)


def _answer(aid, qid, selected, correct=False, when=None):
    return McqAnswer(
        id=aid,
        assessment_id=1,
        question_id=qid,
        selected_option=selected,
        is_correct=correct,
        answered_at=when or datetime(2026, 1, 1, 10, 1, 0),
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def test_default_configuration():
    assert question_count() == DEFAULT_QUESTION_COUNT == 20
    assert time_limit_minutes() == DEFAULT_TIME_LIMIT_MINUTES == 20
    assert pass_threshold() == DEFAULT_PASS_PERCENTAGE == 60


def test_env_configuration_parses_and_clamps(monkeypatch):
    monkeypatch.setenv("MCQ_QUESTION_COUNT", "25")
    assert question_count() == 25
    monkeypatch.setenv("MCQ_QUESTION_COUNT", "1")
    assert question_count() == 5  # clamped up
    monkeypatch.setenv("MCQ_QUESTION_COUNT", "99")
    assert question_count() == 50  # clamped down
    monkeypatch.setenv("MCQ_QUESTION_COUNT", "abc")
    assert question_count() == DEFAULT_QUESTION_COUNT

    monkeypatch.setenv("MCQ_TIME_LIMIT_MINUTES", "30")
    assert time_limit_minutes() == 30
    monkeypatch.setenv("MCQ_TIME_LIMIT_MINUTES", "abc")
    assert time_limit_minutes() == DEFAULT_TIME_LIMIT_MINUTES

    monkeypatch.setenv("MCQ_PASS_PERCENTAGE", "70")
    assert pass_threshold() == 70
    monkeypatch.setenv("MCQ_PASS_PERCENTAGE", "0")
    assert pass_threshold() == 1
    monkeypatch.setenv("MCQ_PASS_PERCENTAGE", "abc")
    assert pass_threshold() == DEFAULT_PASS_PERCENTAGE


def test_category_rotation_repeats_round_robin():
    order = [category_for_index(i) for i in range(12)]
    assert order == CATEGORIES * 3
    assert CATEGORIES == [
        "technical", "problem_solving", "situational", "behavioral"
    ]


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def test_build_generation_prompt_is_grounded():
    prompt = build_generation_prompt(_ctx(), 20)
    assert "SUPPLIED CONTEXT" in prompt
    assert "Sara Chen" in prompt
    assert "Backend Engineer" in prompt
    assert "NUMBER OF QUESTIONS: 20" in prompt
    assert "technical, problem_solving, situational, behavioral" in prompt
    assert "recruito" in MCQ_SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------

def _llm_item(category="technical", options=None, correct_index=2, question="Q?"):
    return {
        "category": category,
        "question": question,
        "options": options or ["a", "b", "c", "d"],
        "correct_index": correct_index,
    }


def test_parse_generation_json_accepts_valid_batch():
    data = {"questions": [_llm_item(correct_index=0), _llm_item(correct_index=3)]}
    parsed = parse_generation_json(data, 20)
    assert len(parsed) == 2
    assert parsed[0]["correct_index"] == 0
    assert parsed[0]["options"] == ["a", "b", "c", "d"]
    assert parsed[0]["category"] == "technical"


def test_parse_generation_json_accepts_letters_and_rejects_ambiguous_one_based():
    data = {"questions": [
        _llm_item(correct_index="C"),  # letter -> index 2
        _llm_item(correct_index=4),    # NOT 1-based: 4 is out of range (skipped)
    ]}
    parsed = parse_generation_json(data, 20)
    assert len(parsed) == 1
    assert parsed[0]["correct_index"] == 2


def test_parse_generation_json_skips_malformed_items():
    data = {"questions": [
        _llm_item(options=["a", "b", "c"]),          # too few options
        _llm_item(options=["a", "a", "b", "c"]),     # duplicate options
        _llm_item(correct_index=4),                  # out of range (0-based)
        _llm_item(question="   "),                   # empty question
        {"not": "an item"},
        _llm_item(),                                 # valid
    ]}
    parsed = parse_generation_json(data, 20)
    assert len(parsed) == 1
    assert parsed[0]["question"] == "Q?"


def test_parse_generation_json_rejects_non_object_or_missing_list():
    with pytest.raises(ValueError):
        parse_generation_json([], 20)
    with pytest.raises(ValueError):
        parse_generation_json({}, 20)
    with pytest.raises(ValueError):
        parse_generation_json({"questions": "nope"}, 20)


def test_parse_generation_json_caps_at_total():
    data = {"questions": [_llm_item() for _ in range(30)]}
    parsed = parse_generation_json(data, 20)
    assert len(parsed) == 20


# ---------------------------------------------------------------------------
# Question generation (LLM + fallback bank)
# ---------------------------------------------------------------------------

def test_generate_questions_llm_path_builds_full_test():
    def fake_llm(prompt, system=None):
        assert system == MCQ_SYSTEM_PROMPT
        assert "NUMBER OF QUESTIONS: 20" in prompt
        return {"questions": [_llm_item(correct_index=i % 4) for i in range(20)]}

    result = generate_questions(_ctx(), 20, llm_call=fake_llm)
    assert result["generated_by"] == "llm"
    assert result["used_fallback"] is False
    assert len(result["questions"]) == 20
    assert all(q["generated_by"] == "llm" for q in result["questions"])
    assert all(q["correct_index"] in (0, 1, 2, 3) for q in result["questions"])
    assert all(q["question_index"] == i for i, q in enumerate(result["questions"]))


def test_generate_questions_falls_back_entirely_when_llm_broken():
    def broken(prompt, system=None):
        raise RuntimeError("connection refused")

    result = generate_questions(_ctx(), 20, llm_call=broken)
    assert result["generated_by"] == "fallback"
    assert result["used_fallback"] is True
    assert len(result["questions"]) == 20
    assert all(q["generated_by"] == "fallback" for q in result["questions"])
    assert "connection refused" in result["notice"]
    assert FALLBACK_NOTICE in result["questions"][0]["notice"]


def test_generate_questions_pads_partial_llm_batch_to_full():
    def fake_llm(prompt, system=None):
        return {"questions": [_llm_item() for _ in range(3)]}

    result = generate_questions(_ctx(), 20, llm_call=fake_llm)
    assert result["generated_by"] == "mixed"
    assert result["used_fallback"] is True
    assert len(result["questions"]) == 20
    assert [q["generated_by"] for q in result["questions"][:3]] == ["llm"] * 3
    assert all(q["generated_by"] == "fallback" for q in result["questions"][3:])
    # Indices remain 0..19 so question order is stable after a refresh.
    assert [q["question_index"] for q in result["questions"]] == list(range(20))


def test_fallback_question_bank_is_deterministic_and_valid():
    first = [fallback_question_at(i) for i in range(20)]
    second = [fallback_question_at(i) for i in range(20)]
    assert [q["question"] for q in first] == [q["question"] for q in second]
    assert len(first) == 20
    for q in first:
        assert len(q["options"]) == 4
        assert len(set(q["options"])) == 4  # distinct options
        assert 0 <= int(q["correct_index"]) <= 3
        assert q["category"] in CATEGORIES
    assert [q["category"] for q in first] == CATEGORIES * 5


def test_build_question_row_persists_options_and_answer_key():
    row = build_question_row(
        7,
        {
            "question_index": 3,
            "category": "situational",
            "question": "Q",
            "options": ["w", "x", "y", "z"],
            "correct_index": 2,
            "generated_by": "llm",
            "notice": None,
        },
    )
    assert row.assessment_id == 7
    assert row.question_index == 3
    assert row.category == "situational"
    assert row.options == ["w", "x", "y", "z"]
    assert row.correct_option_index == 2
    assert row.generated_by == "llm"


# ---------------------------------------------------------------------------
# Answer upsert (duplicate-submission safety)
# ---------------------------------------------------------------------------

def test_build_answer_row_snapshots_correctness():
    q = _question(5, 0, correct=2)
    row = build_answer_row(_assessment(), q, 2)
    assert row.selected_option == 2
    assert row.is_correct is True
    row2 = build_answer_row(_assessment(), q, 1)
    assert row2.is_correct is False


def test_record_answer_upserts_and_never_duplicates():
    assessment = _assessment()
    q = _question(5, 0, correct=2)
    assessment.answers = []

    created = record_answer(assessment, q, 2)
    assert created is True
    assert len(assessment.answers) == 1
    assert assessment.answers[0].is_correct is True

    # Re-answering the same question must update the single row, not create a
    # second submission.
    created_again = record_answer(assessment, q, 0)
    assert created_again is False
    assert len(assessment.answers) == 1
    assert assessment.answers[0].selected_option == 0
    assert assessment.answers[0].is_correct is False


def test_record_answer_tracks_multiple_questions_separately():
    assessment = _assessment()
    q0 = _question(5, 0, correct=0)
    q1 = _question(6, 1, correct=3)
    assessment.answers = []
    record_answer(assessment, q0, 0)
    record_answer(assessment, q1, 3)
    assert len(assessment.answers) == 2


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_compute_results_scores_mixed_attempt():
    questions = [
        _question_dict(0, correct=2, category="technical"),
        _question_dict(1, correct=3, category="technical"),
        _question_dict(2, correct=0, category="behavioral"),
        _question_dict(3, correct=1, category="behavioral"),
    ]
    answered = {0: 2, 2: 1}  # q0 correct, q1 wrong, q2/q3 unanswered
    results = compute_results(questions, answered, 4, 60)
    assert results["score"] == 1
    assert results["total"] == 4
    assert results["percentage"] == 25
    assert results["correct_count"] == 1
    assert results["incorrect_count"] == 1
    assert results["unanswered_count"] == 2
    assert results["passed"] is False
    assert results["pass_percentage"] == 60


def test_compute_results_category_performance_aggregates():
    questions = [
        _question_dict(0, correct=2, category="technical"),
        _question_dict(1, correct=3, category="technical"),
        _question_dict(2, correct=0, category="behavioral"),
    ]
    answered = {0: 2, 1: 2}  # technical one correct one wrong; behavioral wrong
    results = compute_results(questions, answered, 3, 60)
    cats = {c["category"]: c for c in results["category_performance"]}
    assert cats["technical"]["total"] == 2
    assert cats["technical"]["correct"] == 1
    assert cats["technical"]["percentage"] == 50
    assert cats["behavioral"]["total"] == 1
    assert cats["behavioral"]["correct"] == 0
    assert cats["behavioral"]["percentage"] == 0


def test_compute_results_pass_fail_threshold_boundary():
    full = [_question_dict(i, correct=0) for i in range(20)]
    answered_correct_12 = {i: 0 for i in range(12)}
    answered_correct_11 = {i: 0 for i in range(11)}
    assert compute_results(full, answered_correct_12, 20, 60)["passed"] is True
    assert compute_results(full, answered_correct_11, 20, 60)["passed"] is False


def test_compute_results_empty_attempt_scores_zero():
    questions = [_question_dict(i, correct=0) for i in range(4)]
    results = compute_results(questions, {}, 4, 50)
    assert results["score"] == 0
    assert results["percentage"] == 0
    assert results["unanswered_count"] == 4
    assert results["passed"] is False


def test_compute_results_percentage_rounds():
    questions = [_question_dict(i, correct=0) for i in range(3)]
    results = compute_results(questions, {0: 0}, 3, 33)
    assert results["percentage"] == 33
    assert results["passed"] is True


# ---------------------------------------------------------------------------
# Backend-enforced timer
# ---------------------------------------------------------------------------

def test_expires_at_derives_deadline_from_started_at_plus_limit():
    a = _assessment(started_at=datetime(2026, 1, 1, 10, 0, 0), time_limit_minutes=20)
    assert expires_at(a) == datetime(2026, 1, 1, 10, 20, 0)


def test_is_expired_boundaries():
    started = datetime(2026, 1, 1, 10, 0, 0)
    a = _assessment(started_at=started, time_limit_minutes=20)
    assert is_expired(a, now=datetime(2026, 1, 1, 10, 19, 59)) is False
    # Deadline is inclusive: at exactly 10:20 the test is over.
    assert is_expired(a, now=datetime(2026, 1, 1, 10, 20, 0)) is True
    assert is_expired(a, now=datetime(2026, 1, 1, 10, 25, 0)) is True


def test_is_expired_false_for_completed_assessment():
    a = _assessment(status=AssessmentStatusEnum.completed,
                    started_at=datetime(2026, 1, 1, 10, 0, 0))
    assert is_expired(a, now=datetime(2026, 1, 1, 10, 30, 0)) is False


def test_finalize_assessment_computes_results_for_expired_test():
    a = _assessment(total_questions=3, started_at=datetime(2026, 1, 1, 10, 0, 0))
    q0 = _question(10, 0, correct=1)
    q1 = _question(11, 1, correct=3)
    q2 = _question(12, 2, correct=0)
    a.questions = [q0, q1, q2]
    a.answers = [_answer(1, q0.id, selected=1, correct=True)]

    results = finalize_assessment(a, expired=True)

    assert a.status == AssessmentStatusEnum.completed
    assert a.expired is True
    assert a.completed_at is not None
    assert results["score"] == 1
    assert results["unanswered_count"] == 2
    assert results["expired"] is True
    assert a.result_notice == EXPIRY_NOTICE
    assert a.percentage == 33


def test_finalize_assessment_without_expiry_has_no_expiry_notice():
    a = _assessment(total_questions=2)
    q0 = _question(10, 0, correct=1)
    a.questions = [q0]
    a.answers = [_answer(1, q0.id, selected=1, correct=True)]
    results = finalize_assessment(a, expired=False)
    assert results["expired"] is False
    assert a.expired is False
    assert a.result_notice is None


def test_finalize_assessment_is_idempotent_and_sticky_on_expiry():
    a = _assessment(total_questions=1,
                    started_at=datetime(2026, 1, 1, 10, 0, 0))
    q0 = _question(10, 0, correct=0)
    a.questions = [q0]
    a.answers = [_answer(1, q0.id, selected=0, correct=True)]

    first = finalize_assessment(a, expired=True)
    second = finalize_assessment(a, expired=False)  # e.g. a re-run after submit
    assert a.expired is True  # sticky: expiry is not lost on a re-run
    assert first["score"] == second["score"] == 1
    assert first["percentage"] == second["percentage"] == 100
    assert len(a.answers) == 1  # no duplicate rows created by re-scoring


# ---------------------------------------------------------------------------
# Serialization / answer security
# ---------------------------------------------------------------------------

def _in_progress_assessment():
    a = _assessment(
        id=1, total_questions=2, started_at=datetime(2026, 1, 1, 10, 0, 0),
    )
    q0 = _question(10, 0, correct=1, options=["a", "b", "c", "d"], generated_by="llm")
    q1 = _question(11, 1, correct=0, options=["w", "x", "y", "z"], generated_by="fallback")
    a.questions = [q0, q1]
    a.answers = [_answer(1, q0.id, selected=1, correct=True)]
    return a


def test_question_out_never_exposes_correct_answer():
    q = _question(10, 0, correct=2, options=["a", "b", "c", "d"])
    out = _question_out(q, {q.id: None})
    payload = out.model_dump()
    assert payload["options"] == ["a", "b", "c", "d"]
    assert "correct_option_index" not in payload
    assert "correct_index" not in payload
    assert "correct_answer" not in payload
    assert payload["selected_option"] is None


def test_detail_in_progress_has_no_answer_key_anywhere():
    a = _in_progress_assessment()
    detail = _detail(a)
    assert detail.status == AssessmentStatusEnum.in_progress
    assert detail.answered_count == 1
    assert detail.expires_at is not None
    assert detail.results is None

    raw = detail.model_dump_json()
    assert "correct_option_index" not in raw
    assert "correct_index" not in raw
    assert "correct_answer" not in raw.lower()

    q0out = detail.questions[0]
    assert q0out.options == ["a", "b", "c", "d"]
    assert q0out.selected_option == 1  # candidate's own selection is their data
    assert detail.questions[1].selected_option is None


def test_detail_questions_ordered_by_index():
    a = _in_progress_assessment()
    detail = _detail(a)
    assert [q.question_index for q in detail.questions] == [0, 1]


def test_completed_detail_returns_aggregate_results_only():
    a = _assessment(
        id=2, status=AssessmentStatusEnum.completed, total_questions=2,
        total_scored=2, score=1, percentage=50, correct_count=1,
        incorrect_count=1, unanswered_count=0, passed=False,
        pass_percentage=60, started_at=datetime(2026, 1, 1, 10, 0, 0),
        completed_at=datetime(2026, 1, 1, 10, 10, 0),
        category_performance=[{
            "category": "technical", "total": 2, "correct": 1, "percentage": 50,
        }],
        generated_by="fallback", used_fallback=True,
    )
    a.questions = []
    a.answers = []
    detail = _detail(a)
    assert detail.results is not None
    assert detail.expires_at is None
    assert detail.results.score == 1
    assert detail.results.percentage == 50
    assert detail.results.correct_count == 1
    assert detail.results.incorrect_count == 1
    assert detail.results.passed is False
    assert detail.results.category_performance[0].category == "technical"


def test_results_out_none_while_in_progress():
    assert _results_out(_in_progress_assessment()) is None


# ---------------------------------------------------------------------------
# RBAC / ownership / enforcement
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


def _app(user_id=1, id_=1):
    return SimpleNamespace(id=id_, user_id=user_id)


def test_role_checker_blocks_non_candidates():
    assert RoleChecker(["user"])(current_user=_user(RoleEnum.user)) is not None
    with pytest.raises(Exception) as exc:
        RoleChecker(["user"])(current_user=_user(RoleEnum.admin))
    code = getattr(getattr(exc.value, "status_code", None), "value", None) or (
        exc.value.status_code if hasattr(exc.value, "status_code") else None
    )
    assert code == 403


def test_owned_application_missing_returns_404():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _owned_application(FakeSession([]), _user(RoleEnum.user), 1)
    assert exc.value.status_code == 404


def test_owned_application_other_users_returns_403():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _owned_application(FakeSession([_app(user_id=2)]),
                           _user(RoleEnum.user, id_=1), 1)
    assert exc.value.status_code == 403


def test_owned_application_owner_allowed():
    app_ = _owned_application(FakeSession([_app(user_id=1)]),
                              _user(RoleEnum.user, id_=1), 1)
    assert app_.id == 1


def test_owned_assessment_missing_returns_404():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _owned_assessment(FakeSession([]), _user(RoleEnum.user), 10)
    assert exc.value.status_code == 404


def test_owned_assessment_other_users_returns_403():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _owned_assessment(FakeSession([_assessment(user_id=2, id=10)]),
                          _user(RoleEnum.user, id_=1), 10)
    assert exc.value.status_code == 403


def test_owned_assessment_owner_allowed():
    a = _owned_assessment(FakeSession([_assessment(user_id=1, id=10)]),
                          _user(RoleEnum.user, id_=1), 10)
    assert a.id == 10


def test_ensure_answerable_rejects_completed_assessment():
    from fastapi import HTTPException

    completed = _assessment(status=AssessmentStatusEnum.completed)
    with pytest.raises(HTTPException) as exc:
        _ensure_answerable(completed)
    assert exc.value.status_code == 400


def test_ensure_answerable_rejects_expired_timer():
    from fastapi import HTTPException

    expired = _assessment(started_at=datetime(2026, 1, 1, 10, 0, 0),
                          time_limit_minutes=20)
    with pytest.raises(HTTPException) as exc:
        _ensure_answerable(expired, now=datetime(2026, 1, 1, 10, 21, 0))
    assert exc.value.status_code == 400


def test_ensure_answerable_accepts_active_assessment():
    active = _assessment(started_at=datetime(2026, 1, 1, 10, 0, 0),
                         time_limit_minutes=20)
    _ensure_answerable(active, now=datetime(2026, 1, 1, 10, 5, 0))  # no raise


def test_finalize_if_expired_auto_submits_and_flags_expiry():
    expired = _assessment(
        total_questions=1, started_at=datetime(2026, 1, 1, 10, 0, 0),
    )
    q0 = _question(10, 0, correct=0)
    expired.questions = [q0]
    expired.answers = [_answer(1, q0.id, selected=0, correct=True)]

    finalized = _finalize_if_expired(expired, now=datetime(2026, 1, 1, 10, 21, 0))
    assert finalized is True
    assert expired.status == AssessmentStatusEnum.completed
    assert expired.expired is True
    assert expired.percentage == 100


def test_finalize_if_expired_noop_for_live_assessment():
    live = _assessment(started_at=datetime(2026, 1, 1, 10, 0, 0))
    live.questions = []
    live.answers = []
    assert _finalize_if_expired(live, now=datetime(2026, 1, 1, 10, 5, 0)) is False
    assert live.status == AssessmentStatusEnum.in_progress


# ---------------------------------------------------------------------------
# Selected-map detail helpers
# ---------------------------------------------------------------------------

def test_selected_map_returns_candidate_selection_by_question():
    a = _in_progress_assessment()
    selected = _selected_map(a)
    assert selected == {10: 1}
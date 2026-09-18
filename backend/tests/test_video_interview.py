"""Tests for the Technical Video Interview module: session lifecycle (start/end),
camera & microphone state persistence, RBAC/ownership, and the list/detail
serialization helpers — hermetic, no DB / API.
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
    AssessmentStatusEnum,
    RoleEnum,
    User,
    VideoInterview,
)
from app.routes.video_interviews import (  # noqa: E402
    _answered_count,
    _current_question,
    _detail,
    _ensure_live,
    _list_out,
    _owned_application,
    _owned_session,
    _questions,
)
from app.services.video_interview import (  # noqa: E402
    apply_device_state,
    end_session,
    session_duration_seconds,
)


# ---------------------------------------------------------------------------
# Harness builders
# ---------------------------------------------------------------------------

def _session(**kw):
    defaults = dict(
        id=1,
        user_id=1,
        application_id=2,
        status=AssessmentStatusEnum.in_progress,
        camera_enabled=True,
        microphone_enabled=True,
        started_at=datetime(2026, 1, 1, 10, 0, 0),
        ended_at=None,
        created_at=datetime(2026, 1, 1, 10, 0, 0),
        updated_at=datetime(2026, 1, 1, 10, 0, 0),
    )
    defaults.update(kw)
    return VideoInterview(**defaults)


def _user(role, id_=1):
    return User(id=id_, name="x", email=f"{id_}@x.com", password="p", role=role)


def _app(user_id=1, id_=1):
    return SimpleNamespace(id=id_, user_id=user_id)


def _labeled_session(**session_kw):
    """A plain-namespace session whose application/job/company chain supports
    _detail/_list_out. (Real SQLAlchemy relationships refuse non-mapped
    children, so serialization tests use a namespace instead of the model.)"""
    company = SimpleNamespace(name="Acme Inc")
    job = SimpleNamespace(title="Backend Engineer", company=company)
    application = SimpleNamespace(job=job)
    defaults = dict(
        id=1,
        application_id=2,
        user_id=1,
        status=AssessmentStatusEnum.in_progress,
        camera_enabled=True,
        microphone_enabled=True,
        started_at=datetime(2026, 1, 1, 10, 0, 0),
        ended_at=None,
        created_at=datetime(2026, 1, 1, 10, 0, 0),
        updated_at=datetime(2026, 1, 1, 10, 0, 0),
        application=application,
    )
    defaults.update(session_kw)
    return SimpleNamespace(**defaults)


def _question(**kw):
    """A plain-namespace question mirrored on MockInterviewQuestion so the
    serialization helpers (_question_out/_answered_out reuse) can read it."""
    defaults = dict(
        id=1,
        question_index=0,
        category="technical",
        question_text="Explain the difference between processes and threads.",
        generated_by="llm",
        notice=None,
        question_sources=[],
        answer_text=None,
        score=None,
        correctness=None,
        strengths=None,
        weaknesses=None,
        missing_points=None,
        feedback=None,
        evaluation_generated_by=None,
        evaluation_notice=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


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
        _owned_application(
            FakeSession([_app(user_id=2)]), _user(RoleEnum.user, id_=1), 1
        )
    assert exc.value.status_code == 403


def test_owned_application_owner_allowed():
    app_ = _owned_application(
        FakeSession([_app(user_id=1)]), _user(RoleEnum.user, id_=1), 1
    )
    assert app_.id == 1


def test_owned_session_missing_returns_404():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _owned_session(FakeSession([]), _user(RoleEnum.user), 10)
    assert exc.value.status_code == 404


def test_owned_session_other_users_returns_403():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _owned_session(
            FakeSession([_session(user_id=2, id=10)]),
            _user(RoleEnum.user, id_=1),
            10,
        )
    assert exc.value.status_code == 403


def test_owned_session_owner_allowed():
    session = _owned_session(
        FakeSession([_session(user_id=1, id=10)]),
        _user(RoleEnum.user, id_=1),
        10,
    )
    assert session.id == 10


def test_ensure_live_rejects_completed_session():
    from fastapi import HTTPException

    completed = _session(status=AssessmentStatusEnum.completed)
    with pytest.raises(HTTPException) as exc:
        _ensure_live(completed)
    assert exc.value.status_code == 400


def test_ensure_live_accepts_in_progress_session():
    active = _session(status=AssessmentStatusEnum.in_progress)
    _ensure_live(active)  # must not raise


# ---------------------------------------------------------------------------
# Session lifecycle (service helpers)
# ---------------------------------------------------------------------------

def test_end_session_transitions_in_progress_to_completed():
    session = _session(started_at=datetime(2026, 1, 1, 10, 0, 0))
    assert end_session(session, now=datetime(2026, 1, 1, 10, 45, 0)) is True
    assert session.status == AssessmentStatusEnum.completed
    assert session.ended_at == datetime(2026, 1, 1, 10, 45, 0)


def test_end_session_is_idempotent_and_preserves_ended_at():
    session = _session(
        status=AssessmentStatusEnum.completed,
        ended_at=datetime(2026, 1, 1, 10, 45, 0),
    )
    assert end_session(session, now=datetime(2026, 1, 1, 11, 0, 0)) is False
    assert session.ended_at == datetime(2026, 1, 1, 10, 45, 0)


def test_apply_device_state_updates_toggles():
    session = _session(camera_enabled=True, microphone_enabled=True)
    apply_device_state(session, camera_enabled=False, microphone_enabled=False)
    assert session.camera_enabled is False
    assert session.microphone_enabled is False


def test_session_duration_grows_while_live_and_fixed_when_ended():
    live = _session(started_at=datetime(2026, 1, 1, 10, 0, 0))
    assert (
        session_duration_seconds(live, now=datetime(2026, 1, 1, 10, 2, 30)) == 150
    )
    done = _session(
        started_at=datetime(2026, 1, 1, 10, 0, 0),
        ended_at=datetime(2026, 1, 1, 10, 15, 0),
    )
    assert session_duration_seconds(done, now=datetime(2026, 1, 1, 11, 0, 0)) == 900


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def test_detail_serializes_session_shape():
    out = _detail(
        _labeled_session(
            id=5,
            user_id=1,
            application_id=2,
            camera_enabled=True,
            microphone_enabled=False,
        )
    )
    assert out.id == 5
    assert out.application_id == 2
    assert out.user_id == 1
    assert out.job_title == "Backend Engineer"
    assert out.company_name == "Acme Inc"
    assert out.status == AssessmentStatusEnum.in_progress
    assert out.camera_enabled is True
    assert out.microphone_enabled is False
    assert out.ended_at is None


def test_detail_completed_includes_ended_at():
    out = _detail(
        _labeled_session(
            status=AssessmentStatusEnum.completed,
            ended_at=datetime(2026, 1, 1, 10, 40, 0),
        )
    )
    assert out.status == AssessmentStatusEnum.completed
    assert out.ended_at == datetime(2026, 1, 1, 10, 40, 0)


def test_detail_falls_back_to_none_labels_without_job():
    application = SimpleNamespace(job=None)
    out = _detail(_labeled_session(id=7, application=application))
    assert out.job_title is None
    assert out.company_name is None


def test_list_out_matches_detail_shape_without_user_id():
    out = _list_out(
        _labeled_session(
            id=9,
            status=AssessmentStatusEnum.completed,
            camera_enabled=False,
            microphone_enabled=True,
            ended_at=datetime(2026, 1, 1, 10, 30, 0),
        )
    )
    assert out.id == 9
    assert out.status == AssessmentStatusEnum.completed
    assert out.camera_enabled is False
    assert out.microphone_enabled is True
    assert out.ended_at == datetime(2026, 1, 1, 10, 30, 0)
    assert out.job_title == "Backend Engineer"
    assert out.company_name == "Acme Inc"
    assert not hasattr(out, "user_id")


# ---------------------------------------------------------------------------
# Question state helpers (shared mock_interview_questions rows)
# ---------------------------------------------------------------------------

def test_questions_defaults_to_empty_without_relationship():
    assert _questions(_labeled_session()) == []


def test_questions_orders_by_question_index():
    q2 = _question(id=2, question_index=2)
    q1 = _question(id=1, question_index=1)
    q0 = _question(id=3, question_index=0)
    session = _labeled_session(questions=[q2, q1, q0])
    assert [q.question_index for q in _questions(session)] == [0, 1, 2]


def test_current_question_is_first_unanswered():
    answered = _question(
        id=1,
        question_index=0,
        answer_text="Processes isolate memory; threads share it.",
        score=8,
        evaluation_generated_by="llm",
    )
    pending = _question(id=2, question_index=1)
    session = _labeled_session(questions=[answered, pending])
    assert _current_question(session).id == 2


def test_current_question_none_when_all_answered():
    one = _question(id=1, question_index=0, answer_text="a")
    two = _question(id=2, question_index=1, answer_text="b")
    assert _current_question(_labeled_session(questions=[one, two])) is None


def test_answered_count_counts_only_answered_questions():
    answered = _question(id=1, question_index=0, answer_text="a")
    pending = _question(id=2, question_index=1)
    session = _labeled_session(questions=[answered, pending])
    assert _answered_count(session) == 1


# ---------------------------------------------------------------------------
# Detail serialization with questions
# ---------------------------------------------------------------------------

def test_detail_includes_current_and_answered_questions():
    answered = _question(
        id=1,
        question_index=0,
        answer_text="Processes isolate memory; threads share the heap.",
        score=8,
        correctness="Solid and accurate.",
        strengths=["Correct mental model"],
        weaknesses=["Missing a scheduling detail"],
        missing_points=["Mention context switch cost"],
        feedback="Add one concrete scheduling example.",
        generated_by="llm",
        evaluation_generated_by="llm",
    )
    pending = _question(
        id=2, question_index=1, category="project_experience"
    )
    out = _detail(_labeled_session(questions=[answered, pending]))

    assert out.answered_count == 1
    assert out.max_questions > 0
    assert out.current_question is not None
    assert out.current_question.question_index == 1
    assert out.current_question.category == "project_experience"
    assert len(out.answered) == 1
    assert out.answered[0].question.question_index == 0
    assert out.answered[0].answer == answered.answer_text
    assert out.answered[0].evaluation.score == 8


def test_detail_empty_questions_returns_none_and_empty():
    out = _detail(_labeled_session())
    assert out.current_question is None
    assert out.answered == []
    assert out.answered_count == 0


# ---------------------------------------------------------------------------
# Shared question-row builder reuse
# ---------------------------------------------------------------------------

def test_build_question_row_anchors_to_video_interview():
    from app.services.mock_interview import build_question_row

    row = build_question_row(
        None,
        2,
        "problem_solving",
        {"question_text": "Walk me through a hard bug you fixed."},
        [],
        video_interview_id=10,
    )
    assert row.interview_id is None
    assert row.video_interview_id == 10
    assert row.question_index == 2
    assert row.category == "problem_solving"
    assert row.question_text == "Walk me through a hard bug you fixed."


# ---------------------------------------------------------------------------
# HR mode + final report serialization
# ---------------------------------------------------------------------------

def _completed_hr_with_report():
    """A finished HR session whose report columns are all populated."""
    return _labeled_session(
        interview_type="hr",
        status=AssessmentStatusEnum.completed,
        ended_at=datetime(2026, 1, 1, 10, 40, 0),
        report={
            "overall_score": 8,
            "category_scores": [
                {"category": "communication", "score": 8, "comment": "good"}
            ],
            "strengths": ["Clear communicator"],
            "weaknesses": ["Skips concrete examples"],
            "recommended_topics": ["STAR answers"],
            "summary": "Strong overall fit for the role.",
        },
        overall_score=8,
        category_scores=[
            {"category": "communication", "score": 8, "comment": "good"}
        ],
        strengths=["Clear communicator"],
        weaknesses=["Skips concrete examples"],
        recommended_topics=["STAR answers"],
        summary="Strong overall fit for the role.",
        report_generated_by="llm",
        report_notice=None,
    )


def test_detail_exposes_interview_type_and_hr_report():
    out = _detail(_completed_hr_with_report())
    assert out.interview_type == "hr"
    assert out.status == AssessmentStatusEnum.completed
    assert out.overall_score == 8
    assert out.category_scores[0].category == "communication"
    assert out.strengths == ["Clear communicator"]
    assert out.recommended_topics == ["STAR answers"]
    assert out.summary.startswith("Strong overall fit")
    assert out.report_generated_by == "llm"
    assert out.report_notice is None


def test_detail_technical_default_exposed_and_report_absent_while_live():
    live = _detail(_labeled_session())
    assert live.interview_type == "technical"
    assert live.overall_score is None
    assert live.category_scores == []
    assert live.strengths == []
    assert live.summary == ""
    assert live.report_generated_by == "fallback"
    assert live.report_notice is None


def test_list_out_exposes_type_and_score_only_when_reported():
    live = _list_out(_labeled_session(interview_type="hr"))
    assert live.interview_type == "hr"
    assert live.overall_score is None

    done = _list_out(_completed_hr_with_report())
    assert done.interview_type == "hr"
    assert done.overall_score == 8


def test_reused_hr_report_prompt_matches_mock_interview_persona():
    # HR video sessions reuse the shared HR report persona defined in the mock
    # interview engine so reports are consistent across assessment flavours.
    from app.services.mock_interview import HR_REPORT_SYSTEM_PROMPT

    assert "HR interviewer inside RecruitO" in HR_REPORT_SYSTEM_PROMPT
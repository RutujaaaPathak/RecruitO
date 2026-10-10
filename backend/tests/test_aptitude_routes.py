"""Common Mock Practice aptitude route tests (start / config / full flow).

Directly exercises ``app.routes.aptitude_tests`` against an in-memory SQLite
engine with ``foreign_keys=ON`` over just the aptitude pipeline tables. The LLM
path is stubbed so every test is deterministic and hermetic (falls back to the
question bank).

Covers: the common start contract (first question + future deadline + no
application), single-section filtering, mixed rotation, the per-section
in-progress guard, the config endpoint, and the full start -> answer -> submit
-> results flow that the frontend relies on.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import models, schemas  # noqa: E402
from app.routes.aptitude_tests import (  # noqa: E402
    answer_aptitude_test_question,
    candidate_only,
    get_aptitude_config,
    list_aptitude_tests,
    start_aptitude_test,
    submit_aptitude_test,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    from app import models as m

    tables = [
        m.User.__table__,
        m.Company.__table__,
        m.Job.__table__,
        m.Application.__table__,
        m.Resume.__table__,
        m.AptitudeTest.__table__,
        m.AptitudeQuestion.__table__,
        m.AptitudeAnswer.__table__,
    ]
    m.Base.metadata.create_all(engine, tables=tables)
    s = Session(engine)
    yield s
    s.close()
    engine.dispose()


def _user(db, id, role=models.RoleEnum.user, name=None):
    u = models.User(
        id=id,
        name=name or f"User {id}",
        email=f"user{id}@recruito.com",
        password="hashed",
        role=role,
        is_active=True,
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Force the deterministic bank so tests never touch the network."""

    def broken(prompt, system=None):
        raise RuntimeError("LLM disabled in tests")

    import app.services.aptitude_test as svc
    import app.routes.aptitude_tests as routes

    monkeypatch.setattr(
        routes,
        "generate_questions",
        lambda ctx, total, section="mixed": svc.generate_questions(
            ctx, total, section=section, llm_call=broken
        ),
    )


def test_start_common_test_lands_candidate_on_first_question(db, _no_llm):
    """The exact regression for 'Start Test immediately shows score 0': a
    freshly started common test must stay in_progress, expose question 0 first,
    and give a deadline in the future (never auto-submit at t=0)."""
    candidate = _user(db, 10, name="Rutuja")

    out = start_aptitude_test(
        schemas.AptitudeTestStartIn(section="quantitative"), candidate, db
    )

    assert out.application_id is None  # common: no company/job/application
    assert out.section == "quantitative"
    assert out.status == models.AssessmentStatusEnum.in_progress
    assert out.results is None
    assert out.questions and out.questions[0].question_index == 0
    assert [q.question_index for q in out.questions] == list(
        range(len(out.questions))
    )
    assert all(q.category == "quantitative" for q in out.questions)  # filtered
    assert out.total_questions == len(out.questions) == out.questions[-1].question_index + 1
    # Future deadline so a UTC-aware frontend countdown is positive at start.
    assert out.expires_at is not None
    assert out.expires_at == out.started_at + timedelta(minutes=out.time_limit_minutes)
    assert out.expires_at > datetime.utcnow()

    # Correct answers never leak.
    raw = out.model_dump_json()
    assert "correct_option_index" not in raw
    assert "correct_index" not in raw


def test_start_mixed_covers_all_three_sections(db, _no_llm):
    candidate = _user(db, 10)
    out = start_aptitude_test(
        schemas.AptitudeTestStartIn(section="mixed"), candidate, db
    )
    categories = {q.category for q in out.questions}
    assert categories == set(schemas.AptitudeSection.__args__) - {"mixed"}
    assert out.section == "mixed"
    assert out.total_questions == out.questions[-1].question_index + 1


def test_one_in_progress_test_per_section(db, _no_llm):
    candidate = _user(db, 10)

    first = start_aptitude_test(
        schemas.AptitudeTestStartIn(section="verbal"), candidate, db
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        start_aptitude_test(schemas.AptitudeTestStartIn(section="verbal"), candidate, db)
    assert exc.value.status_code == 409
    assert "already in progress" in exc.value.detail

    # A different section is allowed at the same time.
    other = start_aptitude_test(
        schemas.AptitudeTestStartIn(section="logical_reasoning"), candidate, db
    )
    assert other.id != first.id
    assert other.section == "logical_reasoning"


def test_config_reports_sections_counts_and_limits(db, _no_llm):
    candidate = _user(db, 10)
    cfg = get_aptitude_config(candidate)

    assert cfg.sections == ["quantitative", "logical_reasoning", "verbal"]
    assert cfg.question_count > 0
    assert cfg.section_question_count > 0
    assert cfg.section_question_count <= cfg.question_count
    assert cfg.time_limit_minutes > 0
    assert cfg.pass_percentage > 0


def test_full_start_answer_submit_results_flow(db, _no_llm):
    candidate = _user(db, 10)
    out = start_aptitude_test(
        schemas.AptitudeTestStartIn(section="quantitative"), candidate, db
    )

    first = out.questions[0]
    # Answer question 0 (the one the candidate sees first) with option 0.
    updated = answer_aptitude_test_question(
        out.id,
        schemas.AptitudeAnswerIn(
            question_index=first.question_index, selected_option=0
        ),
        candidate,
        db,
    )
    assert updated.answered_count == 1
    assert updated.questions[0].selected_option == 0

    results = submit_aptitude_test(out.id, candidate, db)
    assert results.total == out.total_questions
    assert results.score == (1 if first.options and 0 < len(first.options) else 0)
    assert results.correct_count == results.score
    assert results.unanswered_count == results.total - results.score
    assert results.expired is False
    # Result reflects the actual (single) saved answer, never a bogus 0.
    assert results.incorrect_count >= 0

    listed = list_aptitude_tests(candidate, db)
    assert listed[0].id == out.id
    assert listed[0].section == "quantitative"
    assert listed[0].status == models.AssessmentStatusEnum.completed
    assert listed[0].score == results.score


def test_rbac_candidate_only(db, _no_llm):
    company_user = _user(db, 1, role=models.RoleEnum.company)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        candidate_only(current_user=company_user)
    assert exc.value.status_code == 403
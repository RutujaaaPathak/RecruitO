"""Tests for the Phase-2 RAG chatbot: LLM text call, grounding prompt, RBAC,
persistence, fallback, and no-hallucination guarantees (hermetic, no DB / API).
"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.auth import RoleChecker  # noqa: E402
from app.models import (  # noqa: E402
    Application,
    ApplicationStatusEnum,
    ChatMessage,
    ChatSession,
    RoleEnum,
    User,
)
from app.routes.chat import _owned_application, _owned_session  # noqa: E402
from app.services import llm_client  # noqa: E402
from app.services.rag_chat import (  # noqa: E402
    ChatContext,
    FALLBACK_NOTICE,
    SYSTEM_PROMPT,
    build_context_section,
    build_grounding_prompt,
    generate_chat_reply,
    run_chat_turn,
    title_from_message,
)
from app.services.resume_retriever import RetrievedChunk  # noqa: E402

RESUME = (
    "Sara Chen. Python developer with Django, PostgreSQL and Docker experience. "
    "Built REST APIs on AWS and deployed microservices."
)
JOB_TITLE = "Backend Engineer"
JOB_COMPANY = "Acme Inc"
JOB_SKILLS = ["python", "django", "aws", "kubernetes"]
JOB_DESC = "Backend engineer. Requires Python, Django, AWS and Kubernetes experience."
CHUNKS = [
    RetrievedChunk(chunk_id=1, chunk_index=0, section="experience", score=88,
                   content="Built Django REST APIs on AWS with PostgreSQL."),
    RetrievedChunk(chunk_id=2, chunk_index=1, section="skills", score=40,
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
    )
    base.update(overrides)
    return ChatContext(**base)


def _conversation(*turns):
    return [{"role": r, "content": c} for r, c in turns]


# ---------------------------------------------------------------------------
# generate_text() on the LLM client (generate_json stays JSON-only)
# ---------------------------------------------------------------------------

def test_generate_text_no_key_raises_not_configured(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(llm_client.LLMNotConfigured):
        llm_client.generate_text("hi")


def test_generate_text_http_error_raises_llm_error(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    class FakeResp:
        status_code = 429
        text = "rate limited"

        def raise_for_status(self):
            from httpx import HTTPStatusError, Request

            raise HTTPStatusError(
                "429 Too Many Requests",
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
        llm_client.generate_text("hi")


def test_generate_text_returns_raw_text(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "Hello! This is a plain answer."}}]
            }

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
    assert llm_client.generate_text("hi") == "Hello! This is a plain answer."


# ---------------------------------------------------------------------------
# Grounding: system prompt + context + prompt builder
# ---------------------------------------------------------------------------

def test_system_prompt_forbids_hallucination_and_stays_in_domain():
    lower = SYSTEM_PROMPT.lower()
    assert "never invent" in lower
    assert "only in the supplied context" in lower
    assert "not present in the supplied resume" in lower
    assert "say so plainly" in lower
    assert "stay within resume, jobs, applications, interviews, skills and career topics" in lower


def test_build_context_section_includes_resume_and_job():
    section = build_context_section(_ctx())
    assert "Sara Chen" in section
    assert "sara@example.com" in section
    assert "LATEST RESUME TEXT" in section and "PostgreSQL" in section
    assert JOB_TITLE in section and "Acme Inc" in section
    assert "ats match score: 62" in section.lower()
    assert "71" in section
    assert "Built Django REST APIs on AWS" in section  # retrieved chunk grounded


def test_build_context_section_handles_no_resume_and_no_job():
    ctx = _ctx(resume_text=None, job_title=None, job_company=None,
               job_skills=[], job_description=None, retrieved_chunks=[],
               ats_score=None, semantic_score=None)
    section = build_context_section(ctx)
    assert "(none uploaded)" in section
    assert "(none — the candidate did not select a job)" in section


def test_build_grounding_prompt_includes_history_and_question():
    conversation = _conversation(
        ("user", "Do I match this job?"),
        ("assistant", "You match Python/Django."),
        ("user", "Should I apply for Kubernetes roles?"),
    )
    prompt = build_grounding_prompt(_ctx(), conversation)
    assert "Do I match this job?" in prompt
    assert "You match Python/Django." in prompt
    assert "Should I apply for Kubernetes roles?" in prompt
    assert "SUPPLIED CONTEXT" in prompt


def test_build_grounding_prompt_caps_history_length():
    turns = [{"role": "user", "content": f"turn{i}"} for i in range(30)]
    prompt = build_grounding_prompt(_ctx(), turns)
    # Only the most recent turns are included.
    assert "turn0" not in prompt
    assert "turn29" in prompt


# ---------------------------------------------------------------------------
# Sources returned with the assistant reply
# ---------------------------------------------------------------------------

def test_generate_chat_reply_llm_path_returns_sources():
    def fake_llm(prompt, system=None):
        # System prompt is the strict grounding prompt; user content is grounded.
        assert system == SYSTEM_PROMPT
        assert "Sara Chen" in prompt and "PostgreSQL" in prompt
        return "Focus on Kubernetes next."

    result = generate_chat_reply(_ctx(), _conversation(("user", "Hi")), llm_call=fake_llm)
    assert result["generated_by"] == "llm"
    assert result["reply"] == "Focus on Kubernetes next."
    assert result["notice"] is None
    assert result["model_used"] == "all-MiniLM-L6-v2"
    assert len(result["sources"]) == 2
    assert result["sources"][0]["chunk_id"] == 1
    assert result["sources"][0]["section"] == "experience"


def test_sources_content_capped():
    import app.services.rag_chat as rag_chat
    long_chunk = RetrievedChunk(chunk_id=9, chunk_index=0, section="general",
                                score=10, content="x" * 5000)
    sources = rag_chat._to_sources([long_chunk])
    assert len(sources[0]["content"]) <= 2000


# ---------------------------------------------------------------------------
# Fallback on LLM failure (keeps grounding)
# ---------------------------------------------------------------------------

def test_fallback_on_llm_error_is_grounded():
    def broken_llm(prompt, system=None):
        raise RuntimeError("connection refused")

    result = generate_chat_reply(_ctx(), _conversation(("user", "Am I a fit?")), llm_call=broken_llm)
    assert result["generated_by"] == "fallback"
    assert "connection refused" in result["notice"]
    assert FALLBACK_NOTICE in result["notice"]
    assert len(result["sources"]) == 2
    # Fallback only mentions facts from the context: no invented skills.
    reply_lower = result["reply"].lower()
    assert "kubernetes" in reply_lower  # required but missing, from context
    assert "python" in reply_lower      # matched, from the resume
    for invented in ("machine learning", "rust", "blockchain"):
        assert invented not in reply_lower


def test_fallback_default_llm_unconfigured(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    result = generate_chat_reply(_ctx(), _conversation(("user", "Hi")))
    assert result["generated_by"] == "fallback"
    assert "LLM_API_KEY" in result["notice"]


def test_fallback_with_no_resume_does_not_invent_experience():
    ctx = _ctx(resume_text=None, job_title=None, job_description=None,
               job_skills=[], retrieved_chunks=[], ats_score=None, semantic_score=None)
    result = generate_chat_reply(ctx, _conversation(("user", "Am I experienced?")),
                                 llm_call=lambda p, system=None: (_ for _ in ()).throw(RuntimeError("down")))
    assert result["generated_by"] == "fallback"
    assert "no resume uploaded" in result["reply"]
    assert "AWS" not in result["reply"]


# ---------------------------------------------------------------------------
# Persistence of every user and assistant message
# ---------------------------------------------------------------------------

class FakeDB:
    def __init__(self):
        self.added = []

    def add(self, row):
        self.added.append(row)

    def flush(self):
        return None

    def commit(self):
        return None


def test_run_chat_turn_persists_user_and_assistant_messages():
    db = FakeDB()
    session = ChatSession(id=55, user_id=1)

    assistant_row, user_row, meta = run_chat_turn(
        db, session, "Am I a good fit?", _ctx(),
        llm_call=lambda prompt, system=None: "Yes, especially Django."
    )

    assert len(db.added) == 2
    assert isinstance(user_row, ChatMessage) and user_row.role == "user"
    assert user_row.content == "Am I a good fit?"
    assert isinstance(assistant_row, ChatMessage) and assistant_row.role == "assistant"
    assert assistant_row.content == "Yes, especially Django."
    assert assistant_row.generated_by == "llm"
    assert assistant_row.model_used == "all-MiniLM-L6-v2"
    assert assistant_row.sources == meta["sources"]


def test_run_chat_turn_persists_assistant_fallback_metadata():
    db = FakeDB()
    session = ChatSession(id=1, user_id=1)
    assistant_row, _user_row, result = run_chat_turn(
        db, session, "Hi", _ctx(),
        llm_call=lambda prompt, system=None: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert result["generated_by"] == "fallback"
    assert assistant_row.generated_by == "fallback"
    assert "boom" in assistant_row.content or "LLM" in result["notice"] or "boom" in result["notice"]
    assert isinstance(assistant_row.sources, list)


def test_run_chat_turn_history_reaches_prompt():
    db = FakeDB()
    session = ChatSession(id=1, user_id=1)
    history = _conversation(
        ("user", "What should I learn?"),
        ("assistant", "Try Kubernetes."),
    )

    captured = {}

    def fake_llm(prompt, system=None):
        captured["prompt"] = prompt
        return "ok"

    session.messages = [
        ChatMessage(id=1, session_id=1, role=t["role"], content=t["content"])
        for t in history
    ]
    run_chat_turn(db, session, "Tell me more", _ctx(), llm_call=fake_llm)
    assert "What should I learn?" in captured["prompt"]
    assert "Try Kubernetes." in captured["prompt"]


def test_title_from_message_truncates():
    assert title_from_message("  Am I a good fit?  ") == "Am I a good fit?"
    t = title_from_message("x" * 200)
    assert len(t) <= 60 and t.endswith("...")


# ---------------------------------------------------------------------------
# RBAC / ownership + authentication role gate
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


def _application(user_id=1, id_=10):
    app = Application(id=id_, job_id=5, user_id=user_id,
                      status=ApplicationStatusEnum.applied)
    return app


from fastapi import HTTPException


def test_role_checker_blocks_non_candidates():
    assert RoleChecker(["user"])(current_user=_user(RoleEnum.user)) is not None
    with pytest.raises(HTTPException) as exc:
        RoleChecker(["user"])(current_user=_user(RoleEnum.company))
    assert exc.value.status_code == 403


def test_owned_application_missing_returns_404():
    with pytest.raises(HTTPException) as exc:
        _owned_application(FakeSession([]), _user("user"), 10)
    assert exc.value.status_code == 404


def test_owned_application_other_users_returns_403():
    with pytest.raises(HTTPException) as exc:
        _owned_application(FakeSession([_application(user_id=2)]), _user("user", id_=1), 10)
    assert exc.value.status_code == 403


def test_owned_application_owner_allowed():
    app = _owned_application(FakeSession([_application(user_id=1)]), _user("user", id_=1), 10)
    assert app.user_id == 1


def test_owned_session_missing_returns_404():
    with pytest.raises(HTTPException) as exc:
        _owned_session(FakeSession([]), _user("user"), 3)
    assert exc.value.status_code == 404


def test_owned_session_other_users_returns_403():
    other = ChatSession(id=3, user_id=2)
    with pytest.raises(HTTPException) as exc:
        _owned_session(FakeSession([other]), _user("user", id_=1), 3)
    assert exc.value.status_code == 403


def test_owned_session_owner_allowed():
    mine = ChatSession(id=3, user_id=1)
    session = _owned_session(FakeSession([mine]), _user("user", id_=1), 3)
    assert session.id == 3
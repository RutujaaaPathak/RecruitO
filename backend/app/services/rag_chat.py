# pyrefly: ignore [missing-import]
"""AI Chatbot service: strictly grounded RAG chat over RecruitO candidate data.

The chatbot is NOT a general-purpose assistant. Every reply is grounded in:
  - the authenticated candidate's profile
  - their latest parsed resume
  - resume chunks retrieved with the Phase-1 pgvector/keyword RAG index
  - the selected application and its related job (title, skills, description)
  - ATS / semantic scores where available
  - the recent conversation history

The model is told never to invent candidate facts and to stay within career /
recruitment topics. On any LLM failure (not configured, network error, empty
reply) a deterministic reply is built from the available context and returned,
mirroring the career-recommendations fallback.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import Application, ChatMessage, ChatSession, Resume, User
from app.services import llm_client, semantic_matcher
from app.services.career_recommendations import _safe_reason
from app.services.resume_retriever import (
    DEFAULT_TOP_K,
    retrieve_chunks_for_job,
)
from app.services.skill_gap import analyze_skill_gap

SYSTEM_PROMPT = """You are RecruitO AI, a career assistant inside RecruitO, an ATS/
recruitment platform. You answer candidates' questions about their resume, jobs,
skill gaps, applications, interviews and career planning.

STRICT GROUNDING RULES — follow them without exception:
1. Ground every answer ONLY in the SUPPLIED CONTEXT below: the candidate
   profile, resume, retrieved resume sections, job posting, scores and the
   conversation history. NEVER INVENT, guess or assume any candidate fact.
2. Never claim the candidate has a skill, project, experience, degree or
   achievement that is not present in the supplied resume/context.
3. Never quote a company, salary, deadline, requirement or detail that is not
   in the supplied job information.
4. If the answer to a question is not available in the context, say so plainly
   (e.g. "that information isn't in your resume/application context") instead
   of guessing or making something up.
5. Stay within resume, jobs, applications, interviews, skills and career topics.
   If asked anything else, politely say that you only help with career and
   RecruitO topics.
6. Be concise, helpful and specific to THIS candidate's data. Do not produce
   generic boilerplate when the context allows a personalized answer.
"""

# How much of the parsed resume to embed in the prompt (token budgeting).
RESUME_MAX_CHARS = 8000
# How many recent messages (user+assistant) are sent to the model.
HISTORY_LIMIT = 10

FALLBACK_NOTICE = (
    "The AI model is unavailable right now, so this answer is a grounded "
    "summary built only from your RecruitO data."
)


@dataclass
class ChatContext:
    """Everything about a candidate and their selected application that the
    chatbot is allowed to use. Assembled server-side; never supplied by the
    frontend."""

    user_name: str
    user_email: str
    profile_skills: List[str] = field(default_factory=list)
    resume_text: Optional[str] = None
    job_title: Optional[str] = None
    job_company: Optional[str] = None
    job_skills: List[str] = field(default_factory=list)
    job_description: Optional[str] = None
    ats_score: Optional[int] = None
    semantic_score: Optional[int] = None
    retrieved_chunks: List = field(default_factory=list)
    model_used: str = "none"
    used_fallback: bool = False


# ---------------------------------------------------------------------------
# Context assembly (server-side only)
# ---------------------------------------------------------------------------

def resolve_chat_context(
    db: Session, user: User, application: Optional[Application]
) -> ChatContext:
    """Build the grounded context for a candidate and (optional) application."""
    resume = None
    if user is not None:
        resume = (
            db.query(Resume)
            .filter(Resume.user_id == user.id)
            .order_by(Resume.uploaded_at.desc())
            .first()
        )

    ctx = ChatContext(
        user_name=(user.name if user else "Candidate"),
        user_email=(user.email if user else ""),
        profile_skills=list((user.skills or [])) if user and user.skills else [],
    )

    if resume is not None:
        ctx.resume_text = (resume.parsed_text or "").strip() or None

    if application is not None:
        job = application.job
        ctx.ats_score = application.match_score
        if job is not None:
            ctx.job_title = job.title
            ctx.job_company = job.company.name if job.company else None
            ctx.job_skills = list(job.skills or [])
            ctx.job_description = (job.description or "").strip() or None

        if ctx.resume_text and ctx.job_description:
            try:
                ctx.semantic_score = semantic_matcher.compute_semantic_score(
                    ctx.resume_text, ctx.job_description
                ).score
            except Exception:
                ctx.semantic_score = None
            retrieved_chunks, model_used, used_fallback = retrieve_chunks_for_job(
                db, resume, ctx.job_description, top_k=DEFAULT_TOP_K
            )
            ctx.retrieved_chunks = retrieved_chunks
            ctx.model_used = model_used
            ctx.used_fallback = used_fallback

    return ctx


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_context_section(ctx: ChatContext) -> str:
    """Render the grounded context block injected into the system prompt."""
    parts: List[str] = []
    parts.append(f"CANDIDATE NAME: {ctx.user_name}")
    parts.append(f"CANDIDATE EMAIL: {ctx.user_email}")

    profile_skills = ", ".join(ctx.profile_skills) if ctx.profile_skills else "None listed"
    parts.append(f"CANDIDATE PROFILE SKILLS: {profile_skills}")

    if ctx.resume_text:
        resume = ctx.resume_text
        if len(resume) > RESUME_MAX_CHARS:
            resume = resume[:RESUME_MAX_CHARS] + "\n[resume truncated]"
        parts.append(f"LATEST RESUME TEXT:\n{resume}")
    else:
        parts.append("LATEST RESUME TEXT: (none uploaded)")

    if ctx.retrieved_chunks:
        chunk_lines = []
        for index, chunk in enumerate(ctx.retrieved_chunks, start=1):
            section = getattr(chunk, "section", None) or f"chunk {index}"
            content = getattr(chunk, "content", "") or ""
            chunk_lines.append(f"--- Resume section: {section} ---\n{content}")
        parts.append(
            "RETRIEVED RESUME SECTIONS (most relevant to the selected job):\n"
            + "\n\n".join(chunk_lines)
        )

    if ctx.job_title or ctx.job_description:
        parts.append(f"SELECTED JOB TITLE: {ctx.job_title or 'N/A'}")
        parts.append(
            "SELECTED JOB COMPANY: "
            + (ctx.job_company or "N/A")
        )
        parts.append(
            "SELECTED JOB REQUIRED SKILLS: "
            + (", ".join(ctx.job_skills) if ctx.job_skills else "None listed")
        )
        parts.append(
            "SELECTED JOB DESCRIPTION:\n" + (ctx.job_description or "N/A")
        )
    else:
        parts.append("SELECTED APPLICATION: (none — the candidate did not select a job)")

    parts.append(f"ATS MATCH SCORE: {ctx.ats_score if ctx.ats_score is not None else 'N/A'}")
    parts.append(
        "SEMANTIC SCORE: "
        + (str(ctx.semantic_score) if ctx.semantic_score is not None else "N/A")
    )
    return "\n\n".join(parts)


def build_grounding_prompt(
    ctx: ChatContext, conversation: List[Dict[str, str]]
) -> str:
    """Compose the user-content portion of the chat turn.

    The strict ``SYSTEM_PROMPT`` is sent in the system role by the caller; this
    returns the grounded context + recent history + the latest question that the
    model must answer from.
    """
    history_lines = []
    recent = conversation[-(HISTORY_LIMIT):]
    for turn in recent:
        role = "CANDIDATE" if turn.get("role") == "user" else "AI_ASSISTANT"
        history_lines.append(f"{role}: {turn.get('content', '')}")
    history_block = "\n".join(history_lines) if history_lines else "(no previous messages)"

    user_message = conversation[-1]["content"] if conversation else ""

    return f"""SUPPLIED CONTEXT (the ONLY facts you may use):

{build_context_section(ctx)}

CONVERSATION HISTORY (most recent):
{history_block}

CANDIDATE QUESTION:
{user_message}
"""


# ---------------------------------------------------------------------------
# Reply generation
# ---------------------------------------------------------------------------

def _to_sources(retrieved_chunks: Optional[List]) -> List[Dict[str, Any]]:
    """Serialize retrieved chunks into source references (capped content)."""
    sources = []
    for chunk in retrieved_chunks or []:
        section = getattr(chunk, "section", None)
        sources.append(
            {
                "chunk_id": getattr(chunk, "chunk_id", None),
                "chunk_index": getattr(chunk, "chunk_index", 0),
                "section": section,
                "score": getattr(chunk, "score", None),
                "content": (getattr(chunk, "content", "") or "")[:2000],
            }
        )
    return sources


def _fallback_reply(
    ctx: ChatContext, conversation: List[Dict[str, str]]
) -> str:
    """Deterministic, fully grounded reply used when the LLM is unavailable.

    Uses only the supplied context: skill-gap analysis for the selected job,
    profile skills, retrieved resume sections and stored scores.
    """
    matched: List[str] = []
    missing: List[str] = []

    if ctx.resume_text and (ctx.job_skills or ctx.job_description):
        gap = analyze_skill_gap(
            ctx.resume_text, ctx.job_skills or [], ctx.job_description or ""
        )
        matched = [s for s in gap.matched_skills]
        missing = [m.skill for m in gap.missing_skills]

    lines: List[str] = []
    lines.append(
        "Note: the AI model is unavailable right now, so this is a grounded "
        "summary based only on your RecruitO data."
    )

    if not ctx.resume_text:
        lines.append(
            "Your profile has no resume uploaded yet, so I can't comment on "
            "your experience or skills. Upload a resume to get personalized help."
        )
    else:
        if ctx.job_title:
            company = f" at {ctx.job_company}" if ctx.job_company else ""
            lines.append(f"Selected job: {ctx.job_title}{company}.")
        if matched:
            lines.append(
                "Skills from your resume that match this job: "
                + ", ".join(matched) + "."
            )
        if missing:
            lines.append(
                "Skills this job asks for that aren't clearly in your resume: "
                + ", ".join(missing) + ". Consider adding any relevant "
                "experience with these to your resume."
            )
        if not matched and not missing:
            lines.append(
                "I could not compare your resume to this job's requirements "
                "because the job has no listed skills or description."
            )
        scores = []
        if ctx.ats_score is not None:
            scores.append(f"ATS match score: {ctx.ats_score}/100")
        if ctx.semantic_score is not None:
            scores.append(f"semantic similarity: {ctx.semantic_score}/100")
        if scores:
            lines.append("Your existing scores: " + "; ".join(scores) + ".")

    lines.append(
        "Please try again in a moment for a richer, personalized answer."
    )
    return " ".join(lines)


def generate_chat_reply(
    ctx: ChatContext,
    conversation: List[Dict[str, str]],
    llm_call=None,
) -> Dict[str, Any]:
    """Produce a grounded assistant reply for the current conversation.

    `conversation` is a list of {"role": "user"|"assistant", "content": str}
    turns; the last item is the candidate's newest question. `llm_call` is
    injectable for tests and defaults to the production `generate_text`.

    Returns:
        {
          "reply": str,
          "generated_by": "llm" | "fallback",
          "notice": Optional[str],
          "sources": List[dict],
          "model_used": str,
        }
    """
    if llm_call is None:
        llm_call = llm_client.generate_text

    sources = _to_sources(ctx.retrieved_chunks)
    try:
        prompt = build_grounding_prompt(ctx, conversation)
        reply = llm_call(prompt, system=SYSTEM_PROMPT)
        if not reply or not str(reply).strip():
            raise ValueError("LLM returned an empty reply.")
        reply = str(reply).strip()
        return {
            "reply": reply,
            "generated_by": "llm",
            "notice": None,
            "sources": sources,
            "model_used": ctx.model_used or "none",
        }
    except Exception as exc:
        return {
            "reply": _fallback_reply(ctx, conversation),
            "generated_by": "fallback",
            "notice": f"{FALLBACK_NOTICE} ({_safe_reason(exc)})",
            "sources": sources,
            "model_used": ctx.model_used or "none",
        }


# ---------------------------------------------------------------------------
# Persistence (one turn = one user message + one assistant message)
# ---------------------------------------------------------------------------

def run_chat_turn(
    db: Session,
    session: ChatSession,
    user_message: str,
    ctx: ChatContext,
    llm_call=None,
):
    """Persist the candidate's message, generate a grounded reply and persist it.

    Returns (assistant_row, user_row, result) where `result` is the dict from
    ``generate_chat_reply``. Never raises on LLM failure (falls back).
    """
    history = [
        {"role": m.role, "content": m.content}
        for m in (session.messages or [])
    ]
    history.append({"role": "user", "content": user_message})

    user_row = ChatMessage(session_id=session.id, role="user", content=user_message)
    db.add(user_row)
    db.flush()

    result = generate_chat_reply(ctx, history, llm_call=llm_call)

    assistant_row = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=result["reply"],
        sources=result["sources"] or None,
        model_used=result["model_used"],
        generated_by=result["generated_by"],
    )
    db.add(assistant_row)
    return assistant_row, user_row, result


def title_from_message(user_message: str, max_len: int = 60) -> str:
    """A short session title from the first user message."""
    cleaned = " ".join((user_message or "").split())
    if not cleaned:
        return "Chat"
    return cleaned if len(cleaned) <= max_len else cleaned[: max_len - 3] + "..."
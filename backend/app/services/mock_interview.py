# pyrefly: ignore [missing-import]
"""AI Mock Interview service: grounded, text-based mock interviews.

Runs a structured mock interview for a candidate against one of their
applications (and therefore a real job posting). The interview is grounded ONLY
in the candidate's actual data:

  - the authenticated candidate's profile
  - their latest parsed resume
  - resume chunks retrieved with the RAG index (pgvector / keyword)
  - the selected application and its job (title, skills, description)
  - ATS / semantic scores and the skill-gap snapshot where available

The interview rotates question categories by type (technical mode: technical ->
project_experience -> problem_solving -> behavioral; HR mode: communication ->
work_experience -> motivation -> behavioral), adapts follow-ups to the
candidate's previous answer, and evaluates every answer 0-10. On any LLM
failure each stage (question generation, evaluation, final report) degrades to
a deterministic, fully grounded rule-based fallback so the interview always
works.

This module deliberately does NOT import the RAG chatbot service. It
assembles its own small context block from the shared low-level helpers so the
mock interview stays decoupled from the chatbot.
"""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import (
    Application,
    MockInterviewQuestion,
    Resume,
    User,
)
from app.services import llm_client, semantic_matcher
from app.services.resume_retriever import (
    DEFAULT_TOP_K,
    retrieve_chunks_for_job,
)
from app.services.skill_gap import analyze_skill_gap

# Categories, rotated in this exact order for every interview.
# Technical mode: technical + career/job-focused behavioural questions.
CATEGORIES = ["technical", "project_experience", "problem_solving", "behavioral"]

# HR mode: behavioural soft-skills / fit questions drawn from the candidate's
# real work history and profile (never invented by the model).
HR_CATEGORIES = ["communication", "work_experience", "motivation", "behavioral"]

DEFAULT_MAX_QUESTIONS = 8

# How much of the parsed resume to embed in prompts (token budgeting).
RESUME_MAX_CHARS = 8000
# Evaluation prompts get a tighter resume excerpt.
EVAL_RESUME_MAX_CHARS = 4000

FALLBACK_NOTICE = (
    "The AI model is unavailable right now, so this is a deterministic "
    "rule-based fallback grounded only in your RecruitO data."
)

QUESTION_SYSTEM_PROMPT = """You are a senior technical interviewer inside RecruitO, an
ATS/recruitment platform. Your ONLY job is to generate ONE realistic interview
question for a candidate applying to a specific role. Respond with ONLY valid
JSON in this exact shape: {"question": string}

STRICT GROUNDING RULES — follow them without exception:
1. Generate a question that is answerable from the candidate's ACTUAL background
   in the SUPPLIED CONTEXT. Ask only about skills, projects, technologies,
   education and experiences that appear in the supplied resume text or the
   retrieved resume sections, or that are explicitly required by the supplied job.
2. NEVER ask about a skill, technology, project, company, degree or achievement
   that is not present in the supplied context.
3. Never assert invented facts about the candidate (do not write things like
   "you have 5 years at Google" or "in your portfolio"). Phrase questions so the
   candidate can describe their own, real experience (e.g. "Describe a project
   from your resume where you used X").
4. The question must match the requested CATEGORY. If the category cannot be
   grounded in a specific resume detail, still ask a general question in that
   category that asks the candidate to describe their own experience — without
   inventing anything.
5. Keep the question 1-3 sentences, specific, and answerable in a text
   interview. Do not include the answer, hints, or evaluation criteria."""

EVALUATION_SYSTEM_PROMPT = """You are a senior technical interviewer and evaluator inside
RecruitO. Evaluate ONE candidate answer to ONE interview question. Respond with
ONLY valid JSON in this exact shape:
{
  "score": int (0-10),
  "correctness": string,
  "strengths": [string],
  "weaknesses": [string],
  "missing_points": [string],
  "feedback": string
}

GROUNDING RULES — follow them without exception:
1. Evaluate ONLY the supplied question and the candidate's answer. Do not
   evaluate against experience that is not in the answer.
2. score is 0-10 based on correctness, relevance and completeness relative to
   the supplied rubric/context. Be fair; an empty or off-topic answer scores low.
3. strengths, weaknesses and missing_points: 0-4 concise items each.
4. feedback: 1-2 sentences of concise, actionable improvement advice."""

REPORT_SYSTEM_PROMPT = """You are a senior technical interviewer inside RecruitO. Produce
a final mock-interview report from the candidate's answered questions. Respond
with ONLY valid JSON in this exact shape:
{
  "overall_score": int (0-10),
  "category_scores": [{"category": string, "score": int (0-10), "comment": string}],
  "strengths": [string],
  "weaknesses": [string],
  "recommended_topics": [string],
  "summary": string
}

GROUNDING RULES — follow them without exception:
1. Base every score, strength, weakness and recommendation ONLY on the supplied
   per-question evaluations and the supplied context. Never invent candidate
   experience or skills.
2. overall_score should reflect the supplied aggregate scores.
3. recommended_topics are topics to prepare next; ground them in the supplied
   missing skills and the weakest categories.
4. Keep lists concise (2-5 items)."""

HR_QUESTION_SYSTEM_PROMPT = """You are an HR interviewer inside RecruitO, an ATS/recruitment
platform. Your ONLY job is to generate ONE realistic HR/soft-skills interview
question for a candidate applying to a specific role. Respond with ONLY valid
JSON in this exact shape: {"question": string}

STRICT GROUNDING RULES — follow them without exception:
1. Generate a question that is answerable from the candidate's ACTUAL background
   in the SUPPLIED CONTEXT (their resume, profile and the selected job). Ask only
   about experiences, projects, roles and motivations that appear in the context.
2. NEVER ask about a skill, role, achievement or motivation that is not present
   in the supplied context, and never assert invented facts about the candidate.
3. Phrase questions so the candidate can describe their own, real experience
   (e.g. "Describe a time you communicated a technical topic to a non-technical
   audience" rather than "you have strong presentation skills").
4. The question must match the requested CATEGORY. If the category cannot be
   grounded in a specific context detail, still ask a general question in that
   category that asks the candidate to describe their own experience — without
   inventing anything.
5. Keep the question 1-3 sentences, specific, and answerable in a text
   interview. Do not include evaluation criteria or hints."""

HR_EVALUATION_SYSTEM_PROMPT = """You are an HR interviewer and evaluator inside RecruitO.
Evaluate ONE candidate answer to ONE HR/soft-skills interview question. Respond
with ONLY valid JSON in this exact shape:
{
  "score": int (0-10),
  "correctness": string,
  "strengths": [string],
  "weaknesses": [string],
  "missing_points": [string],
  "feedback": string
}

GROUNDING RULES — follow them without exception:
1. Evaluate ONLY the supplied question and the candidate's answer. Do not
   evaluate against experience that is not in the answer.
2. score is 0-10 based on relevance, communication quality and completeness
   relative to the supplied context. Be fair; an empty or off-topic answer
   scores low.
3. strengths, weaknesses and missing_points: 0-4 concise items each.
4. feedback: 1-2 sentences of concise, actionable improvement advice."""

HR_REPORT_SYSTEM_PROMPT = """You are an HR interviewer inside RecruitO. Produce a final
candidate-fit report from the candidate's answered HR interview questions.
Respond with ONLY valid JSON in this exact shape:
{
  "overall_score": int (0-10),
  "category_scores": [{"category": string, "score": int (0-10), "comment": string}],
  "strengths": [string],
  "weaknesses": [string],
  "recommended_topics": [string],
  "summary": string
}

GROUNDING RULES — follow them without exception:
1. Base every score, strength, weakness and recommendation ONLY on the supplied
   per-question evaluations and the supplied context. Never invent candidate
   experience or motivations.
2. overall_score should reflect the supplied aggregate scores.
3. recommended_topics are areas for the candidate to prepare next.
4. Keep lists concise (2-5 items)."""


# ---------------------------------------------------------------------------
# Context assembly (server-side only; decided by the candidate's data)
# ---------------------------------------------------------------------------

@dataclass
class InterviewContext:
    """Everything about a candidate and their selected application that the
    mock interview is allowed to use. Assembled server-side; never supplied by
    the frontend."""

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
    matched_skills: List[str] = field(default_factory=list)
    missing_skills: List[str] = field(default_factory=list)


def resolve_interview_context(
    db: Session, user: User, application: Optional[Application]
) -> InterviewContext:
    """Build the grounded context for a candidate and their application."""
    resume = None
    if user is not None:
        resume = (
            db.query(Resume)
            .filter(Resume.user_id == user.id)
            .order_by(Resume.uploaded_at.desc())
            .first()
        )

    ctx = InterviewContext(
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

        if ctx.resume_text and (ctx.job_skills or ctx.job_description):
            gap = analyze_skill_gap(
                ctx.resume_text, ctx.job_skills or [], ctx.job_description or ""
            )
            ctx.matched_skills = list(gap.matched_skills)
            ctx.missing_skills = [s.skill for s in gap.missing_skills]

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


def _resume_excerpt(ctx: InterviewContext, max_chars: int = RESUME_MAX_CHARS) -> str:
    if not ctx.resume_text:
        return "(none uploaded)"
    text = ctx.resume_text
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[resume truncated]"
    return text


def build_context_section(ctx: InterviewContext) -> str:
    """Render the grounded context block injected into LLM prompts."""
    parts: List[str] = []
    parts.append(f"CANDIDATE NAME: {ctx.user_name}")
    parts.append(f"CANDIDATE EMAIL: {ctx.user_email}")

    profile_skills = ", ".join(ctx.profile_skills) if ctx.profile_skills else "None listed"
    parts.append(f"CANDIDATE PROFILE SKILLS: {profile_skills}")

    resume = _resume_excerpt(ctx)
    parts.append(f"LATEST RESUME TEXT:\n{resume}")

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

    parts.append(f"SELECTED JOB TITLE: {ctx.job_title or 'N/A'}")
    parts.append("SELECTED JOB COMPANY: " + (ctx.job_company or "N/A"))
    parts.append(
        "SELECTED JOB REQUIRED SKILLS: "
        + (", ".join(ctx.job_skills) if ctx.job_skills else "None listed")
    )
    parts.append(
        "SELECTED JOB DESCRIPTION:\n" + (ctx.job_description or "N/A")
    )

    parts.append(f"ATS MATCH SCORE: {ctx.ats_score if ctx.ats_score is not None else 'N/A'}")
    parts.append(
        "SEMANTIC SCORE: "
        + (str(ctx.semantic_score) if ctx.semantic_score is not None else "N/A")
    )
    parts.append(
        "JOB SKILLS ALREADY IN THE RESUME: "
        + (", ".join(ctx.matched_skills) if ctx.matched_skills else "None")
    )
    parts.append(
        "JOB SKILLS MISSING FROM THE RESUME: "
        + (", ".join(ctx.missing_skills) if ctx.missing_skills else "None")
    )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Sources (normalized RAG chunk references, capped content)
# ---------------------------------------------------------------------------

def _to_sources(retrieved_chunks: Optional[List]) -> List[Dict[str, Any]]:
    sources = []
    for chunk in retrieved_chunks or []:
        if isinstance(chunk, dict):
            sources.append(
                {
                    "chunk_id": chunk.get("chunk_id") or 0,
                    "chunk_index": chunk.get("chunk_index", 0),
                    "section": chunk.get("section"),
                    "score": chunk.get("score"),
                    "content": (chunk.get("content") or "")[:2000],
                }
            )
        else:
            sources.append(
                {
                    "chunk_id": getattr(chunk, "chunk_id", None) or 0,
                    "chunk_index": getattr(chunk, "chunk_index", 0),
                    "section": getattr(chunk, "section", None),
                    "score": getattr(chunk, "score", None),
                    "content": (getattr(chunk, "content", "") or "")[:2000],
                }
            )
    return sources


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def max_questions() -> int:
    """Return the configured question cap (MOCK_INTERVIEW_MAX_QUESTIONS)."""
    raw = os.getenv("MOCK_INTERVIEW_MAX_QUESTIONS", str(DEFAULT_MAX_QUESTIONS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_QUESTIONS
    return max(1, min(30, value))


def interview_categories(interview_type: str) -> List[str]:
    """The rotating category list for an interview flavour."""
    return HR_CATEGORIES if interview_type == "hr" else CATEGORIES


def category_for_index(index: int, interview_type: str = "technical") -> str:
    """Rotating category for a zero-based question index of an interview type."""
    cats = interview_categories(interview_type)
    return cats[index % len(cats)]


# ---------------------------------------------------------------------------
# Shared coercion helpers (lenient, like career recommendations)
# ---------------------------------------------------------------------------

def _safe_reason(exc: Exception) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text[:300]


def _clamp_score(value: Any, lo: int = 0, hi: int = 10) -> int:
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        return lo


def _coerce_str(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _coerce_str_list(raw: Any, limit: int = 6) -> List[str]:
    out: List[str] = []
    for item in raw or []:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            text = _coerce_str(item.get("text") or item.get("point") or item.get("item"))
            if text:
                out.append(text)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------

def _snapshot_sources(ctx: InterviewContext) -> List[Dict[str, Any]]:
    return _to_sources(ctx.retrieved_chunks)


def build_question_prompt(
    ctx: InterviewContext,
    category: str,
    question_index: int,
    total: int,
    previous_answer: Optional[str] = None,
    interview_type: str = "technical",
) -> str:
    """Compose the prompt that produces ONE grounded interview question.

    ``interview_type`` selects the category vocabulary advertised to the model
    (technical categories vs HR categories).
    """
    previous_block = ""
    if previous_answer and previous_answer.strip():
        previous_block = (
            "CANDIDATE'S PREVIOUS ANSWER (from the prior question — make the new\n"
            f"question an adaptive follow-up that builds on it WITHOUT assuming\n"
            f"anything not in the context):\n{previous_answer.strip()}\n"
        )
    categories_hint = ", ".join(interview_categories(interview_type))
    return f"""SUPPLIED CONTEXT (the ONLY facts you may use):

{build_context_section(ctx)}

CATEGORY: {category} (one of: {categories_hint})

QUESTION NUMBER: {question_index + 1} of {total}

{previous_block}
Now produce the interview question JSON."""


def parse_question_json(data: Any) -> Dict[str, Any]:
    """Validate/normalize an LLM question response into a question dict."""
    if not isinstance(data, dict):
        raise ValueError("LLM question response was not a JSON object")
    text = _coerce_str(
        data.get("question") or data.get("question_text") or data.get("text")
    )
    if not text:
        raise ValueError("LLM returned an empty question")
    return {"question_text": text}


def fallback_question(
    ctx: InterviewContext,
    category: str,
    question_index: int,
    total: int,
    interview_type: str = "technical",
) -> Dict[str, Any]:
    """Deterministic, fully grounded question for when the LLM is unavailable.

    Technical questions anchor on a skill that is required by the job (or
    already in the resume). HR questions ask the candidate to describe their
    own, real work history, communication and motivations — nothing is
    invented. All other categories only ask the candidate to describe their own
    experience.
    """
    notice = {
        "question_text": None,
        "generated_by": "fallback",
        "notice": FALLBACK_NOTICE,
    }

    if interview_type == "hr":
        return _fallback_hr_question(ctx, category, question_index, total, notice)

    candidates = ctx.job_skills or ctx.matched_skills or ctx.missing_skills
    skill = candidates[question_index % len(candidates)] if candidates else None

    if category == "technical":
        if skill:
            question = (
                f"This role requires {skill}. Based on your actual experience in the "
                f"resume, explain what you genuinely know about {skill} — including "
                "any real project, coursework or internship where you used it."
            )
        else:
            question = (
                "From the skills actually listed in your resume, choose the one you "
                "are strongest at and explain the depth of your knowledge and where "
                "you have used it for real."
            )
    elif category == "project_experience":
        question = (
            "Pick one project that is actually on your resume and describe what you "
            "built, your specific role in it, the technologies you used, and the "
            "impact. Only describe what is genuinely on your resume."
        )
    elif category == "problem_solving":
        question = (
            "Describe a technical problem you solved in a real project from your "
            "resume. Walk through how you approached it, what went wrong, and how "
            "you fixed it. Stay strictly within your real experience."
        )
    else:  # behavioral / situational
        question = (
            "Tell me about a real time you worked with a team or had to communicate "
            "a technical topic to others. What did you do specifically, and what "
            "did you learn from it?"
        )

    notice["question_text"] = question
    return notice


def _fallback_hr_question(
    ctx: InterviewContext,
    category: str,
    question_index: int,
    total: int,
    notice: Dict[str, Any],
) -> Dict[str, Any]:
    """Deterministic HR-mode question, grounded only in the real context."""
    educational = (
        f"Work your way through your real work history from the resume and "
        f"the job ({ctx.job_title or 'this role'} at "
        f"{ctx.job_company or 'this company'}): what roles have you held, "
        f"what did you own in each, and how does it connect to this job?"
    )
    if category == "communication":
        question = (
            "Describe a real situation where you explained something complex to a "
            "non-technical audience or stakeholder. What did you do to make it "
            "clear, and what was the outcome?"
        )
    elif category == "work_experience":
        question = educational
    elif category == "motivation":
        question = (
            "Why are you genuinely interested in this role and company based on "
            "your own career goals, and what are you hoping to achieve in the next "
            "role you take?"
        )
    else:  # behavioral / teamwork / conflict / fit
        question = (
            "Tell me about a real time you faced a disagreement or a difficult "
            "situation with teammates or a manager. How did you handle it, and "
            "what would you do differently?"
        )
    notice["question_text"] = question
    return notice


def generate_question(
    ctx: InterviewContext,
    category: str,
    question_index: int,
    total: int,
    previous_answer: Optional[str] = None,
    llm_call=None,
    interview_type: str = "technical",
) -> Dict[str, Any]:
    """Generate one grounded question; falls back to a deterministic one.

    ``interview_type`` picks the role-specific system prompt and fallback bank
    (technical vs HR); the technical pipeline is the default and unchanged.
    """
    if llm_call is None:
        llm_call = llm_client.generate_json

    system_prompt = (
        HR_QUESTION_SYSTEM_PROMPT if interview_type == "hr" else QUESTION_SYSTEM_PROMPT
    )
    try:
        prompt = build_question_prompt(
            ctx,
            category,
            question_index,
            total,
            previous_answer=previous_answer,
            interview_type=interview_type,
        )
        raw = llm_call(prompt, system=system_prompt)
        question = parse_question_json(raw)
        question["generated_by"] = "llm"
        question["notice"] = None
        return question
    except Exception as exc:
        question = fallback_question(
            ctx, category, question_index, total, interview_type=interview_type
        )
        question["notice"] = f"{FALLBACK_NOTICE} ({_safe_reason(exc)})"
        return question


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def build_evaluation_prompt(
    ctx: InterviewContext,
    question_text: str,
    category: str,
    answer_text: str,
) -> str:
    """Compose the prompt that evaluates one candidate answer."""
    context_section = build_context_section(ctx)
    # The full context block is trimmed to the resume excerpt size used by the
    # evaluation prompt to keep the call cheaper while staying grounded.
    return f"""SUPPLIED CONTEXT (the ONLY background material you may use):

{context_section}

QUESTION CATEGORY: {category}

QUESTION:
{question_text}

CANDIDATE'S ANSWER:
{answer_text}

Scoring rubric: score 0-10 — 9-10 comprehensive and accurate; 7-8 solid with minor
gaps; 5-6 partial/partly relevant; 3-4 weak or mostly off-topic; 0-2 empty or
completely irrelevant. Be consistent with this rubric.

Now produce the evaluation JSON."""


def parse_evaluation_json(data: Any) -> Dict[str, Any]:
    """Validate/normalize an LLM evaluation response into a safe shape."""
    if not isinstance(data, dict):
        raise ValueError("LLM evaluation response was not a JSON object")
    return {
        "score": _clamp_score(data.get("score"), 0, 10),
        "correctness": _coerce_str(
            data.get("correctness")
            or data.get("assessment")
            or data.get("relevance")
            or data.get("summary")
        ),
        "strengths": _coerce_str_list(data.get("strengths") or data.get("strong")),
        "weaknesses": _coerce_str_list(data.get("weaknesses") or data.get("weak")),
        "missing_points": _coerce_str_list(
            data.get("missing_points") or data.get("missing") or data.get("gaps")
        ),
        "feedback": _coerce_str(data.get("feedback") or data.get("improvement")),
    }


def _tokens(text: str) -> set:
    from app.services.resume_parser import _normalize

    norm = _normalize(text or "")
    return {t for t in norm.split(" ") if len(t) >= 2}


def fallback_evaluation(
    ctx: InterviewContext,
    question_text: str,
    category: str,
    answer_text: str,
) -> Dict[str, Any]:
    """Deterministic, transparent evaluation for when the LLM is unavailable.

    Scores from answer length, token overlap with the question, and whether any
    skill from the job (or the resume) appears in the answer. Never references
    anything outside the supplied context.
    """
    answer = (answer_text or "").strip()
    if not answer:
        return {
            "score": 1,
            "correctness": "No answer was provided.",
            "strengths": [],
            "weaknesses": ["No answer was provided, so nothing could be evaluated."],
            "missing_points": ["Provide a real answer to the question."],
            "feedback": "Rephrase your answer with concrete details from your own experience.",
            "generated_by": "fallback",
            "notice": FALLBACK_NOTICE,
        }

    answer_tokens = _tokens(answer)
    question_tokens = _tokens(question_text)
    overlap = (
        len(answer_tokens & question_tokens) / len(question_tokens)
        if question_tokens
        else 0.0
    )

    mentioned = [s for s in (ctx.job_skills or []) if _has_skill(answer, s)]
    if not mentioned:
        mentioned = [s for s in (ctx.matched_skills or []) if _has_skill(answer, s)]

    words = len(answer.split())
    score = 2
    score += 5 if words >= 40 else 4 if words >= 20 else 2 if words >= 10 else 0
    if mentioned:
        score += 2
    score += int(round(2 * overlap))
    score = max(1, min(10, score))

    strengths: List[str] = []
    weaknesses: List[str] = []
    missing_points: List[str] = []

    if mentioned:
        strengths.append(
            f"Your answer references {', '.join(mentioned[:3])}, which is relevant to this role."
        )
    if words >= 40:
        strengths.append("Your answer is detailed enough to show real thought.")
    else:
        weaknesses.append(
            "Your answer is brief — expand it with specific details from your own experience."
        )
    if overlap < 0.25:
        weaknesses.append("Your answer only loosely connects to what the question asks.")
    elif overlap >= 0.5:
        strengths.append("Your answer stays on-topic and directly addresses the question.")

    if ctx.missing_skills and category == "technical":
        missing_points.append(
            "Review the role's required skills that are not clearly in your resume "
            f"({', '.join(ctx.missing_skills[:3])})."
        )
    if not missing_points:
        missing_points.append(
            "Add concrete examples (project, role, outcome) to strengthen your point."
        )

    correctness = (
        f"Your answer received a score of {score}/10 from the rule-based evaluator."
    )
    feedback = (
        "Structure your answer with a clear point, a concrete example from your "
        "experience, and the outcome to score higher."
    )

    return {
        "score": score,
        "correctness": correctness,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "missing_points": missing_points,
        "feedback": feedback,
        "generated_by": "fallback",
        "notice": FALLBACK_NOTICE,
    }


def _has_skill(text: str, skill: str) -> bool:
    from app.services.resume_parser import _normalize, normalize_skill

    f = normalize_skill(skill)
    if not f:
        return False
    return f" {f} " in f" {_normalize(text)} "


def evaluate_answer(
    ctx: InterviewContext,
    question_text: str,
    category: str,
    answer_text: str,
    llm_call=None,
    interview_type: str = "technical",
) -> Dict[str, Any]:
    """Evaluate one answer; falls back to a deterministic evaluation.

    ``interview_type`` picks the evaluator persona (technical vs HR); the
    technical pipeline is the default and unchanged.
    """
    if llm_call is None:
        llm_call = llm_client.generate_json

    system_prompt = (
        HR_EVALUATION_SYSTEM_PROMPT if interview_type == "hr" else EVALUATION_SYSTEM_PROMPT
    )
    try:
        prompt = build_evaluation_prompt(ctx, question_text, category, answer_text)
        raw = llm_call(prompt, system=system_prompt)
        evaluation = parse_evaluation_json(raw)
        if not evaluation["feedback"] and not evaluation["correctness"]:
            raise ValueError("LLM returned an empty evaluation")
        evaluation["generated_by"] = "llm"
        evaluation["notice"] = None
        return evaluation
    except Exception as exc:
        evaluation = fallback_evaluation(ctx, question_text, category, answer_text)
        evaluation["notice"] = f"{FALLBACK_NOTICE} ({_safe_reason(exc)})"
        return evaluation


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

def _aggregate_scores(qa_pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute overall + per-category averages from answered question pairs.

    Each pair: {"category", "question", "answer", "score", "strengths",
    "weaknesses", "missing_points"}.
    """
    if not qa_pairs:
        return {"overall_score": 0, "category_scores": []}

    scores = [max(0, p["score"]) for p in qa_pairs]
    overall = int(round(sum(scores) / len(scores)))

    by_category: Dict[str, List[int]] = {}
    for pair in qa_pairs:
        by_category.setdefault(pair["category"], []).append(pair["score"])

    category_scores = [
        {
            "category": category,
            "score": int(round(sum(vals) / len(vals))),
            "comment": "",
        }
        for category, vals in sorted(by_category.items())
    ]
    return {"overall_score": overall, "category_scores": category_scores}


def build_report_prompt(
    ctx: InterviewContext,
    qa_pairs: List[Dict[str, Any]],
    aggregates: Dict[str, Any],
) -> str:
    """Compose the prompt that produces the final interview report."""
    lines = []
    for i, pair in enumerate(qa_pairs, start=1):
        lines.append(
            f"Q{i} [{pair['category']}]: {pair['question']}\n"
            f"Answer: {pair['answer']}\n"
            f"Score: {pair['score']}/10"
        )
    qa_block = "\n\n".join(lines) if lines else "(no questions answered)"

    cat_lines = [
        f"- {c['category']}: {c['score']}/10" for c in aggregates["category_scores"]
    ]
    cat_block = "\n".join(cat_lines) if cat_lines else "- (none)"

    return f"""SUPPLIED CONTEXT (the ONLY facts you may use):

{build_context_section(ctx)}

INTERVIEW QUESTIONS & EVALUATIONS:
{qa_block}

AGGREGATE SCORES (computed from the evaluations above):
OVERALL: {aggregates['overall_score']}/10
{cat_block}

Now produce the final interview report JSON."""


def parse_report_json(data: Any) -> Dict[str, Any]:
    """Validate/normalize an LLM report response into a safe shape."""
    if not isinstance(data, dict):
        raise ValueError("LLM report response was not a JSON object")
    overall = _clamp_score(data.get("overall_score") or data.get("score"), 0, 10)
    category_scores: List[Dict[str, Any]] = []
    for item in data.get("category_scores") or []:
        if not isinstance(item, dict):
            continue
        category = _coerce_str(item.get("category") or item.get("name") or item.get("label"))
        if category:
            category_scores.append(
                {
                    "category": category,
                    "score": _clamp_score(item.get("score"), 0, 10),
                    "comment": _coerce_str(item.get("comment") or item.get("notes")),
                }
            )
    return {
        "overall_score": overall,
        "category_scores": category_scores,
        "strengths": _coerce_str_list(data.get("strengths")),
        "weaknesses": _coerce_str_list(data.get("weaknesses")),
        "recommended_topics": _coerce_str_list(
            data.get("recommended_topics") or data.get("topics") or data.get("next_steps")
        ),
        "summary": _coerce_str(data.get("summary") or data.get("overview")),
    }


def fallback_report(
    ctx: InterviewContext,
    qa_pairs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Deterministic report built purely from the stored evaluations."""
    aggregates = _aggregate_scores(qa_pairs)
    overall = aggregates["overall_score"]
    category_scores = aggregates["category_scores"]

    strengths: List[str] = []
    weaknesses: List[str] = []
    for pair in qa_pairs:
        for s in pair.get("strengths") or []:
            if s.strip() and s.strip() not in strengths and len(strengths) < 5:
                strengths.append(s.strip())
        for w in pair.get("weaknesses") or []:
            if w.strip() and w.strip() not in weaknesses and len(weaknesses) < 5:
                weaknesses.append(w.strip())

    recommended_topics = [s for s in ctx.missing_skills if s][:4]
    low_categories = [
        c["category"] for c in category_scores if c["score"] < 6
    ]
    if low_categories:
        recommended_topics.append(
            "Strengthen the weakest areas: " + ", ".join(low_categories)
        )
    if not recommended_topics:
        recommended_topics.append(
            "Deepen practical depth in your strongest skills with real projects."
        )
    recommended_topics = recommended_topics[:6]

    if not qa_pairs:
        summary = (
            "The interview ended before any question was answered, so only a "
            "baseline score could be computed."
        )
    else:
        summary = (
            f"Overall mock interview score: {overall}/10 across "
            f"{len(qa_pairs)} answered question"
            f"{'s' if len(qa_pairs) > 1 else ''}."
        )
        if strengths:
            summary += " Notable strengths: " + "; ".join(strengths[:3]) + "."
        if weaknesses:
            summary += " Key areas to improve: " + "; ".join(weaknesses[:3]) + "."

    return {
        "overall_score": overall,
        "category_scores": category_scores,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommended_topics": recommended_topics,
        "summary": summary,
        "generated_by": "fallback",
        "notice": FALLBACK_NOTICE,
    }


def generate_report(
    ctx: InterviewContext,
    qa_pairs: List[Dict[str, Any]],
    llm_call=None,
    interview_type: str = "technical",
) -> Dict[str, Any]:
    """Produce the final interview report; falls back to a deterministic one.

    ``interview_type`` picks the reporting persona (technical vs HR); the
    technical pipeline is the default and unchanged.
    """
    if llm_call is None:
        llm_call = llm_client.generate_json

    system_prompt = (
        HR_REPORT_SYSTEM_PROMPT
        if interview_type == "hr"
        else REPORT_SYSTEM_PROMPT
    )
    aggregates = _aggregate_scores(qa_pairs)
    try:
        prompt = build_report_prompt(ctx, qa_pairs, aggregates)
        raw = llm_call(prompt, system=system_prompt)
        report = parse_report_json(raw)
        if not report["summary"] and not report["category_scores"]:
            raise ValueError("LLM returned an empty report")
        report["generated_by"] = "llm"
        report["notice"] = None
        return report
    except Exception as exc:
        report = fallback_report(ctx, qa_pairs)
        report["notice"] = f"{FALLBACK_NOTICE} ({_safe_reason(exc)})"
        return report


# ---------------------------------------------------------------------------
# Question/answer row helpers (used by the route layer)
# ---------------------------------------------------------------------------

def build_question_row(
    interview_id: int,
    question_index: int,
    category: str,
    question_result: Dict[str, Any],
    sources: List[Dict[str, Any]],
    video_interview_id: Optional[int] = None,
) -> MockInterviewQuestion:
    """Construct an (unsaved) MockInterviewQuestion ORM object.

    Anchor the question to a text-based mock interview via ``interview_id``, or
    to a video interview session (technical or HR) via ``video_interview_id``
    (exactly one of the two is set).
    """
    return MockInterviewQuestion(
        interview_id=interview_id,
        video_interview_id=video_interview_id,
        question_index=question_index,
        category=category,
        question_text=question_result["question_text"],
        generated_by=question_result.get("generated_by", "fallback"),
        notice=question_result.get("notice"),
        question_sources=sources or None,
    )


def apply_evaluation(
    question: MockInterviewQuestion,
    answer_text: str,
    evaluation: Dict[str, Any],
) -> None:
    """Flatten an evaluation dict onto a question row (in place)."""
    question.answer_text = answer_text
    question.score = evaluation.get("score", 0)
    question.correctness = evaluation.get("correctness", "")
    question.strengths = evaluation.get("strengths") or []
    question.weaknesses = evaluation.get("weaknesses") or []
    question.missing_points = evaluation.get("missing_points") or []
    question.feedback = evaluation.get("feedback", "")
    question.evaluation = evaluation
    question.evaluation_generated_by = evaluation.get("generated_by", "fallback")
    question.evaluation_notice = evaluation.get("notice")
    from datetime import datetime

    question.evaluated_at = datetime.utcnow()


def apply_report(
    interview,
    report: Dict[str, Any],
    completed_at=None,
) -> None:
    """Flatten a report dict onto a MockInterview row (in place)."""
    interview.overall_score = report.get("overall_score", 0)
    interview.category_scores = report.get("category_scores") or []
    interview.strengths = report.get("strengths") or []
    interview.weaknesses = report.get("weaknesses") or []
    interview.recommended_topics = report.get("recommended_topics") or []
    interview.summary = report.get("summary", "")
    interview.report = report
    interview.report_generated_by = report.get("generated_by", "fallback")
    interview.report_notice = report.get("notice")
    if completed_at is not None:
        interview.completed_at = completed_at


def build_qa_pairs(questions: List[MockInterviewQuestion]) -> List[Dict[str, Any]]:
    """Build the qa_pairs shape consumed by the report generators."""
    pairs = []
    for q in questions:
        if not q.answer_text:
            continue
        pairs.append(
            {
                "category": q.category,
                "question": q.question_text,
                "answer": q.answer_text,
                "score": q.score if q.score is not None else 0,
                "strengths": q.strengths or [],
                "weaknesses": q.weaknesses or [],
                "missing_points": q.missing_points or [],
            }
        )
    return pairs
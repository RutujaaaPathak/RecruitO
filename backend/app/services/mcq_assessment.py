# pyrefly: ignore [missing-import]
"""AI MCQ Assessment service: timed multiple-choice tests for candidates.

Runs a 20-minute, 20-question MCQ test against one of the candidate's
applications. Questions are generated per-attempt either by the LLM (grounded
in the same server-side candidate/job context as the mock interview) or by a
deterministic fallback question bank, so the feature always works even without
an LLM key.

Security invariant: each question's single correct answer
(`correct_option_index`) is stored server-side and NEVER serialized. The API
only ever returns the four options plus the candidate's own selection. Scoring
happens entirely backend-side at submission, or automatically when the timer
expires (backend-enforced deadline = `started_at + time_limit_minutes`).

This module deliberately does NOT import the (paused) RAG chatbot. It reuses
the shared low-level context helpers from the mock interview module so the
assessment stays grounded but decoupled.
"""
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.models import (
    AssessmentStatusEnum,
    McqAnswer,
    McqAssessment,
    McqQuestion,
)
from app.services import llm_client
from app.services.mock_interview import build_context_section

# Question rotation, in this exact order for every assessment.
CATEGORIES = ["technical", "problem_solving", "situational", "behavioral"]

DEFAULT_QUESTION_COUNT = 20
DEFAULT_TIME_LIMIT_MINUTES = 20
DEFAULT_PASS_PERCENTAGE = 60

OPTION_COUNT = 4

FALLBACK_NOTICE = (
    "The AI model is unavailable right now, so these questions come from a "
    "deterministic fallback question bank."
)

EXPIRY_NOTICE = (
    "The time limit was reached, so the assessment was auto-submitted. The "
    "results below reflect the questions answered before the deadline."
)

MCQ_SYSTEM_PROMPT = """You are a senior assessment author inside RecruitO, an HR/recruitment
platform. Your ONLY job is to generate a set of multiple-choice questions for a
candidate applying to a specific role. Respond with ONLY valid JSON in this
exact shape:
{"questions": [{"category": string, "question": string, "options": [string], "correct_index": int}]}

GROUNDING RULES — follow them without exception:
1. Categories must be drawn from: technical, problem_solving, situational, behavioral.
2. Distribute the requested number of questions evenly across these four
   categories (round-robin: technical, problem_solving, situational, behavioral).
3. Ground every question in the SUPPLIED CONTEXT (the candidate's resume, the
   selected job, its required skills and description). Questions must be
   answerable from general role knowledge; never invent facts about the candidate.
4. options: exactly 4 DIFFERENT, succinct and plausible options (a few words each).
5. correct_index: the 0-based index into options of the SINGLE correct option;
   it MUST match the option text exactly.
6. Output ONLY the JSON object — no preamble, no numbering, no explanation."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _clamp(raw: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def question_count() -> int:
    """Return the configured question count (MCQ_QUESTION_COUNT)."""
    raw = os.getenv("MCQ_QUESTION_COUNT", str(DEFAULT_QUESTION_COUNT))
    return _clamp(raw, DEFAULT_QUESTION_COUNT, 5, 50)


def time_limit_minutes() -> int:
    """Return the configured time limit (MCQ_TIME_LIMIT_MINUTES)."""
    raw = os.getenv("MCQ_TIME_LIMIT_MINUTES", str(DEFAULT_TIME_LIMIT_MINUTES))
    return _clamp(raw, DEFAULT_TIME_LIMIT_MINUTES, 5, 120)


def pass_threshold() -> int:
    """Return the configured pass percentage (MCQ_PASS_PERCENTAGE)."""
    raw = os.getenv("MCQ_PASS_PERCENTAGE", str(DEFAULT_PASS_PERCENTAGE))
    return _clamp(raw, DEFAULT_PASS_PERCENTAGE, 1, 100)


def category_for_index(index: int) -> str:
    """Rotating category for a zero-based question index (round-robin)."""
    return CATEGORIES[index % len(CATEGORIES)]


# ---------------------------------------------------------------------------
# Timed deadline helpers
# ---------------------------------------------------------------------------

def expires_at(assessment: McqAssessment) -> datetime:
    """The backend-enforced deadline for an in-progress assessment."""
    started = assessment.started_at or datetime.utcnow()
    return started + timedelta(minutes=assessment.time_limit_minutes or 20)


def is_expired(assessment: McqAssessment, now: Optional[datetime] = None) -> bool:
    """True when an in-progress assessment has passed its deadline."""
    if assessment.status != AssessmentStatusEnum.in_progress:
        return False
    now = now or datetime.utcnow()
    return now >= expires_at(assessment)


# ---------------------------------------------------------------------------
# Lenient coercion helpers (shared pattern; see mock_interview / career recs)
# ---------------------------------------------------------------------------

def _safe_reason(exc: Exception) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text[:300]


def _coerce_str(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _coerce_category(value: Any) -> str:
    cat = _coerce_str(value).lower().replace(" ", "_").replace("-", "_")
    if cat in CATEGORIES:
        return cat
    if cat.startswith("tech"):
        return "technical"
    return "technical"


def _coerce_options(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    options: List[str] = []
    for item in raw:
        if isinstance(item, dict):
            text = _coerce_str(item.get("text") or item.get("option") or item.get("value"))
        else:
            text = _coerce_str(item)
        if text:
            options.append(text)
    return options[:OPTION_COUNT]


def _coerce_correct_index(raw: Any) -> Optional[int]:
    """Accept a 0-based index (0-3) or a letter A-D; returns a 0-based index."""
    if isinstance(raw, str):
        letter = raw.strip().upper()
        if letter in ("A", "B", "C", "D"):
            return ord(letter) - ord("A")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if 0 <= value <= 3:
        return value
    return None


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_generation_prompt(ctx: Any, total: int) -> str:
    """Compose the prompt that produces ALL questions for one assessment."""
    rotation = ", ".join(CATEGORIES)
    return f"""SUPPLIED CONTEXT (the ONLY facts you may use):

{build_context_section(ctx)}

NUMBER OF QUESTIONS: {total}

CATEGORY ROTATION (repeat in this order): {rotation}

Now produce the questions JSON."""


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------

def parse_generation_json(data: Any, total: int) -> List[Dict[str, Any]]:
    """Validate/normalize an LLM batch response into question dicts.

    Returns a list of up to ``total`` validated questions shaped like:
    {"category", "question", "options", "correct_index"}. Unparseable items are
    skipped so one bad question doesn't discard the whole batch.
    """
    if not isinstance(data, dict):
        raise ValueError("LLM response was not a JSON object")
    raw = data.get("questions")
    if raw is None:
        raw = data.get("mcqs") or data.get("items")
    if not isinstance(raw, list):
        raise ValueError("LLM response had no 'questions' list")

    out: List[Dict[str, Any]] = []
    for item in raw:
        if len(out) >= total:
            break
        if not isinstance(item, dict):
            continue
        question = _coerce_str(item.get("question") or item.get("question_text"))
        if not question:
            continue
        options = _coerce_options(item.get("options"))
        if len(options) != OPTION_COUNT or len(set(options)) != OPTION_COUNT:
            continue  # must be exactly 4 distinct options
        correct_raw = item.get("correct_index")
        if correct_raw is None:
            correct_raw = item.get("correct_answer_index")
        if correct_raw is None:
            correct_raw = item.get("answer_index")
        correct_index = _coerce_correct_index(correct_raw)
        if correct_index is None or correct_index >= len(options):
            continue
        out.append(
            {
                "category": _coerce_category(item.get("category")),
                "question": question,
                "options": options,
                "correct_index": correct_index,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Fallback question bank (deterministic; used when the LLM is unavailable)
# ---------------------------------------------------------------------------

_FALLBACK_BANK: List[Dict[str, Any]] = [
    {
        "category": "technical",
        "question": "Which SQL clause is used to filter grouped rows after aggregation?",
        "options": ["WHERE", "HAVING", "ORDER BY", "GROUP BY"],
        "correct_index": 1,
    },
    {
        "category": "problem_solving",
        "question": "Which algorithm is best when a problem has overlapping subproblems and optimal substructure?",
        "options": ["Divide and conquer", "Dynamic programming", "Greedy selection", "Randomized sampling"],
        "correct_index": 1,
    },
    {
        "category": "situational",
        "question": "A stakeholder asks for a feature that conflicts with the roadmap. What should you do first?",
        "options": ["Implement it immediately", "Ignore the request", "Clarify the goal and align priorities", "Delay it silently"],
        "correct_index": 2,
    },
    {
        "category": "behavioral",
        "question": "Which approach best shows your role on a resume project during an interview?",
        "options": ["List every technology used", "Describe your actions and measurable impact", "Read the description verbatim", "Only mention the failures"],
        "correct_index": 1,
    },
    {
        "category": "technical",
        "question": "Which data structure provides O(1) average-time insert and lookup?",
        "options": ["Linked list", "Queue", "Hash table", "Binary search tree"],
        "correct_index": 2,
    },
    {
        "category": "problem_solving",
        "question": "An endpoint is slow because it makes 200 sequential API calls. What is the best improvement?",
        "options": ["Buy faster hardware", "Increase the timeout", "Parallelize with a concurrency limit", "Add a retry loop"],
        "correct_index": 2,
    },
    {
        "category": "situational",
        "question": "Your task will be late because of an upstream delay. What is the right move?",
        "options": ["Wait silently", "Tell the manager at the last minute", "Inform stakeholders early with a new estimate", "Ship incomplete work quietly"],
        "correct_index": 2,
    },
    {
        "category": "behavioral",
        "question": "How do you approach a technology you have never used before?",
        "options": ["Avoid tasks that use it", "Learn the fundamentals and prototype", "Copy code from tutorials blindly", "Wait for someone else to do it"],
        "correct_index": 1,
    },
    {
        "category": "technical",
        "question": "What does the HTTP status code 401 indicate?",
        "options": ["Bad request", "Payment required", "Unauthorized", "Conflict"],
        "correct_index": 2,
    },
    {
        "category": "problem_solving",
        "question": "Which Big-O class does binary search belong to?",
        "options": ["O(n)", "O(log n)", "O(n log n)", "O(n^2)"],
        "correct_index": 1,
    },
    {
        "category": "situational",
        "question": "A teammate commits code that breaks the build. What is the best first response?",
        "options": ["Blame them publicly", "Silently fix it and say nothing", "Investigate and fix it together", "Roll back without discussion"],
        "correct_index": 2,
    },
    {
        "category": "behavioral",
        "question": "When you disagree with your manager on an approach, you should...",
        "options": ["Accept silently and resent it", "Argue until they change their mind", "Present evidence and respect the final decision", "Complain to teammates"],
        "correct_index": 2,
    },
    {
        "category": "technical",
        "question": "In REST, which HTTP method is idempotent and commonly used to fully replace a resource?",
        "options": ["GET", "POST", "PATCH", "PUT"],
        "correct_index": 3,
    },
    {
        "category": "problem_solving",
        "question": "You detect a duplicate in an array of length n+1 holding values 1..n. Which approach is O(n) time and O(1) space?",
        "options": ["Sort then scan", "Nested loops", "Floyd's cycle detection", "Count via a second array"],
        "correct_index": 2,
    },
    {
        "category": "situational",
        "question": "You discover a security bug in production code. What is most appropriate?",
        "options": ["Keep it secret to avoid blame", "Log it and fix it later", "Disclose it through the incident process and patch it", "Wait for the next release without telling anyone"],
        "correct_index": 2,
    },
    {
        "category": "behavioral",
        "question": "How do you stay current with new frameworks in your field?",
        "options": ["Only learn what is forced on you", "Follow communities and build small experiments", "Skip learning entirely", "Memorize interview questions"],
        "correct_index": 1,
    },
]


def fallback_question_at(index: int) -> Dict[str, Any]:
    """Deterministic bank question for a zero-based index (cycles the bank)."""
    item = dict(_FALLBACK_BANK[index % len(_FALLBACK_BANK)])
    item["category"] = _coerce_category(item["category"])
    return item


# ---------------------------------------------------------------------------
# Question generation orchestration (LLM with deterministic fallback)
# ---------------------------------------------------------------------------

def generate_questions(ctx: Any, total: int, llm_call=None) -> Dict[str, Any]:
    """Generate exactly ``total`` question dicts; returns metadata too.

    Result shape:
    {
      "questions": [{"question_index", "category", "question", "options",
                     "correct_index", "generated_by", "notice"}],
      "generated_by": "llm" | "mixed" | "fallback",
      "used_fallback": bool,
      "notice": Optional[str],
    }
    """
    if llm_call is None:
        llm_call = llm_client.generate_json

    parsed: List[Dict[str, Any]] = []
    notice: Optional[str] = None
    try:
        prompt = build_generation_prompt(ctx, total)
        raw = llm_call(prompt, system=MCQ_SYSTEM_PROMPT)
        parsed = parse_generation_json(raw, total)
    except Exception as exc:  # noqa: BLE001 - degrade gracefully, like mock interview
        notice = f"{FALLBACK_NOTICE} ({_safe_reason(exc)})"

    questions: List[Dict[str, Any]] = []
    llm_count = 0
    if parsed:
        llm_count = len(parsed)
        for index, item in enumerate(parsed):
            row = dict(item)
            row["question_index"] = index
            row["generated_by"] = "llm"
            row["notice"] = None
            questions.append(row)

    # Pad any shortfall from the deterministic bank so the test is always full.
    for index in range(len(questions), total):
        fq = fallback_question_at(index)
        fq["question_index"] = index
        fq["generated_by"] = "fallback"
        fq["notice"] = notice or FALLBACK_NOTICE
        fq["correct_index"] = int(fq["correct_index"])
        questions.append(fq)

    if llm_count == 0:
        generated_by = "fallback"
    elif llm_count == total:
        generated_by = "llm"
    else:
        generated_by = "mixed"

    return {
        "questions": questions,
        "generated_by": generated_by,
        "used_fallback": any(q["generated_by"] == "fallback" for q in questions),
        "notice": notice,
    }


def build_question_row(
    assessment_id: int, question: Dict[str, Any]
) -> McqQuestion:
    """Map a generated question dict onto a persisted McqQuestion row."""
    return McqQuestion(
        assessment_id=assessment_id,
        question_index=int(question["question_index"]),
        category=question["category"],
        question_text=question["question"],
        options=list(question["options"]),
        correct_option_index=int(question["correct_index"]),
        generated_by=question.get("generated_by") or "fallback",
        notice=question.get("notice"),
    )


def build_answer_row(
    assessment: McqAssessment,
    question: McqQuestion,
    selected_option: int,
) -> McqAnswer:
    """Build the answer row (correctness snapshotted from the stored key)."""
    return McqAnswer(
        assessment_id=assessment.id,
        question_id=question.id,
        selected_option=selected_option,
        is_correct=selected_option == question.correct_option_index,
    )


def record_answer(
    assessment: McqAssessment,
    question: McqQuestion,
    selected_option: int,
) -> bool:
    """Upsert the candidate's answer; returns True when the row was created.

    `(assessment_id, question_id)` is unique, so re-answering the same question
    updates ONE row instead of creating a duplicate submission.
    """
    existing = next(
        (a for a in (assessment.answers or []) if a.question_id == question.id),
        None,
    )
    is_correct = selected_option == question.correct_option_index
    if existing is None:
        assessment.answers.append(build_answer_row(assessment, question, selected_option))
        return True
    existing.selected_option = selected_option
    existing.is_correct = is_correct
    existing.answered_at = datetime.utcnow()
    return False


# ---------------------------------------------------------------------------
# Scoring (pure, test-friendly) + finalization
# ---------------------------------------------------------------------------

def compute_results(
    questions: List[Dict[str, Any]],
    answered: Dict[int, int],
    total: int,
    pass_threshold_value: int,
    expired: bool = False,
) -> Dict[str, Any]:
    """Score an assessment from its questions + answered map.

    ``questions``: dicts with "question_index", "category", "correct_option_index".
    ``answered``: mapping question_index -> selected option (0-3). Unanswered
    questions simply count toward ``unanswered_count``. Pure — no DB, no I/O.
    """
    correct = 0
    answered_count = 0
    category_stats: Dict[str, Dict[str, int]] = {}
    for q in questions or []:
        qindex = int(q["question_index"])
        category = q.get("category") or "technical"
        cat = category_stats.setdefault(category, {"total": 0, "correct": 0})
        cat["total"] += 1
        selected = answered.get(qindex)
        if selected is not None:
            answered_count += 1
            if selected == int(q["correct_option_index"]):
                correct += 1
                cat["correct"] += 1

    incorrect = answered_count - correct
    unanswered = total - answered_count
    percentage = int(round((correct / total) * 100)) if total else 0
    category_performance = [
        {
            "category": category,
            "total": stats["total"],
            "correct": stats["correct"],
            "percentage": int(round((stats["correct"] / stats["total"]) * 100))
            if stats["total"]
            else 0,
        }
        for category, stats in category_stats.items()
    ]

    return {
        "score": correct,
        "total": total,
        "percentage": percentage,
        "correct_count": correct,
        "incorrect_count": incorrect,
        "unanswered_count": unanswered,
        "passed": percentage >= pass_threshold_value,
        "pass_percentage": pass_threshold_value,
        "category_performance": category_performance,
        "expired": bool(expired),
    }


def apply_results(
    assessment: McqAssessment,
    results: Dict[str, Any],
    notice: Optional[str] = None,
) -> None:
    """Flatten computed results onto the assessment row (no commit)."""
    assessment.status = AssessmentStatusEnum.completed
    assessment.completed_at = datetime.utcnow()
    assessment.score = results["score"]
    assessment.total_scored = results["total"]
    assessment.percentage = results["percentage"]
    assessment.correct_count = results["correct_count"]
    assessment.incorrect_count = results["incorrect_count"]
    assessment.unanswered_count = results["unanswered_count"]
    assessment.passed = results["passed"]
    assessment.pass_percentage = results["pass_percentage"]
    assessment.category_performance = results["category_performance"]
    assessment.expired = (
        bool(results.get("expired", False)) or bool(assessment.expired)
    )
    if notice:
        assessment.result_notice = notice


def build_answered_map(assessment: McqAssessment) -> Dict[int, int]:
    """Map question_index -> selected option from the assessment's answers."""
    index_by_question_id = {
        q.id: q.question_index for q in (assessment.questions or [])
    }
    answered: Dict[int, int] = {}
    for answer in assessment.answers or []:
        qindex = index_by_question_id.get(answer.question_id)
        if qindex is not None:
            answered[qindex] = answer.selected_option
    return answered


def finalize_assessment(
    assessment: McqAssessment, expired: bool = False
) -> Dict[str, Any]:
    """Compute, apply and return results. Idempotent; safe to re-run.

    Correct answers are read from the stored key; nothing is exposed to the
    candidate beyond the aggregate results dict.
    """
    questions = [
        {
            "question_index": q.question_index,
            "category": q.category,
            "correct_option_index": q.correct_option_index,
        }
        for q in (assessment.questions or [])
    ]
    answered = build_answered_map(assessment)
    threshold = assessment.pass_percentage or pass_threshold()
    results = compute_results(
        questions,
        answered,
        assessment.total_questions or len(questions),
        threshold,
        expired=expired,
    )
    notice = EXPIRY_NOTICE if expired else None
    apply_results(assessment, results, notice=notice)
    return results
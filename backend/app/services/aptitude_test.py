# pyrefly: ignore [missing-import]
"""Aptitude Test service: timed multiple-choice aptitude tests for candidates.

Mirrors the AI MCQ assessment architecture (see ``app/services/mcq_assessment.py``)
and reuses its generic deadline + scoring helpers. Runs a 20-minute, 20-question
aptitude test against one of the candidate's applications. Questions span three
fixed sections — quantitative, logical reasoning and verbal — generated
per-attempt either by the LLM or by a deterministic fallback question bank, so
the feature always works even without an LLM key.

Security invariant: each question's single correct answer
(``correct_option_index``) is stored server-side and NEVER serialized. The API
only ever returns the four options plus the candidate's own selection. Scoring
happens entirely backend-side at submission, or automatically when the timer
expires (backend-enforced deadline = ``started_at + time_limit_minutes``).
"""
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.models import (
    AssessmentStatusEnum,
    AptitudeAnswer,
    AptitudeQuestion,
    AptitudeTest,
)
from app.services import llm_client
from app.services.mock_interview import build_context_section
from app.services.mcq_assessment import (
    compute_results as _compute_results,
    expires_at as _expires_at,
    is_expired as _is_expired,
)

# Question rotation, in this exact order for every test.
CATEGORIES = ["quantitative", "logical_reasoning", "verbal"]

DEFAULT_QUESTION_COUNT = 20
DEFAULT_TIME_LIMIT_MINUTES = 20
DEFAULT_PASS_PERCENTAGE = 60

OPTION_COUNT = 4

FALLBACK_NOTICE = (
    "The AI model is unavailable right now, so these questions come from a "
    "deterministic fallback question bank."
)

EXPIRY_NOTICE = (
    "The time limit was reached, so the test was auto-submitted. The "
    "results below reflect the questions answered before the deadline."
)

APTITUDE_SYSTEM_PROMPT = """You are a senior aptitude-test author inside RecruitO, an HR/recruitment
platform. Your ONLY job is to generate a set of aptitude multiple-choice questions
for a candidate applying to a specific role. Respond with ONLY valid JSON in this
exact shape:
{"questions": [{"category": string, "question": string, "options": [string], "correct_index": int}]}

GROUNDING RULES — follow them without exception:
1. Categories must be drawn from: quantitative, logical_reasoning, verbal.
2. Distribute the requested number of questions evenly across these three
   categories (round-robin: quantitative, logical_reasoning, verbal).
3. Every question must be a pure aptitude question (math, logic, or language
   skill). Never ask about the candidate's personal details; never invent facts
   about the candidate. Standard aptitude wording is preferred.
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
    """Return the configured question count (APTITUDE_QUESTION_COUNT)."""
    raw = os.getenv("APTITUDE_QUESTION_COUNT", str(DEFAULT_QUESTION_COUNT))
    return _clamp(raw, DEFAULT_QUESTION_COUNT, 5, 50)


def time_limit_minutes() -> int:
    """Return the configured time limit (APTITUDE_TIME_LIMIT_MINUTES)."""
    raw = os.getenv("APTITUDE_TIME_LIMIT_MINUTES", str(DEFAULT_TIME_LIMIT_MINUTES))
    return _clamp(raw, DEFAULT_TIME_LIMIT_MINUTES, 5, 120)


def pass_threshold() -> int:
    """Return the configured pass percentage (APTITUDE_PASS_PERCENTAGE)."""
    raw = os.getenv("APTITUDE_PASS_PERCENTAGE", str(DEFAULT_PASS_PERCENTAGE))
    return _clamp(raw, DEFAULT_PASS_PERCENTAGE, 1, 100)


def category_for_index(index: int) -> str:
    """Rotating category for a zero-based question index (round-robin)."""
    return CATEGORIES[index % len(CATEGORIES)]


# ---------------------------------------------------------------------------
# Timed deadline helpers (reused verbatim from the MCQ assessment module)
# ---------------------------------------------------------------------------

def expires_at(test: AptitudeTest) -> datetime:
    """The backend-enforced deadline for an in-progress aptitude test."""
    return _expires_at(test)


def is_expired(test: AptitudeTest, now: Optional[datetime] = None) -> bool:
    """True when an in-progress aptitude test has passed its deadline."""
    return _is_expired(test, now=now)


# ---------------------------------------------------------------------------
# Lenient coercion helpers (shared pattern; see mcq_assessment / mock_interview)
# ---------------------------------------------------------------------------

def _safe_reason(exc: Exception) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text[:300]


def _coerce_str(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _coerce_category(value: Any, index: int = 0) -> str:
    cat = _coerce_str(value).lower().replace(" ", "_").replace("-", "_")
    if cat in ("quantitative", "quant", "math", "arithmetic", "quants"):
        return "quantitative"
    if cat in ("logical_reasoning", "logical", "reasoning", "logic"):
        return "logical_reasoning"
    if cat in ("verbal", "english", "vocabulary", "language"):
        return "verbal"
    return category_for_index(index)


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
    """Compose the prompt that produces ALL questions for one test."""
    rotation = ", ".join(CATEGORIES)
    return f"""SUPPLIED CONTEXT (role only — never factually associate questions with
the candidate's personal data):

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
    for index, item in enumerate(raw):
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
                "category": _coerce_category(item.get("category"), index),
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
        "category": "quantitative",
        "question": "A shopkeeper sells an item for $144, making a profit of 20%. What was the cost price?",
        "options": ["$120", "$115", "$125", "$130"],
        "correct_index": 0,
    },
    {
        "category": "logical_reasoning",
        "question": "Which number completes the sequence: 2, 6, 12, 20, 30, ...?",
        "options": ["40", "42", "44", "36"],
        "correct_index": 1,
    },
    {
        "category": "verbal",
        "question": "Choose the word that is most similar in meaning to 'MAGNANIMOUS'.",
        "options": ["Generous", "Stingy", "Proud", "Quiet"],
        "correct_index": 0,
    },
    {
        "category": "quantitative",
        "question": "What is 15% of 240?",
        "options": ["32", "36", "24", "40"],
        "correct_index": 1,
    },
    {
        "category": "logical_reasoning",
        "question": "Find the odd one out: 3, 5, 7, 8, 11.",
        "options": ["3", "5", "7", "8"],
        "correct_index": 3,
    },
    {
        "category": "verbal",
        "question": "Choose the grammatically correct sentence.",
        "options": [
            "He don't like apples",
            "He doesn't likes apples",
            "He doesn't like apples",
            "He not like apples",
        ],
        "correct_index": 2,
    },
    {
        "category": "quantitative",
        "question": "A train travels 90 km in 1.5 hours. What is its average speed in km/h?",
        "options": ["45", "50", "60", "75"],
        "correct_index": 2,
    },
    {
        "category": "logical_reasoning",
        "question": "If PENCIL is coded as QFODJM, how is PAPER coded?",
        "options": ["QBQFS", "QZQGS", "QBQGT", "RBQFS"],
        "correct_index": 0,
    },
    {
        "category": "verbal",
        "question": "Choose the word that is the opposite of 'DEFICIT'.",
        "options": ["Shortage", "Surplus", "Debt", "Loss"],
        "correct_index": 1,
    },
    {
        "category": "quantitative",
        "question": "If x + y = 30 and x − y = 8, what is the value of x?",
        "options": ["11", "19", "20", "22"],
        "correct_index": 1,
    },
    {
        "category": "logical_reasoning",
        "question": "A clock shows 9:00. What is the angle between the hour and minute hands?",
        "options": ["45°", "60°", "90°", "120°"],
        "correct_index": 2,
    },
    {
        "category": "verbal",
        "question": "Select the correctly spelled word.",
        "options": ["Accomodate", "Acommodate", "Accommodate", "Acomodate"],
        "correct_index": 2,
    },
    {
        "category": "quantitative",
        "question": "The average of five numbers is 24. If one number is removed, the average drops to 22. What was the removed number?",
        "options": ["28", "30", "32", "26"],
        "correct_index": 2,
    },
    {
        "category": "logical_reasoning",
        "question": "In a row of students, Riya is 8th from the left and 7th from the right. How many students are in the row?",
        "options": ["13", "15", "14", "16"],
        "correct_index": 2,
    },
    {
        "category": "verbal",
        "question": "Complete the analogy: FISH is to SCHOOL as LION is to ...",
        "options": ["Herd", "Pride", "Pack", "Flock"],
        "correct_index": 1,
    },
    {
        "category": "quantitative",
        "question": "A mixture contains 4 parts water to 1 part syrup. What percentage of the mixture is syrup?",
        "options": ["20%", "25%", "40%", "10%"],
        "correct_index": 0,
    },
    {
        "category": "logical_reasoning",
        "question": "CAT is to KITTEN as DOG is to ...",
        "options": ["Puppy", "Calf", "Cub", "Chick"],
        "correct_index": 0,
    },
    {
        "category": "verbal",
        "question": "Choose the word that is closest in meaning to 'TRANSIENT'.",
        "options": ["Permanent", "Temporary", "Eternal", "Constant"],
        "correct_index": 1,
    },
]


def fallback_question_at(index: int) -> Dict[str, Any]:
    """Deterministic bank question for a zero-based index (cycles the bank)."""
    item = dict(_FALLBACK_BANK[index % len(_FALLBACK_BANK)])
    item["category"] = category_for_index(index)
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
        raw = llm_call(prompt, system=APTITUDE_SYSTEM_PROMPT)
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


def build_question_row(test_id: int, question: Dict[str, Any]) -> AptitudeQuestion:
    """Map a generated question dict onto a persisted AptitudeQuestion row."""
    return AptitudeQuestion(
        aptitude_test_id=test_id,
        question_index=int(question["question_index"]),
        category=question["category"],
        question_text=question["question"],
        options=list(question["options"]),
        correct_option_index=int(question["correct_index"]),
        generated_by=question.get("generated_by") or "fallback",
        notice=question.get("notice"),
    )


def build_answer_row(
    test: AptitudeTest,
    question: AptitudeQuestion,
    selected_option: int,
) -> AptitudeAnswer:
    """Build the answer row (correctness snapshotted from the stored key)."""
    return AptitudeAnswer(
        aptitude_test_id=test.id,
        question_id=question.id,
        selected_option=selected_option,
        is_correct=selected_option == question.correct_option_index,
    )


def record_answer(
    test: AptitudeTest,
    question: AptitudeQuestion,
    selected_option: int,
) -> bool:
    """Upsert the candidate's answer; returns True when the row was created.

    `(aptitude_test_id, question_id)` is unique, so re-answering the same
    question updates ONE row instead of creating a duplicate submission.
    """
    existing = next(
        (a for a in (test.answers or []) if a.question_id == question.id),
        None,
    )
    is_correct = selected_option == question.correct_option_index
    if existing is None:
        test.answers.append(build_answer_row(test, question, selected_option))
        return True
    existing.selected_option = selected_option
    existing.is_correct = is_correct
    existing.answered_at = datetime.utcnow()
    return False


# ---------------------------------------------------------------------------
# Scoring + finalization
# ---------------------------------------------------------------------------

def compute_results(
    questions: List[Dict[str, Any]],
    answered: Dict[int, int],
    total: int,
    pass_threshold_value: int,
    expired: bool = False,
) -> Dict[str, Any]:
    """Score a test from its questions + answered map (pure; reused scoring)."""
    return _compute_results(
        questions,
        answered,
        total,
        pass_threshold_value,
        expired=expired,
    )


def apply_results(
    test: AptitudeTest,
    results: Dict[str, Any],
    notice: Optional[str] = None,
) -> None:
    """Flatten computed results onto the test row (no commit)."""
    test.status = AssessmentStatusEnum.completed
    test.completed_at = datetime.utcnow()
    test.score = results["score"]
    test.total_scored = results["total"]
    test.percentage = results["percentage"]
    test.correct_count = results["correct_count"]
    test.incorrect_count = results["incorrect_count"]
    test.unanswered_count = results["unanswered_count"]
    test.passed = results["passed"]
    test.pass_percentage = results["pass_percentage"]
    test.category_performance = results["category_performance"]
    test.expired = bool(results.get("expired", False)) or bool(test.expired)
    if notice:
        test.result_notice = notice


def build_answered_map(test: AptitudeTest) -> Dict[int, int]:
    """Map question_index -> selected option from the test's answers."""
    index_by_question_id = {
        q.id: q.question_index for q in (test.questions or [])
    }
    answered: Dict[int, int] = {}
    for answer in test.answers or []:
        qindex = index_by_question_id.get(answer.question_id)
        if qindex is not None:
            answered[qindex] = answer.selected_option
    return answered


def finalize_test(test: AptitudeTest, expired: bool = False) -> Dict[str, Any]:
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
        for q in (test.questions or [])
    ]
    answered = build_answered_map(test)
    threshold = test.pass_percentage or pass_threshold()
    results = compute_results(
        questions,
        answered,
        test.total_questions or len(questions),
        threshold,
        expired=expired,
    )
    notice = EXPIRY_NOTICE if expired else None
    apply_results(test, results, notice=notice)
    return results
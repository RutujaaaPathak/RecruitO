# pyrefly: ignore [missing-import]
"""Coding test service: question bank, test lifecycle, and scoring.

Provides a deterministic question bank of programming problems (no LLM
dependency).  Problems include sample cases (shown to candidates) and hidden
cases (used only server-side for scoring).

Security invariant: ``hidden_cases`` are stored on ``CodingProblem`` rows
and NEVER serialized — the API only returns ``sample_cases``.
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models import (
    CodingProblem,
    CodingSubmission,
    CodingTest,
    CodingTestStatusEnum,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_PROBLEM_COUNT = 5
DEFAULT_PASS_PERCENTAGE = 60
DEFAULT_TIME_LIMIT_SECONDS = 5
DEFAULT_MAX_CODE_LENGTH = 64 * 1024

SUPPORTED_LANGUAGES: List[str] = ["python", "java", "cpp"]


def _clamp(raw: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def problem_count() -> int:
    """Number of problems per test (``CODING_TEST_PROBLEM_COUNT``)."""
    raw = os.getenv("CODING_TEST_PROBLEM_COUNT", str(DEFAULT_PROBLEM_COUNT))
    return _clamp(raw, DEFAULT_PROBLEM_COUNT, 1, 20)


def pass_threshold() -> int:
    """Percentage required to pass (``CODING_TEST_PASS_PERCENTAGE``)."""
    raw = os.getenv(
        "CODING_TEST_PASS_PERCENTAGE", str(DEFAULT_PASS_PERCENTAGE)
    )
    return _clamp(raw, DEFAULT_PASS_PERCENTAGE, 1, 100)


def time_limit_seconds() -> int:
    """Per-test-case time limit in seconds (``CODING_TEST_TIME_LIMIT_SECONDS``)."""
    raw = os.getenv(
        "CODING_TEST_TIME_LIMIT_SECONDS", str(DEFAULT_TIME_LIMIT_SECONDS)
    )
    return _clamp(raw, DEFAULT_TIME_LIMIT_SECONDS, 1, 30)


def max_code_length() -> int:
    """Maximum code length in characters (``CODING_TEST_MAX_CODE_LENGTH``)."""
    raw = os.getenv(
        "CODING_TEST_MAX_CODE_LENGTH", str(DEFAULT_MAX_CODE_LENGTH)
    )
    return _clamp(raw, DEFAULT_MAX_CODE_LENGTH, 1024, 256 * 1024)


# ---------------------------------------------------------------------------
# Question bank (5 problems with sample + hidden test cases)
# ---------------------------------------------------------------------------

QUESTION_BANK: List[Dict[str, Any]] = [
    {
        "title": "Two Sum",
        "category": "arrays",
        "difficulty": "easy",
        "description": (
            "Given an array of integers `nums` and an integer `target`, return "
            "the indices of the two numbers that add up to `target`.\n\n"
            "You may assume that each input has exactly one solution, and you "
            "may not use the same element twice.\n\n"
            "Return the answer as two space-separated 0-based indices in any "
            "order."
        ),
        "input_format": (
            "Line 1: An integer N (the size of the array)\n"
            "Line 2: N space-separated integers\n"
            "Line 3: The target integer"
        ),
        "output_format": "Two space-separated integers (0-based indices)",
        "constraints": (
            "2 ≤ N ≤ 1000\n-10^9 ≤ nums[i] ≤ 10^9\n"
            "Exactly one valid answer exists"
        ),
        "sample_cases": [
            {"input": "4\n2 7 11 15\n9", "expected": "0 1"},
            {"input": "3\n3 2 4\n6", "expected": "1 2"},
        ],
        "hidden_cases": [
            {"input": "2\n3 3\n6", "expected": "0 1"},
            {"input": "5\n1 5 3 7 2\n9", "expected": "1 3"},
            {"input": "4\n-1 -2 -3 -4\n-6", "expected": "1 3"},
        ],
    },
    {
        "title": "Palindrome Check",
        "category": "strings",
        "difficulty": "easy",
        "description": (
            "Check if a given string is a palindrome.  The comparison should "
            "be case-insensitive — uppercase and lowercase letters are "
            "considered the same."
        ),
        "input_format": "A single line containing the string to check",
        "output_format": (
            '"true" if the string is a palindrome, "false" otherwise'
        ),
        "constraints": "0 ≤ string length ≤ 10000",
        "sample_cases": [
            {"input": "racecar", "expected": "true"},
            {"input": "hello", "expected": "false"},
        ],
        "hidden_cases": [
            {"input": "RaceCar", "expected": "true"},
            {"input": "A", "expected": "true"},
            {"input": "", "expected": "true"},
        ],
    },
    {
        "title": "FizzBuzz",
        "category": "basics",
        "difficulty": "easy",
        "description": (
            'Print numbers from 1 to N (inclusive).  For each number:\n'
            '- If it is a multiple of both 3 and 5, print "FizzBuzz"\n'
            '- If it is a multiple of 3 (but not 5), print "Fizz"\n'
            '- If it is a multiple of 5 (but not 3), print "Buzz"\n'
            "- Otherwise, print the number itself"
        ),
        "input_format": "A single integer N",
        "output_format": "N lines, one output per line",
        "constraints": "1 ≤ N ≤ 100",
        "sample_cases": [
            {"input": "5", "expected": "1\n2\nFizz\n4\nBuzz"},
            {"input": "1", "expected": "1"},
        ],
        "hidden_cases": [
            {"input": "3", "expected": "1\n2\nFizz"},
            {
                "input": "15",
                "expected": (
                    "1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n"
                    "11\nFizz\n13\n14\nFizzBuzz"
                ),
            },
            {"input": "6", "expected": "1\n2\nFizz\n4\nBuzz\nFizz"},
        ],
    },
    {
        "title": "Maximum Subarray Sum",
        "category": "algorithms",
        "difficulty": "medium",
        "description": (
            "Given an array of integers, find the contiguous subarray "
            "(containing at least one element) that has the largest sum, and "
            "return that sum."
        ),
        "input_format": (
            "Line 1: An integer N (the size of the array)\n"
            "Line 2: N space-separated integers"
        ),
        "output_format": "A single integer — the maximum subarray sum",
        "constraints": "1 ≤ N ≤ 100000\n-100000 ≤ nums[i] ≤ 100000",
        "sample_cases": [
            {"input": "5\n-2 1 -3 4 -1", "expected": "4"},
            {"input": "3\n1 2 3", "expected": "6"},
        ],
        "hidden_cases": [
            {"input": "6\n-2 1 -3 4 -1 2", "expected": "5"},
            {"input": "4\n-1 -2 -3 -4", "expected": "-1"},
            {"input": "1\n42", "expected": "42"},
        ],
    },
    {
        "title": "Valid Parentheses",
        "category": "stack",
        "difficulty": "easy",
        "description": (
            "Given a string containing only the characters '(', ')', '{', '}', "
            "'[' and ']', determine if the input string is valid.\n\n"
            "A string is valid if:\n"
            "1. Open brackets are closed by the same type of bracket.\n"
            "2. Open brackets are closed in the correct order.\n"
            "3. Every close bracket has a corresponding open bracket."
        ),
        "input_format": "A single line containing the bracket string",
        "output_format": (
            '"true" if the string is valid, "false" otherwise'
        ),
        "constraints": (
            "0 ≤ string length ≤ 10000\n"
            "The string will only contain bracket characters"
        ),
        "sample_cases": [
            {"input": "()[]{}", "expected": "true"},
            {"input": "(]", "expected": "false"},
        ],
        "hidden_cases": [
            {"input": "{[]}", "expected": "true"},
            {"input": "([)]", "expected": "false"},
            {"input": "", "expected": "true"},
        ],
    },
]


def bank_problem_at(index: int) -> Dict[str, Any]:
    """Return the bank problem at *index* (cycles if index >= bank size)."""
    return dict(QUESTION_BANK[index % len(QUESTION_BANK)])


# ---------------------------------------------------------------------------
# Test creation
# ---------------------------------------------------------------------------


def create_test_problems(
    coding_test_id: int,
    count: int,
) -> List[CodingProblem]:
    """Build ``CodingProblem`` rows from the question bank."""
    problems: List[CodingProblem] = []
    for i in range(count):
        bank = bank_problem_at(i)
        problems.append(
            CodingProblem(
                coding_test_id=coding_test_id,
                problem_index=i,
                title=bank["title"],
                category=bank["category"],
                difficulty=bank["difficulty"],
                description=bank["description"],
                input_format=bank["input_format"],
                output_format=bank["output_format"],
                constraints=bank["constraints"],
                sample_cases=bank["sample_cases"],
                hidden_cases=bank["hidden_cases"],
                time_limit_seconds=time_limit_seconds(),
                supported_languages=SUPPORTED_LANGUAGES,
            )
        )
    return problems


# ---------------------------------------------------------------------------
# Scoring (pure, test-friendly)
# ---------------------------------------------------------------------------


def compute_problem_score(passed_cases: int, total_cases: int) -> int:
    """Return a 0–100 percentage score for a single problem."""
    if total_cases <= 0:
        return 0
    return int(round((passed_cases / total_cases) * 100))


def compute_test_aggregate(
    submissions: List[Dict[str, Any]],
    total_problems: int,
    threshold: int,
) -> Dict[str, Any]:
    """Compute the aggregate score for a coding test.

    *submissions*: list of dicts with ``score`` (0–100) and ``status``.
    Unscored problems count as 0.  Pure — no DB, no I/O.
    """
    if total_problems <= 0:
        return {"score": 0, "passed": False, "solved_count": 0}

    total_score = sum(s.get("score", 0) for s in submissions)
    avg = int(round(total_score / total_problems))
    solved = sum(1 for s in submissions if s.get("status") == "passed")

    return {
        "score": avg,
        "passed": avg >= threshold,
        "solved_count": solved,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_problem_by_index(
    test: CodingTest, index: int
) -> Optional[CodingProblem]:
    """Find a problem by its ``problem_index``."""
    return next(
        (p for p in (test.problems or []) if p.problem_index == index),
        None,
    )


def get_submission(
    test: CodingTest, problem_id: int
) -> Optional[CodingSubmission]:
    """Find the (only) submission for a problem."""
    return next(
        (s for s in (test.submissions or []) if s.problem_id == problem_id),
        None,
    )


def is_test_answerable(test: CodingTest) -> bool:
    """Return ``True`` when the test can still accept submissions."""
    return test.status == CodingTestStatusEnum.in_progress


def finalize_test(test: CodingTest) -> Dict[str, Any]:
    """Compute and apply aggregate results.  Idempotent."""
    threshold = test.pass_percentage or pass_threshold()
    subs = [
        {"score": s.score or 0, "status": s.status}
        for s in (test.submissions or [])
    ]
    results = compute_test_aggregate(subs, test.total_problems, threshold)

    test.status = CodingTestStatusEnum.completed
    test.completed_at = datetime.utcnow()
    test.score = results["score"]
    test.passed = results["passed"]
    test.solved_count = results["solved_count"]

    return results

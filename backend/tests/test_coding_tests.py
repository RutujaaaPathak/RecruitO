"""Tests for the Coding Test module: configuration, question bank validity,
scoring, test lifecycle, ownership/RBAC, code validation, output
normalization, hidden-case security (hidden cases are never serialized), and
the sandboxed code executor (Python runnable in CI).
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
    CodingProblem,
    CodingSubmission,
    CodingTest,
    CodingTestStatusEnum,
    McqAssessment,
    RoleEnum,
    User,
)
from app.routes.coding_tests import (  # noqa: E402
    _detail,
    _ensure_answerable,
    _list_out,
    _owned_application,
    _owned_test,
    _problem_out,
    _submission_out,
)
from app.services.code_executor import (  # noqa: E402
    MAX_CODE_LENGTH,
    execute_code,
    normalize_output,
    validate_code,
)
from app.services.coding_tests import (  # noqa: E402
    DEFAULT_PASS_PERCENTAGE,
    DEFAULT_PROBLEM_COUNT,
    DEFAULT_TIME_LIMIT_SECONDS,
    QUESTION_BANK,
    SUPPORTED_LANGUAGES,
    compute_problem_score,
    compute_test_aggregate,
    create_test_problems,
    finalize_test,
    get_problem_by_index,
    is_test_answerable,
    max_code_length,
    pass_threshold,
    problem_count,
    time_limit_seconds,
)


def _user(role, id_=1):
    return User(id=id_, name="x", email=f"{id_}@x.com", password="p", role=role)


def _app(user_id=1, id_=1):
    return SimpleNamespace(id=id_, user_id=user_id)


def _test(**kw):
    defaults = dict(
        id=10,
        user_id=1,
        application_id=2,
        status=CodingTestStatusEnum.in_progress,
        total_problems=2,
        solved_count=0,
        score=None,
        passed=None,
        pass_percentage=DEFAULT_PASS_PERCENTAGE,
        started_at=datetime(2026, 1, 1, 10, 0, 0),
        created_at=datetime(2026, 1, 1, 10, 0, 0),
        updated_at=datetime(2026, 1, 1, 10, 0, 0),
    )
    defaults.update(kw)
    return CodingTest(**defaults)


def _problem(pid, index, **kw):
    defaults = dict(
        id=pid,
        coding_test_id=10,
        problem_index=index,
        title="Two Sum",
        category="arrays",
        difficulty="easy",
        description="Find the two numbers that sum to target.",
        input_format="N\nnums\ntarget",
        output_format="indices",
        constraints="2 <= N <= 1000",
        sample_cases=[{"input": "3\n1 2 3\n5", "expected": "1 2"}],
        hidden_cases=[
            {"input": "2\n3 3\n6", "expected": "0 1"},
            {"input": "4\n-1 -2 -3 -4\n-6", "expected": "1 3"},
        ],
        time_limit_seconds=5,
        supported_languages=SUPPORTED_LANGUAGES,
    )
    defaults.update(kw)
    return CodingProblem(**defaults)


def _submission(pid, **kw):
    defaults = dict(
        id=pid,
        coding_test_id=10,
        problem_id=100 + pid,
        user_id=1,
        language="python",
        code="print(1)",
        status="passed",
        passed_cases=2,
        total_cases=2,
        score=100,
        execution_time_ms=12,
        error_message=None,
        results=[
            {"case_index": 0, "passed": True, "status": "passed", "time_ms": 6},
            {"case_index": 1, "passed": True, "status": "passed", "time_ms": 6},
        ],
        created_at=datetime(2026, 1, 1, 10, 1, 0),
        updated_at=datetime(2026, 1, 1, 10, 1, 0),
    )
    defaults.update(kw)
    return CodingSubmission(**defaults)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def test_default_configuration():
    assert problem_count() == DEFAULT_PROBLEM_COUNT == 5
    assert pass_threshold() == DEFAULT_PASS_PERCENTAGE == 60
    assert time_limit_seconds() == DEFAULT_TIME_LIMIT_SECONDS == 5
    assert SUPPORTED_LANGUAGES == ["python", "java", "cpp"]


def test_env_configuration_parses_and_clamps(monkeypatch):
    monkeypatch.setenv("CODING_TEST_PROBLEM_COUNT", "3")
    assert problem_count() == 3
    monkeypatch.setenv("CODING_TEST_PROBLEM_COUNT", "0")
    assert problem_count() == 1
    monkeypatch.setenv("CODING_TEST_PROBLEM_COUNT", "99")
    assert problem_count() == 20
    monkeypatch.setenv("CODING_TEST_PROBLEM_COUNT", "abc")
    assert problem_count() == DEFAULT_PROBLEM_COUNT

    monkeypatch.setenv("CODING_TEST_PASS_PERCENTAGE", "70")
    assert pass_threshold() == 70
    monkeypatch.setenv("CODING_TEST_PASS_PERCENTAGE", "0")
    assert pass_threshold() == 1
    monkeypatch.setenv("CODING_TEST_PASS_PERCENTAGE", "abc")
    assert pass_threshold() == DEFAULT_PASS_PERCENTAGE

    monkeypatch.setenv("CODING_TEST_TIME_LIMIT_SECONDS", "8")
    assert time_limit_seconds() == 8
    monkeypatch.setenv("CODING_TEST_TIME_LIMIT_SECONDS", "0")
    assert time_limit_seconds() == 1
    monkeypatch.setenv("CODING_TEST_TIME_LIMIT_SECONDS", "abc")
    assert time_limit_seconds() == DEFAULT_TIME_LIMIT_SECONDS

    monkeypatch.setenv("CODING_TEST_MAX_CODE_LENGTH", "2000")
    assert max_code_length() == 2000
    monkeypatch.setenv("CODING_TEST_MAX_CODE_LENGTH", "abc")
    assert max_code_length() == 64 * 1024


# ---------------------------------------------------------------------------
# Question bank
# ---------------------------------------------------------------------------

def test_question_bank_is_valid():
    assert len(QUESTION_BANK) >= 4
    titles = set()
    for problem in QUESTION_BANK:
        assert problem["title"]
        assert problem["category"]
        assert problem["difficulty"] in ("easy", "medium", "hard")
        assert problem["description"]
        assert problem["input_format"]
        assert problem["output_format"]
        assert problem["constraints"]
        assert len(problem["sample_cases"]) >= 2
        assert len(problem["hidden_cases"]) >= 3
        for case in problem["sample_cases"] + problem["hidden_cases"]:
            assert "input" in case and "expected" in case
        titles.add(problem["title"])
    assert len(titles) == len(QUESTION_BANK)  # unique titles


def test_create_test_problems_builds_rows():
    problems = create_test_problems(7, 3)
    assert len(problems) == 3
    assert [p.problem_index for p in problems] == [0, 1, 2]
    for p in problems:
        assert p.coding_test_id == 7
        assert p.sample_cases
        assert p.hidden_cases
        assert p.supported_languages == SUPPORTED_LANGUAGES
    # Hidden cases match the bank exactly (grading stays deterministic).
    assert problems[0].hidden_cases == QUESTION_BANK[0]["hidden_cases"]


# ---------------------------------------------------------------------------
# Output normalization / code validation
# ---------------------------------------------------------------------------

def test_normalize_output_compares_cleanly():
    assert normalize_output("hello\n") == "hello"
    assert normalize_output("hello\n\n") == "hello"
    assert normalize_output("hello\r\nworld\r\n") == "hello\nworld"
    assert normalize_output("   ") == ""
    assert normalize_output("a  \nb") == "a\nb"


def test_validate_code_rejects_empty_and_oversized():
    with pytest.raises(ValueError):
        validate_code("   ", "python")
    with pytest.raises(ValueError):
        validate_code("", "python")
    with pytest.raises(ValueError):
        validate_code("x" * (MAX_CODE_LENGTH + 1), "python")
    with pytest.raises(ValueError):
        validate_code("print(1)", "ruby")
    validate_code("print(1)", "python")  # no raise


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_compute_problem_score():
    assert compute_problem_score(0, 3) == 0
    assert compute_problem_score(1, 4) == 25
    assert compute_problem_score(2, 3) == 67  # rounds
    assert compute_problem_score(3, 3) == 100
    assert compute_problem_score(0, 0) == 0  # no cases -> 0


def test_compute_test_aggregate_averages_problem_scores():
    submissions = [
        {"score": 100, "status": "passed"},
        {"score": 50, "status": "failed"},
        {"score": 0, "status": "error"},
    ]
    results = compute_test_aggregate(submissions, 4, 60)
    assert results["score"] == int(round((100 + 50 + 0) / 4))  # 38
    assert results["passed"] is False
    assert results["solved_count"] == 1

    submissions_all_pass = [{"score": 100, "status": "passed"}] * 5
    assert compute_test_aggregate(submissions_all_pass, 5, 60)["passed"] is True
    assert compute_test_aggregate([], 5, 60)["score"] == 0
    assert compute_test_aggregate([], 0, 60)["score"] == 0


# ---------------------------------------------------------------------------
# Test lifecycle helpers (finalize, get_problem_by_index, answerable)
# ---------------------------------------------------------------------------

def test_finalize_test_computes_aggregate_and_marks_completed():
    test = _test()
    p0 = _problem(100, 0)
    p1 = _problem(101, 1)
    test.problems = [p0, p1]
    test.total_problems = 2
    test.submissions = [
        _submission(1, problem_id=p0.id, status="passed", passed_cases=2,
                    total_cases=2, score=100),
        _submission(2, problem_id=p1.id, status="failed", passed_cases=1,
                    total_cases=2, score=50),
    ]

    results = finalize_test(test)

    assert test.status == CodingTestStatusEnum.completed
    assert test.completed_at is not None
    assert results["score"] == 75  # (100 + 50) / 2
    assert results["passed"] is True  # 75 >= 60
    assert results["solved_count"] == 1
    assert test.score == 75
    assert test.passed is True
    assert test.solved_count == 1


def test_finalize_test_with_no_submissions_scores_zero():
    test = _test(total_problems=3)
    test.problems = [_problem(100, 0), _problem(101, 1), _problem(102, 2)]
    test.submissions = []
    results = finalize_test(test)
    assert results["score"] == 0
    assert results["passed"] is False
    assert test.status == CodingTestStatusEnum.completed


def test_get_problem_by_index_finds_and_misses():
    test = _test()
    test.problems = [_problem(100, 0), _problem(101, 1), _problem(102, 2)]
    assert get_problem_by_index(test, 1).id == 101
    assert get_problem_by_index(test, 9) is None


def test_is_test_answerable():
    assert is_test_answerable(_test()) is True
    assert is_test_answerable(_test(status=CodingTestStatusEnum.completed)) is False


# ---------------------------------------------------------------------------
# Serialization / hidden-case security
# ---------------------------------------------------------------------------

def test_problem_out_never_exposes_hidden_cases():
    p = _problem(100, 0)
    out = _problem_out(p)
    payload = out.model_dump()
    assert payload["sample_cases"][0]["input"] == "3\n1 2 3\n5"
    assert "hidden_cases" not in payload
    assert "hidden" not in " ".join(payload.keys()).lower()


def test_detail_never_exposes_hidden_cases_anywhere():
    test = _test()
    p0 = _problem(100, 0)
    p1 = _problem(101, 1)
    test.problems = [p0, p1]
    test.submissions = [
        _submission(1, problem_id=p0.id, status="passed"),
    ]

    detail = _detail(test)
    raw = detail.model_dump_json()
    assert "hidden_cases" not in raw
    assert "hidden" not in raw.lower()
    assert len(detail.problems) == 2
    assert detail.problems[0].submission is not None
    assert detail.problems[1].submission is None
    for p_out in detail.problems:
        for case in p_out.sample_cases:
            assert "expected" in case  # samples are public


def test_submission_out_redacts_hidden_execution_details():
    sub = _submission(
        1,
        results=[
            {"case_index": 0, "passed": True, "status": "passed", "time_ms": 6},
            {"case_index": 1, "passed": False, "status": "wrong_answer", "time_ms": 7},
        ],
        error_message="oops: RuntimeError",
    )
    out = _submission_out(sub)
    payload = out.model_dump()
    # Per-case results only carry status/time — never hidden I/O or expected.
    assert all(
        "stdout" not in r or r["stdout"] == ""
        for r in payload["results"]
    )
    assert all(
        "stderr" not in r or r["stderr"] == ""
        for r in payload["results"]
    )
    assert payload["error_message"] == "oops: RuntimeError"
    assert payload["passed_cases"] == 2
    assert payload["total_cases"] == 2
    assert payload["score"] == 100


def test_list_out_shape():
    test = _test(status=CodingTestStatusEnum.completed, score=80, passed=True)
    out = _list_out(test)
    assert out.score == 80
    assert out.passed is True
    assert out.pass_percentage == DEFAULT_PASS_PERCENTAGE


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
        RoleChecker(["user"])(current_user=_user(RoleEnum.company))
    assert exc.value.status_code == 403


def test_owned_application_rules():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _owned_application(FakeSession([]), _user(RoleEnum.user), 1)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        _owned_application(
            FakeSession([_app(user_id=2)]), _user(RoleEnum.user, id_=1), 1
        )
    assert exc.value.status_code == 403
    app_ = _owned_application(
        FakeSession([_app(user_id=1)]), _user(RoleEnum.user, id_=1), 1
    )
    assert app_.id == 1


def test_owned_test_rules():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _owned_test(FakeSession([]), _user(RoleEnum.user), 10)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        _owned_test(FakeSession([_test(user_id=2, id=10)]),
                    _user(RoleEnum.user, id_=1), 10)
    assert exc.value.status_code == 403
    test = _owned_test(FakeSession([_test(user_id=1, id=10)]),
                       _user(RoleEnum.user, id_=1), 10)
    assert test.id == 10


def test_ensure_answerable_rejects_completed_test():
    from fastapi import HTTPException

    completed = _test(status=CodingTestStatusEnum.completed)
    with pytest.raises(HTTPException) as exc:
        _ensure_answerable(completed)
    assert exc.value.status_code == 400


def test_ensure_answerable_accepts_in_progress():
    _ensure_answerable(_test())  # no raise


# ---------------------------------------------------------------------------
# Ability to build submissions via product helpers (upsert shape)
# ---------------------------------------------------------------------------

def test_supported_categories_are_castable_to_enum():
    from app.models import CodingTestStatusEnum as E
    assert E.in_progress.value == "in_progress"
    assert E.completed.value == "completed"


# ---------------------------------------------------------------------------
# Sandboxed code executor (real Python available in this environment)
# ---------------------------------------------------------------------------

ECHO = "import sys\nprint(sys.stdin.read().strip())"
FIZZ = (
    "import sys\nn = int(sys.stdin.read().strip())\n"
    "for i in range(1, n + 1):\n"
    "    if i % 15 == 0: print('FizzBuzz')\n"
    "    elif i % 3 == 0: print('Fizz')\n"
    "    elif i % 5 == 0: print('Buzz')\n"
    "    else: print(i)"
)
# Problem 1 "Two Sum" reference solution (bank index 0).
TWO_SUM = (
    "import sys\n"
    "data = list(map(int, sys.stdin.read().split()))\n"
    "n, target = data[0], data[-1]\n"
    "nums = data[1:1 + n]\n"
    "seen = {}\n"
    "for i, x in enumerate(nums):\n"
    "    need = target - x\n"
    "    if need in seen:\n"
    "        print(seen[need], i); break\n"
    "    seen[x] = i"
)


def test_execute_python_correct_and_wrong():
    cases = [
        {"input": "3\n1 2 3\n5", "expected": "1 2"},
        {"input": "2\n3 3\n6", "expected": "0 1"},
    ]
    good = execute_code("python", TWO_SUM, cases)
    assert good.compile_error is False
    assert [r.status for r in good.test_results] == ["passed", "passed"]
    assert good.test_results[0].passed is True

    wrong = execute_code(
        "python", "import sys\nprint('0 0')", cases
    )
    assert [r.status for r in wrong.test_results] == ["wrong_answer", "wrong_answer"]


def test_execute_python_fizzbuzz_multiline():
    cases = [{"input": "5", "expected": "1\n2\nFizz\n4\nBuzz"}]
    result = execute_code("python", FIZZ, cases)
    assert result.test_results[0].status == "passed"
    # Trailing whitespace tolerance: extra blank line still passes.
    padded = execute_code(
        "python",
        "import sys\nn = int(sys.stdin.read().strip())\n"
        "for i in range(1, n + 1):\n    print(i)",
        [{"input": "3", "expected": "1\n2\n3\n\n"}],
    )
    assert padded.test_results[0].status == "passed"


def test_execute_python_runtime_error_and_timeout():
    cases = [{"input": "", "expected": ""}]
    broken = execute_code("python", "print(1 / 0)", cases)
    assert broken.test_results[0].status == "runtime_error"

    slow = execute_code(
        "python",
        "while True:\n    pass",
        cases,
        time_limit=0.5,
    )
    assert slow.test_results[0].status == "timeout"


def test_execute_code_validates_language():
    with pytest.raises(ValueError):
        execute_code("ruby", "puts 1", [{"input": "", "expected": "1"}])


def test_execute_python_io_preserved():
    cases = [{"input": "hello world\n", "expected": "hello world"}]
    result = execute_code("python", ECHO, cases)
    assert result.test_results[0].status == "passed"


_MISSING_TOOLS = __import__("shutil").which("javac") is None, __import__("shutil").which("g++") is None


@pytest.mark.skipif(_MISSING_TOOLS[0], reason="javac not installed")
def test_execute_java_two_sum():
    code = "\n".join(
        [
            "import java.util.*;",
            "public class Main {",
            "  public static void main(String[] args) {",
            "    Scanner sc = new Scanner(System.in);",
            "    int n = sc.nextInt();",
            "    int target = sc.nextInt();",
            "    int[] a = new int[n];",
            "    for (int i = 0; i < n; i++) a[i] = sc.nextInt();",
            "    for (int i = 0; i < n; i++)",
            "      for (int k = i + 1; k < n; k++)",
            '        if (a[i] + a[k] == target) { System.out.println(i + " " + k); return; }',
            "  }",
            "}",
        ]
    )
    cases = [{"input": "3\n1 2 3\n5", "expected": "0 2"}]
    result = execute_code("java", code, cases)
    assert [r.status for r in result.test_results] == ["passed"]


@pytest.mark.skipif(_MISSING_TOOLS[1], reason="g++ not installed")
def test_execute_cpp_two_sum():
    code = "\n".join(
        [
            "#include <bits/stdc++.h>",
            "using namespace std;",
            "int main() {",
            "  int n, target; cin >> n >> target;",
            "  vector<int> a(n);",
            "  for (int i = 0; i < n; i++) cin >> a[i];",
            "  for (int i = 0; i < n; i++)",
            "    for (int k = i + 1; k < n; k++)",
            "      if (a[i] + a[k] == target) { cout << i << ' ' << k << '\\n'; return 0; }",
            "}",
        ]
    )
    cases = [{"input": "3\n1 2 3\n5", "expected": "0 2"}]
    result = execute_code("cpp", code, cases)
    assert [r.status for r in result.test_results] == ["passed"]


@pytest.mark.skipif(_MISSING_TOOLS[0], reason="javac not installed")
def test_execute_java_compile_error():
    cases = [{"input": "", "expected": ""}]
    result = execute_code("java", "public class Main { not java }", cases)
    assert result.compile_error is True
    assert result.test_results[0].status == "compile_error"


@pytest.mark.skipif(_MISSING_TOOLS[1], reason="g++ not installed")
def test_execute_cpp_compile_error():
    cases = [{"input": "", "expected": ""}]
    result = execute_code("cpp", "int main() { not cpp }", cases)
    assert result.compile_error is True
    assert result.test_results[0].status == "compile_error"
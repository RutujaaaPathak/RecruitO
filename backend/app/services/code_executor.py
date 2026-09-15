# pyrefly: ignore [missing-import]
"""Sandboxed code execution for the coding test module.

Runs candidate code in isolated subprocesses with per-test-case time limits,
output truncation, and code length validation.  Compilers (Java, C++) are
invoked with their own timeout.

Security notes
--------------
- Python runs in isolated mode (``-I``) to block user site-packages.
- All subprocesses use ``CREATE_NO_WINDOW`` to avoid spawning visible windows.
- Output is capped at ``MAX_OUTPUT_BYTES`` to prevent memory exhaustion.
- Code length is validated before execution.

This module is NOT used by the chatbot, mock interview, or MCQ modules.
"""

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TIME_LIMIT_SECONDS = 5
DEFAULT_MEMORY_LIMIT_MB = 256
MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB per stream
MAX_CODE_LENGTH = 64 * 1024  # 64 KB

Language = Literal["python", "java", "cpp"]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TestCaseResult:
    case_index: int
    passed: bool
    status: str  # passed | wrong_answer | runtime_error | timeout | compile_error
    stdout: str = ""
    stderr: str = ""
    time_ms: int = 0
    exit_code: Optional[int] = None


@dataclass
class ExecutionResult:
    compile_error: bool = False
    compile_stderr: str = ""
    test_results: List[TestCaseResult] = field(default_factory=list)
    total_time_ms: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def validate_code(code: str, language: str) -> None:
    """Raise ``ValueError`` if the code is empty, too long, or unsupported."""
    if not code or not code.strip():
        raise ValueError("Code cannot be empty")
    if len(code) > MAX_CODE_LENGTH:
        raise ValueError(
            f"Code exceeds maximum length of {MAX_CODE_LENGTH:,} characters"
        )
    if language not in ("python", "java", "cpp"):
        raise ValueError(f"Unsupported language: {language}")


def normalize_output(text: str) -> str:
    """Normalize output for comparison: strip trailing whitespace per line,
    normalize line endings, and remove trailing blank lines."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip() for line in lines]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _truncate(text: str, max_bytes: int = MAX_OUTPUT_BYTES) -> str:
    """Truncate output to *max_bytes* and append a marker."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    return (
        encoded[:max_bytes].decode("utf-8", errors="replace")
        + "\n[output truncated]"
    )


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------

_CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run_command(
    cmd: List[str],
    input_text: str = "",
    cwd: Optional[str] = None,
    timeout: float = DEFAULT_TIME_LIMIT_SECONDS,
    env: Optional[Dict[str, str]] = None,
) -> tuple:
    """Run *cmd* with a hard timeout.

    Returns ``(stdout, stderr, returncode, time_ms, timed_out)``.
    """
    full_env = os.environ.copy()
    full_env["PYTHONDONTWRITEBYTECODE"] = "1"
    full_env["PYTHONUNBUFFERED"] = "1"
    if env:
        full_env.update(env)

    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=full_env,
            creationflags=_CREATE_FLAGS,
        )
        try:
            stdout, stderr = proc.communicate(
                input=input_text.encode("utf-8") if input_text else None,
                timeout=timeout,
            )
            elapsed = int((time.monotonic() - start) * 1000)
            return (
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
                proc.returncode,
                elapsed,
                False,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            elapsed = int((time.monotonic() - start) * 1000)
            return "", "Time limit exceeded", -1, elapsed, True
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        return "", str(exc), -1, elapsed, False


# ---------------------------------------------------------------------------
# Language-specific compilation
# ---------------------------------------------------------------------------


def _compile_cpp(
    source_path: str, exe_path: str, cwd: str, timeout: float
) -> tuple:
    """Compile C++.  Returns ``(success, stderr, time_ms)``."""
    cmd = ["g++", "-std=c++17", "-O2", "-o", exe_path, source_path]
    stderr, _, rc, time_ms, _ = _run_command(cmd, cwd=cwd, timeout=timeout)
    return rc == 0, _truncate(stderr), time_ms


def _compile_java(
    source_path: str, class_dir: str, timeout: float
) -> tuple:
    """Compile Java.  Returns ``(success, stderr, time_ms)``."""
    cmd = ["javac", "-d", class_dir, source_path]
    stderr, _, rc, time_ms, _ = _run_command(cmd, cwd=class_dir, timeout=timeout)
    return rc == 0, _truncate(stderr), time_ms


# ---------------------------------------------------------------------------
# Per-language runner (boilerplate kept inside each branch for clarity)
# ---------------------------------------------------------------------------


def _run_python(
    source: str,
    test_cases: List[Dict[str, Any]],
    tmp_dir: str,
    time_limit: float,
    result: ExecutionResult,
) -> None:
    for i, tc in enumerate(test_cases):
        stdout, stderr, rc, time_ms, timed_out = _run_command(
            [sys.executable, "-I", source],
            input_text=tc.get("input", ""),
            cwd=tmp_dir,
            timeout=time_limit,
        )
        if timed_out:
            result.test_results.append(
                TestCaseResult(
                    case_index=i,
                    passed=False,
                    status="timeout",
                    stderr="Time limit exceeded",
                    time_ms=time_ms,
                )
            )
            continue
        if rc != 0:
            result.test_results.append(
                TestCaseResult(
                    case_index=i,
                    passed=False,
                    status="runtime_error",
                    stdout=_truncate(stdout),
                    stderr=_truncate(stderr),
                    time_ms=time_ms,
                    exit_code=rc,
                )
            )
            continue
        expected = normalize_output(tc.get("expected", ""))
        actual = normalize_output(stdout)
        passed = actual == expected
        result.test_results.append(
            TestCaseResult(
                case_index=i,
                passed=passed,
                status="passed" if passed else "wrong_answer",
                stdout=_truncate(stdout),
                stderr=_truncate(stderr),
                time_ms=time_ms,
                exit_code=rc,
            )
        )


def _run_compiled(
    exe_cmd: List[str],
    test_cases: List[Dict[str, Any]],
    tmp_dir: str,
    time_limit: float,
    result: ExecutionResult,
) -> None:
    """Shared runner for Java / C++ after successful compilation."""
    for i, tc in enumerate(test_cases):
        stdout, stderr, rc, time_ms, timed_out = _run_command(
            exe_cmd,
            input_text=tc.get("input", ""),
            cwd=tmp_dir,
            timeout=time_limit,
        )
        if timed_out:
            result.test_results.append(
                TestCaseResult(
                    case_index=i,
                    passed=False,
                    status="timeout",
                    stderr="Time limit exceeded",
                    time_ms=time_ms,
                )
            )
            continue
        if rc != 0:
            result.test_results.append(
                TestCaseResult(
                    case_index=i,
                    passed=False,
                    status="runtime_error",
                    stdout=_truncate(stdout),
                    stderr=_truncate(stderr),
                    time_ms=time_ms,
                    exit_code=rc,
                )
            )
            continue
        expected = normalize_output(tc.get("expected", ""))
        actual = normalize_output(stdout)
        passed = actual == expected
        result.test_results.append(
            TestCaseResult(
                case_index=i,
                passed=passed,
                status="passed" if passed else "wrong_answer",
                stdout=_truncate(stdout),
                stderr=_truncate(stderr),
                time_ms=time_ms,
                exit_code=rc,
            )
        )


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------


def execute_code(
    language: str,
    code: str,
    test_cases: List[Dict[str, Any]],
    time_limit: float = DEFAULT_TIME_LIMIT_SECONDS,
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
) -> ExecutionResult:
    """Execute candidate *code* in *language* against *test_cases*.

    Each test-case dict must have ``"input"`` and ``"expected"`` string keys.
    Returns an ``ExecutionResult`` with per-case pass/fail details.
    """
    validate_code(code, language)
    result = ExecutionResult()

    if not test_cases:
        return result

    with tempfile.TemporaryDirectory(prefix="recruito_code_") as tmp_dir:
        # ------------------------------------------------------------------
        # Python
        # ------------------------------------------------------------------
        if language == "python":
            source = os.path.join(tmp_dir, "solution.py")
            with open(source, "w", encoding="utf-8") as fh:
                fh.write(code)
            _run_python(source, test_cases, tmp_dir, time_limit, result)

        # ------------------------------------------------------------------
        # Java
        # ------------------------------------------------------------------
        elif language == "java":
            source = os.path.join(tmp_dir, "Main.java")
            with open(source, "w", encoding="utf-8") as fh:
                fh.write(code)

            compile_ok, compile_err, _ = _compile_java(
                source, tmp_dir, time_limit
            )
            if not compile_ok:
                result.compile_error = True
                result.compile_stderr = compile_err
                result.test_results = [
                    TestCaseResult(
                        case_index=i,
                        passed=False,
                        status="compile_error",
                        stderr=compile_err,
                    )
                    for i in range(len(test_cases))
                ]
                return result

            _run_compiled(
                ["java", "-cp", tmp_dir, "Main"],
                test_cases,
                tmp_dir,
                time_limit,
                result,
            )

        # ------------------------------------------------------------------
        # C++
        # ------------------------------------------------------------------
        elif language == "cpp":
            source = os.path.join(tmp_dir, "solution.cpp")
            ext = ".exe" if os.name == "nt" else ""
            exe = os.path.join(tmp_dir, f"solution{ext}")
            with open(source, "w", encoding="utf-8") as fh:
                fh.write(code)

            compile_ok, compile_err, _ = _compile_cpp(
                source, exe, tmp_dir, time_limit
            )
            if not compile_ok:
                result.compile_error = True
                result.compile_stderr = compile_err
                result.test_results = [
                    TestCaseResult(
                        case_index=i,
                        passed=False,
                        status="compile_error",
                        stderr=compile_err,
                    )
                    for i in range(len(test_cases))
                ]
                return result

            _run_compiled([exe], test_cases, tmp_dir, time_limit, result)

    if result.test_results:
        result.total_time_ms = sum(r.time_ms for r in result.test_results)
    return result

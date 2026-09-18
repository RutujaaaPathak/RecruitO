# pyrefly: ignore [missing-import]
"""Sandboxed code execution for the coding test module.

Runs candidate code inside an isolated, disposable Docker container per
test-case (compilers also run in their own container) with:

- ``--network none``: no inbound or outbound network access.
- ``--read-only``: container root filesystem is read-only.
- ``--user 1000:1000``: non-root uid (the image user is uid 1000 as well).
- ``--memory`` / ``--memory-swap``: hard memory ceiling with no swap.
- ``--cpus`` / ``--pids-limit``: CPU quota and a process-count cap.
- ``--ulimit fsize``: per-file output cap so runaway writes are bounded.
- ``--tmpfs /tmp``: a bounded writable scratch volume for compilers only.

The host environment, secrets, and filesystem are never exposed: the only
mounts are a read-only ``/workspace`` holding the candidate source and a
writable ``/scratch`` holding the test input, the program's output files and
compile artifacts, plus the explicitly crafted ``-e`` variables (none by
default).  Every container is removed after the run (``docker rm -f``) and a
strict timeout kills long-running containers.

This module is NOT used by the chatbot, mock interview, or MCQ modules.
"""

import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TIME_LIMIT_SECONDS = 5
DEFAULT_MEMORY_LIMIT_MB = 256
MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB per stream
MAX_CODE_LENGTH = 64 * 1024  # 64 KB

Language = Literal["python", "java", "cpp"]

# --- Docker sandbox configuration -----------------------------------------

DOCKER_IMAGE = os.getenv("CODE_RUNNER_IMAGE", "recruito-code-runner:latest")
DOCKERFILE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "docker" / "code-runner"
)
CONTAINER_USER = 1000
CONTAINER_CPUS = float(os.getenv("CODE_RUNNER_CPUS", "1"))
CONTAINER_MAX_PIDS = int(os.getenv("CODE_RUNNER_MAX_PIDS", "256"))
CONTAINER_TMPFS_SIZE = os.getenv("CODE_RUNNER_TMPFS", "128m")
CONTAINER_OUTPUT_LIMIT_MB = int(
    os.getenv("CODE_RUNNER_OUTPUT_LIMIT_MB", "64")
)
AUTO_BUILD_IMAGE = os.getenv("CODE_RUNNER_AUTO_BUILD", "1").lower() not in (
    "0",
    "false",
    "no",
)

_CREATE_TIMEOUT = 30
_CLI_TIMEOUT = 60
_BUILD_TIMEOUT = 600

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
# Docker sandbox runner
# ---------------------------------------------------------------------------

_CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class SandboxUnavailableError(RuntimeError):
    """Raised when the Docker sandbox cannot be used at all."""


# Lazily cached (thread-safe) sandbox readiness so the common path does not
# pay the docker CLI + image-inspect round trip on every execution.
_env_lock = threading.Lock()
_build_lock = threading.Lock()
_env_checked = False
_env_ready = False
_env_error = ""


def _run_cli(
    args: List[str], timeout: float = _CLI_TIMEOUT
) -> Tuple[int, str, str]:
    """Run a ``docker`` CLI command.  Returns ``(returncode, stdout, stderr)``."""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATE_FLAGS,
        )
        return proc.returncode, (proc.stdout or "").strip(), (
            proc.stderr or ""
        ).strip()
    except OSError as exc:
        return -1, "", str(exc)
    except subprocess.TimeoutExpired:
        return -1, "", f"docker command timed out after {timeout:g}s"


def _check_docker() -> None:
    if shutil.which("docker") is None:
        raise SandboxUnavailableError("docker CLI not found on PATH")
    rc, _, err = _run_cli(
        ["docker", "version", "--format", "{{.Server.Version}}"]
    )
    if rc != 0:
        raise SandboxUnavailableError(
            f"docker daemon unreachable: {(err or 'no output')[:200]}"
        )


def _ensure_image() -> None:
    rc, _, _ = _run_cli(["docker", "image", "inspect", DOCKER_IMAGE])
    if rc == 0:
        return
    if not AUTO_BUILD_IMAGE:
        raise SandboxUnavailableError(
            f"runner image {DOCKER_IMAGE!r} is not present"
        )
    if not (DOCKERFILE_DIR / "Dockerfile").is_file():
        raise SandboxUnavailableError(
            f"runner Dockerfile not found at {DOCKERFILE_DIR}"
        )
    rc, _, err = _run_cli(
        ["docker", "build", "-t", DOCKER_IMAGE, str(DOCKERFILE_DIR)],
        timeout=_BUILD_TIMEOUT,
    )
    if rc != 0:
        raise SandboxUnavailableError(
            f"could not build runner image {DOCKER_IMAGE!r}: "
            f"{(err or 'no output')[-300:]}"
        )


def _ensure_environment() -> None:
    """Verify the docker CLI/daemon and runner image are ready (once)."""
    global _env_checked, _env_ready, _env_error
    with _env_lock:
        if _env_checked:
            if _env_ready:
                return
            raise SandboxUnavailableError(_env_error or "sandbox unavailable")

    with _build_lock:
        with _env_lock:
            if _env_checked:
                if _env_ready:
                    return
                raise SandboxUnavailableError(_env_error or "sandbox unavailable")
        try:
            _check_docker()
            _ensure_image()
        except SandboxUnavailableError as exc:
            with _env_lock:
                _env_checked = True
                _env_ready = False
                _env_error = str(exc)
            raise
        with _env_lock:
            _env_checked = True
            _env_ready = True


def _set_dir_permissions(path: str, mode: int) -> None:
    """Best-effort open permissions so the container's non-root user can
    read/execute the workspace and write to the scratch dir, regardless of
    the host umask."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _clear_output_files(scratch_dir: str) -> None:
    for name in ("stdout.txt", "stderr.txt", "input.txt"):
        path = os.path.join(scratch_dir, name)
        try:
            os.remove(path)
        except OSError:
            pass


def _read_capped_file(path: str, max_bytes: int = MAX_OUTPUT_BYTES) -> str:
    """Read at most ``max_bytes + 1`` bytes from *path* and truncate."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(max_bytes + 1)
    except OSError:
        return ""
    return _truncate(data.decode("utf-8", errors="replace"), max_bytes)


def _docker_exec(
    command: str,
    workspace_dir: str,
    scratch_dir: str,
    memory_limit_mb: int,
    timeout: float,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[str, str, int, int, bool]:
    """Run *command* inside one disposable, hardened container.

    Returns ``(stdout, stderr, returncode, time_ms, timed_out)``. The
    container is always removed afterwards (``docker rm -f``), including on
    timeout and on setup failures.
    """
    _ensure_environment()
    name = f"recruito-{os.getpid()}-{uuid.uuid4().hex[:8]}"

    memory_limit_mb = max(32, int(memory_limit_mb))
    output_limit_bytes = CONTAINER_OUTPUT_LIMIT_MB * 1024 * 1024

    create_args: List[str] = [
        "docker",
        "create",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--user",
        f"{CONTAINER_USER}:{CONTAINER_USER}",
        "--memory",
        f"{memory_limit_mb}m",
        "--memory-swap",
        f"{memory_limit_mb}m",
        "--cpus",
        f"{CONTAINER_CPUS:g}",
        "--pids-limit",
        str(CONTAINER_MAX_PIDS),
        "--ulimit",
        f"fsize={output_limit_bytes}:{output_limit_bytes}",
        "--tmpfs",
        f"/tmp:rw,size={CONTAINER_TMPFS_SIZE},mode=1777",
        "-v",
        f"{workspace_dir}:/workspace:ro",
        "-v",
        f"{scratch_dir}:/scratch",
    ]
    for key, value in (env or {}).items():
        create_args.extend(["-e", f"{key}={value}"])
    create_args.extend([DOCKER_IMAGE, "sh", "-c", command])

    rc, _, err = _run_cli(create_args, timeout=_CREATE_TIMEOUT)
    if rc != 0:
        _run_cli(["docker", "rm", "-f", name], timeout=_CREATE_TIMEOUT)
        return "", (err or "failed to create sandbox container"), -1, 0, False

    start = time.monotonic()
    attach_out = b""
    attach_err = b""
    try:
        try:
            proc = subprocess.Popen(
                ["docker", "start", "-a", name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=_CREATE_FLAGS,
            )
            try:
                attach_out, attach_err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                _run_cli(["docker", "kill", name], timeout=_CREATE_TIMEOUT)
                elapsed = int((time.monotonic() - start) * 1000)
                return "", "Time limit exceeded", -1, elapsed, True
        except OSError as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            return "", str(exc), -1, elapsed, False
    finally:
        _run_cli(["docker", "rm", "-f", name], timeout=_CREATE_TIMEOUT)

    elapsed = int((time.monotonic() - start) * 1000)

    stdout = _read_capped_file(os.path.join(scratch_dir, "stdout.txt"))
    stderr = _read_capped_file(os.path.join(scratch_dir, "stderr.txt"))
    if not stdout and attach_out:
        stdout = _truncate(attach_out.decode("utf-8", errors="replace"))
    if not stderr and attach_err:
        stderr = _truncate(attach_err.decode("utf-8", errors="replace"))
    return stdout, stderr, proc.returncode, elapsed, False


def _run_container_case(
    command: str,
    input_text: str,
    workspace_dir: str,
    scratch_dir: str,
    memory_limit_mb: int,
    time_limit: float,
) -> Tuple[str, str, int, int, bool]:
    """Stage the test input, clear stale output, and run one test case."""
    _clear_output_files(scratch_dir)
    with open(
        os.path.join(scratch_dir, "input.txt"),
        "w",
        encoding="utf-8",
        newline="\n",
    ) as fh:
        fh.write(input_text)
    return _docker_exec(
        command, workspace_dir, scratch_dir, memory_limit_mb, time_limit
    )


# ---------------------------------------------------------------------------
# Language-specific compile / run (inside containers)
# ---------------------------------------------------------------------------


def _jvm_heap_mb(memory_limit_mb: int) -> int:
    return max(64, min(128, memory_limit_mb // 2))


def _compile_cpp(
    workspace_dir: str,
    scratch_dir: str,
    memory_limit_mb: int,
    timeout: float,
) -> Tuple[bool, str, int]:
    """Compile C++ in a container.  Returns ``(success, stderr, time_ms)``."""
    command = (
        "g++ -std=c++17 -O2 -o /scratch/solution /workspace/solution.cpp "
        "> /scratch/stdout.txt 2> /scratch/stderr.txt"
    )
    _clear_output_files(scratch_dir)
    stdout, stderr, rc, time_ms, _ = _docker_exec(
        command, workspace_dir, scratch_dir, memory_limit_mb, timeout
    )
    return rc == 0, _truncate(stderr), time_ms


def _compile_java(
    workspace_dir: str,
    scratch_dir: str,
    memory_limit_mb: int,
    timeout: float,
) -> Tuple[bool, str, int]:
    """Compile Java in a container.  Returns ``(success, stderr, time_ms)``."""
    heap = _jvm_heap_mb(memory_limit_mb)
    command = (
        f"javac -J-Xmx{heap}m -d /scratch/classes /workspace/Main.java "
        "> /scratch/stdout.txt 2> /scratch/stderr.txt"
    )
    _clear_output_files(scratch_dir)
    stdout, stderr, rc, time_ms, _ = _docker_exec(
        command, workspace_dir, scratch_dir, memory_limit_mb, timeout
    )
    return rc == 0, _truncate(stderr), time_ms


def _run_python(
    test_cases: List[Dict[str, Any]],
    workspace_dir: str,
    scratch_dir: str,
    memory_limit_mb: int,
    time_limit: float,
    result: ExecutionResult,
) -> None:
    command = (
        "python3 -u -B -I /workspace/solution.py "
        "< /scratch/input.txt > /scratch/stdout.txt 2> /scratch/stderr.txt"
    )
    for i, tc in enumerate(test_cases):
        stdout, stderr, rc, time_ms, timed_out = _run_container_case(
            command,
            tc.get("input", ""),
            workspace_dir,
            scratch_dir,
            memory_limit_mb,
            time_limit,
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
    command: str,
    test_cases: List[Dict[str, Any]],
    workspace_dir: str,
    scratch_dir: str,
    memory_limit_mb: int,
    time_limit: float,
    result: ExecutionResult,
) -> None:
    """Shared runner for Java / C++ after successful compilation."""
    for i, tc in enumerate(test_cases):
        stdout, stderr, rc, time_ms, timed_out = _run_container_case(
            command,
            tc.get("input", ""),
            workspace_dir,
            scratch_dir,
            memory_limit_mb,
            time_limit,
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


def _prepare_workdirs(node: str) -> Tuple[str, str]:
    workspace = os.path.join(node, "workspace")
    scratch = os.path.join(node, "scratch")
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(scratch, exist_ok=True)
    _set_dir_permissions(workspace, 0o755)
    _set_dir_permissions(scratch, 0o777)
    return workspace, scratch


def _write_source(workspace_dir: str, filename: str, code: str) -> str:
    path = os.path.join(workspace_dir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(code)
    return path


def _sandbox_failure_result(
    test_cases: List[Dict[str, Any]], reason: str
) -> ExecutionResult:
    result = ExecutionResult()
    result.error = reason
    result.test_results = [
        TestCaseResult(
            case_index=i,
            passed=False,
            status="runtime_error",
            stderr=f"Sandbox unavailable: {reason}",
        )
        for i in range(len(test_cases))
    ]
    return result


def execute_code(
    language: str,
    code: str,
    test_cases: List[Dict[str, Any]],
    time_limit: float = DEFAULT_TIME_LIMIT_SECONDS,
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
) -> ExecutionResult:
    """Execute candidate *code* in *language* against *test_cases* inside an
    isolated Docker sandbox.

    Each test-case dict must have ``"input"`` and ``"expected"`` string keys.
    Returns an ``ExecutionResult`` with per-case pass/fail details.
    """
    validate_code(code, language)
    result = ExecutionResult()

    if not test_cases:
        return result

    try:
        _ensure_environment()
    except SandboxUnavailableError as exc:
        return _sandbox_failure_result(test_cases, str(exc))

    with tempfile.TemporaryDirectory(prefix="recruito_code_") as tmp_base:
        workspace_dir, scratch_dir = _prepare_workdirs(tmp_base)

        # ------------------------------------------------------------------
        # Python
        # ------------------------------------------------------------------
        if language == "python":
            _write_source(workspace_dir, "solution.py", code)
            _run_python(
                test_cases,
                workspace_dir,
                scratch_dir,
                memory_limit_mb,
                time_limit,
                result,
            )

        # ------------------------------------------------------------------
        # Java
        # ------------------------------------------------------------------
        elif language == "java":
            _write_source(workspace_dir, "Main.java", code)
            compile_ok, compile_err, _ = _compile_java(
                workspace_dir, scratch_dir, memory_limit_mb, time_limit
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

            heap = _jvm_heap_mb(memory_limit_mb)
            command = (
                f"java -Xmx{heap}m -cp /scratch/classes Main "
                "< /scratch/input.txt > /scratch/stdout.txt 2> /scratch/stderr.txt"
            )
            _run_compiled(
                command,
                test_cases,
                workspace_dir,
                scratch_dir,
                memory_limit_mb,
                time_limit,
                result,
            )

        # ------------------------------------------------------------------
        # C++
        # ------------------------------------------------------------------
        elif language == "cpp":
            _write_source(workspace_dir, "solution.cpp", code)
            compile_ok, compile_err, _ = _compile_cpp(
                workspace_dir, scratch_dir, memory_limit_mb, time_limit
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
                "/scratch/solution"
                " < /scratch/input.txt > /scratch/stdout.txt 2> /scratch/stderr.txt",
                test_cases,
                workspace_dir,
                scratch_dir,
                memory_limit_mb,
                time_limit,
                result,
            )

    if result.test_results:
        result.total_time_ms = sum(r.time_ms for r in result.test_results)
    return result
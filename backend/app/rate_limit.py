# pyrefly: ignore [missing-import]
from fastapi import HTTPException, Request, status
import threading
import time
from collections import deque
from typing import Optional, Callable, Tuple


def _default_now() -> float:
    return time.monotonic()


class SlidingWindowRateLimiter:
    """Thread-safe, in-memory sliding-window rate limiter.

    - Never touches PostgreSQL: all state lives in process memory, so there is
      no DB schema, no migration, and zero added DB load.
    - Bounded: keys are pruned lazily on access and idle/empty buckets are
      swept periodically so memory can't grow without limit.
    - Same limiter instance serves all scopes; each caller passes the
      (max_events, window_seconds) relevant to that scope.
    """

    def __init__(
        self,
        now: Optional[Callable[[], float]] = None,
        sweep_interval_seconds: int = 60,
        max_window_seconds: int = 3600,
    ) -> None:
        self._now = now or _default_now
        self._sweep_interval = sweep_interval_seconds
        self._max_window = max_window_seconds
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = {}
        self._last_sweep = self._now()

    def check(
        self,
        key: str,
        max_events: int,
        window_seconds: int,
    ) -> Tuple[bool, int]:
        """Record one attempt for `key`.

        Returns (allowed, retry_after_seconds). When the limit is exceeded,
        retry_after is how long the caller must wait (whole seconds) before
        trying again — derived from when the oldest in-window event expires.
        When allowed, retry_after is 0.
        """
        now = self._now()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque()
                self._buckets[key] = bucket

            cutoff = now - window_seconds
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= max_events:
                retry_after = int(bucket[0] + window_seconds - now) + 1
                return False, max(1, retry_after)

            bucket.append(now)
            self._maybe_sweep(now)
            return True, 0

    def reset(self, key: Optional[str] = None) -> None:
        """Clear the whole limiter (key=None) or a single key.

        Used on successful account actions so a legitimate login never stays
        bottlenecked by earlier failures.
        """
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)

    def _maybe_sweep(self, now: float) -> None:
        if now - self._last_sweep < self._sweep_interval:
            return
        self._last_sweep = now
        idle_cutoff = now - self._max_window
        stale = [
            key
            for key, bucket in self._buckets.items()
            if not bucket or bucket[-1] < idle_cutoff
        ]
        for key in stale:
            self._buckets.pop(key, None)


_limiter = SlidingWindowRateLimiter()


def client_ip(request: Request) -> str:
    """Best-effort source IP for rate limiting.

    Uses the direct TCP peer (request.client). X-Forwarded-For is deliberately
    NOT trusted unless a trusted proxy is configured in front of the app.
    """
    return request.client.host if request.client else "unknown"


def check_rate_limit(
    key: str,
    max_events: int,
    window_seconds: int,
    detail: str = "Too many requests. Please try again later.",
) -> None:
    """Consume one slot for `key` and raise HTTP 429 with Retry-After when the
    sliding window is exhausted."""
    allowed, retry_after = _limiter.check(key, max_events, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )


def reset_rate_limit(key: Optional[str] = None) -> None:
    _limiter.reset(key)

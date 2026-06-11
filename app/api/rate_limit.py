"""Phase 17.6 (task #30) — in-memory rate limiting.

The three drawing-ingest routes added across
Phase 17 — ``/api/drawing/ingest``,
``/api/drawing/ingest-and-build``, and
``/api/drawing/ingest/{id}/commit`` — are bounded
by an in-process token-bucket rate limiter. There
is no Redis dependency. The limiter dies with the
process; the audit log at
``outputs/audit/audit_YYYYMMDD.jsonl`` is the
persistent record of 429s.

The bucket math (the standard token-bucket
algorithm):

1. On first call for a key, the bucket starts full
   (``tokens = capacity``).
2. On each call, refill: ``tokens = min(capacity,
   tokens + (now - last_refill_ts) *
   refill_per_sec)``.
3. If ``tokens >= 1.0``, decrement by 1 and allow.
4. Otherwise, compute ``retry_after = ceil((1.0 -
   tokens) / refill_per_sec)`` and deny.

The ``threading.Lock`` is held for the entire
check-and-decrement to make the read-modify-write
atomic. Lock hold time is microseconds; this is
fine at 30/min/IP x thousands of IPs.

The IP source is ``request.client.host`` by
default. The ``X-Forwarded-For`` header is honored
only when ``TRUST_FORWARDED_FOR=1`` is set in the
environment. Behind a trusted reverse proxy, set
the env var; exposed directly, leave it unset.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Tuple

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class BucketConfig:
    """A token-bucket configuration.

    ``capacity`` is the burst budget (a fresh
    bucket can serve ``capacity`` requests in a
    tight loop before the first 429). ``refill_per_sec``
    is the sustained budget (a single client can
    sustain ``capacity / 60`` requests per second
    indefinitely, given the standard ``refill_per_sec =
    capacity / 60`` convention used by the three
    drawing-ingest routes' bucket configs below).
    """

    capacity: int
    refill_per_sec: float


@dataclass
class _BucketState:
    tokens: float
    last_refill_ts: float


class RateLimiter:
    """In-process token-bucket registry.

    The registry is a flat dict keyed by
    ``"<bucket_name>:ip:<client_ip>"`` (or
    ``"<bucket_name>:key:<extra>"`` when the route
    needs a non-IP key, e.g. per-``machine_name``).
    One lock guards the whole dict; bucket math is
    per-key and lock-free at the call site once the
    lock is held.
    """

    def __init__(self) -> None:
        self._buckets: Dict[str, _BucketState] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Test-only: clear all buckets."""
        with self._lock:
            self._buckets.clear()

    def consume(
        self, key: str, cfg: BucketConfig,
    ) -> Tuple[bool, int, int]:
        """Try to consume one token from the bucket
        identified by ``key``.

        Returns ``(allowed, remaining_tokens,
        retry_after_seconds)``. When ``allowed`` is
        ``True``, ``retry_after_seconds`` is 0.
        When ``allowed`` is ``False``,
        ``retry_after_seconds`` is the integer
        number of seconds the caller should wait
        before the next token is available (always
        >= 1; a value of 0 is rounded up to 1 to
        match HTTP ``Retry-After`` semantics).
        """
        now = time.monotonic()
        with self._lock:
            state = self._buckets.get(key)
            if state is None:
                state = _BucketState(
                    tokens=float(cfg.capacity),
                    last_refill_ts=now,
                )
                self._buckets[key] = state
            else:
                elapsed = now - state.last_refill_ts
                if elapsed > 0:
                    state.tokens = min(
                        cfg.capacity,
                        state.tokens + elapsed * cfg.refill_per_sec,
                    )
                    state.last_refill_ts = now
            if state.tokens >= 1.0:
                state.tokens -= 1.0
                remaining = int(state.tokens)
                return True, remaining, 0
            deficit = 1.0 - state.tokens
            wait = deficit / cfg.refill_per_sec
            # Round up to the next whole second; HTTP
            # Retry-After is an integer count of
            # seconds. A 0.4s wait becomes 1s; a 0s
            # wait also becomes 1s so the client does
            # not retry-storm in a tight loop.
            retry_after = max(1, int(wait + 0.999))
            return False, 0, retry_after


# Module-level singleton. The test suite calls
# ``reset_rate_limiter()`` between tests via a
# function-scoped fixture.
_limiter: RateLimiter | None = None
_limiter_lock = threading.Lock()


def get_rate_limiter() -> RateLimiter:
    """Return the process-wide RateLimiter, creating
    it on first call. The pattern matches
    ``app.runtime.audit.get_audit_logger``."""
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                _limiter = RateLimiter()
    return _limiter


def reset_rate_limiter() -> None:
    """Drop the singleton so the next
    ``get_rate_limiter()`` call builds a fresh
    instance with an empty bucket dict. Test-only."""
    global _limiter
    _limiter = None


# Bucket configs for the three drawing-ingest
# routes. The refill rate is capacity / 60 seconds,
# so a fully-exhausted bucket refills to capacity
# in exactly one minute. The 17.6 recommended
# limits from the checklist:
#   /drawing/ingest            : 30/min
#   /drawing/ingest-and-build  :  5/min
#   /drawing/ingest/{id}/commit: 10/min
BUCKET_INGEST = BucketConfig(
    capacity=30, refill_per_sec=30.0 / 60.0,
)
BUCKET_INGEST_AND_BUILD = BucketConfig(
    capacity=5, refill_per_sec=5.0 / 60.0,
)
BUCKET_COMMIT = BucketConfig(
    capacity=10, refill_per_sec=10.0 / 60.0,
)


def _client_ip(request: Request) -> str:
    """Return the client's IP, optionally trusting
    ``X-Forwarded-For`` when ``TRUST_FORWARDED_FOR=1``
    is set in the environment.

    Default: use ``request.client.host`` (the
    immediate TCP peer). With ``TRUST_FORWARDED_FOR=1``,
    parse ``X-Forwarded-For`` and take the leftmost
    address. The env var gates XFF trust so an
    attacker can't spoof the source IP when the
    platform is exposed directly. Behind a trusted
    reverse proxy, the operator sets the env var.
    """
    if os.getenv("TRUST_FORWARDED_FOR", "").lower() in (
        "1", "true", "yes",
    ):
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    if request.client is None:
        return "unknown"
    return request.client.host


def _audit_429(
    bucket_name: str, ip: str, retry_after: int,
) -> None:
    """Write a single ``rate_limit_exceeded`` entry
    to the global audit log. The audit log is the
    persistent record of 429s; the in-memory
    bucket is ephemeral. The audit call is wrapped
    in a try/except so an audit-log failure cannot
    prevent the 429 from being returned to the
    client — the rate limit is the load-bearing
    security control, the audit is the forensic
    record."""
    try:
        from app.runtime.audit import get_audit_logger
        get_audit_logger().log_action(
            username="anonymous",
            action="rate_limit_exceeded",
            resource=bucket_name,
            detail=f"ip={ip},retry_after={retry_after}",
            ip_address=ip,
            success=False,
        )
    except Exception:
        # Never let an audit failure mask the 429.
        pass


def _rate_limit_enabled() -> bool:
    """Whether the rate limiter is active.

    Default: on. The platform's production
    contract is that the three drawing-ingest
    routes are rate-limited. Tests that share a
    module-scoped TestClient and don't need to
    exercise the limiter can set
    ``RATE_LIMIT_ENABLED=0`` in their
    environment (or via ``monkeypatch.setenv``)
    to make ``enforce_rate_limit`` a no-op.

    The check is at call time, not at module-
    load time, so tests can toggle the limiter
    on and off dynamically.
    """
    return os.getenv("RATE_LIMIT_ENABLED", "1").lower() not in (
        "0", "false", "no",
    )


def enforce_rate_limit(
    request: Request,
    bucket_name: str,
    cfg: BucketConfig,
) -> None:
    """Consume one token from the per-IP bucket for
    ``bucket_name``.

    On the happy path, returns ``None`` and stamps
    ``request.state.ratelimit_limit`` and
    ``request.state.ratelimit_remaining`` so the
    route can set ``X-RateLimit-*`` response headers
    via the ``Response`` parameter.

    On exhaustion, raises ``HTTPException(429)`` with
    ``Retry-After``, ``X-RateLimit-Limit``, and
    ``X-RateLimit-Remaining: 0`` headers. The 429
    is also recorded in the global audit log as
    ``action=rate_limit_exceeded``,
    ``success=false``, with the source IP and
    ``bucket_name`` resource.

    The function does **not** mutate the response
    directly. The route is responsible for the
    200-path header injection; the 429 path carries
    its headers via the ``HTTPException`` ``headers``
    kwarg.

    When ``RATE_LIMIT_ENABLED=0`` is set in the
    environment, this function still stamps
    ``request.state.ratelimit_limit`` and
    ``request.state.ratelimit_remaining`` (with the
    bucket's full capacity and 100% remaining) but
    does **not** consume a token and does **not**
    raise 429. This keeps the route's header
    injection code uniform: the response always
    carries the X-RateLimit-* headers. Tests use
    this backdoor to share a module-scoped
    TestClient without bleed between cases.
    """
    ip = _client_ip(request)
    if not _rate_limit_enabled():
        # No-op: stamp the state with the full
        # bucket so the route's header injection
        # code does not AttributeError, but do not
        # consume a token and do not raise 429.
        request.state.ratelimit_limit = cfg.capacity
        request.state.ratelimit_remaining = cfg.capacity
        return
    limiter = get_rate_limiter()
    key = f"{bucket_name}:ip:{ip}"
    allowed, remaining, retry_after = limiter.consume(key, cfg)
    request.state.ratelimit_limit = cfg.capacity
    request.state.ratelimit_remaining = remaining
    if not allowed:
        _audit_429(bucket_name, ip, retry_after)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limit_exceeded",
                "bucket": bucket_name,
                "retry_after_seconds": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(cfg.capacity),
                "X-RateLimit-Remaining": "0",
            },
        )

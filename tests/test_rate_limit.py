# tests/test_rate_limit.py
#
# Phase 17.6 (task #30) — in-memory token-bucket rate
# limiting on the three drawing-ingest routes. The
# per-IP limits are:
#
#   /api/drawing/ingest             : 30/min
#   /api/drawing/ingest-and-build   :  5/min
#   /api/drawing/ingest/{id}/commit : 10/min
#
# The tests in this file pin:
#
#   1. The 30/min burst on /drawing/ingest is honored
#      (30 succeed, 31st returns 429).
#   2. The 5/min limit on /drawing/ingest-and-build
#      (5 succeed, 6th returns 429).
#   3. The 10/min limit on /drawing/ingest/{id}/commit
#      (10 succeed, 11th returns 429).
#   4. Per-IP isolation: two distinct X-Forwarded-For
#      addresses have independent buckets.
#   5. The 429 response carries Retry-After,
#      X-RateLimit-Limit, and X-RateLimit-Remaining
#      headers.
#   6. The 200 response carries X-RateLimit-Limit and
#      X-RateLimit-Remaining.
#   7. The token-bucket refills over time.
#   8. Unrelated routes (e.g. /api/health) are not
#      rate-limited.
#   9. Every 429 is recorded in the global audit log
#      at outputs/audit/audit_<date>.jsonl.
#
# The test fixture resets the rate limiter and
# enables TRUST_FORWARDED_FOR=1 before every test,
# so the limiter keys on the X-Forwarded-For header
# rather than the test-client's host. This gives
# every test a clean bucket without having to flush
# the in-memory dict by IP.
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_limiter(monkeypatch, tmp_path):
    """Reset the rate limiter and trust X-Forwarded-For
    for every test in this module. The module-scoped
    TestClient shares the rate-limiter singleton; this
    fixture ensures no test bleeds state into the
    next. The tmp_path + chdir isolates the audit log
    to a per-test directory so the audit-on-429 test
    can assert on its own writes without seeing other
    tests' audit entries.

    The fixture also re-enables the rate limiter via
    ``RATE_LIMIT_ENABLED=1``, overriding the
    platform-wide default in ``tests/conftest.py``
    that disables the limiter for tests that don't
    exercise it."""
    from app.api.rate_limit import reset_rate_limiter
    from app.runtime.audit import reset_audit_logger
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    reset_rate_limiter()
    reset_audit_logger()
    monkeypatch.chdir(tmp_path)
    yield
    reset_rate_limiter()
    reset_audit_logger()


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post_ingest(client, xff: str):
    """Send a single POST /api/drawing/ingest with
    the given X-Forwarded-For header. The body is a
    1-byte placeholder; the test is not asserting
    on ingestion success, only on rate-limit
    behavior. The 415 / 200 / 429 distinction is
    the load-bearing assertion."""
    return client.post(
        "/api/drawing/ingest",
        headers={"X-Forwarded-For": xff},
        files={"file": (
            "x.pdf", io.BytesIO(b"%PDF-1.4\n"),
            "application/pdf",
        )},
    )


def _post_ingest_and_build(client, xff: str):
    """Send a single POST /api/drawing/ingest-and-build
    with the given X-Forwarded-For header. The
    commit=false default keeps the route short-
    circuiting at Gate 1 (no orchestrator call),
    which is the cheapest path to exercise the
    rate limiter without mocking the orchestrator.
    The XFF header is the only key the test cares
    about."""
    return client.post(
        "/api/drawing/ingest-and-build",
        headers={"X-Forwarded-For": xff},
        files={"file": (
            "x.pdf", io.BytesIO(b"%PDF-1.4\n"),
            "application/pdf",
        )},
    )


def _post_commit(client, xff: str, ingestion_id: str = "ing_x"):
    """Send a single POST /api/drawing/ingest/{id}/commit
    with the given X-Forwarded-For header. The route
    returns 404 for an unknown ingestion_id, but the
    rate limit fires BEFORE the 404, so the test can
    use any string for the path parameter. The 404
    is not a 429; the test asserts that 30 calls in
    a tight loop do not 429."""
    return client.post(
        f"/api/drawing/ingest/{ingestion_id}/commit",
        headers={"X-Forwarded-For": xff},
        json={"actor": "test", "reason": "rate limit smoke"},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIngestRouteRateLimit:
    """The /api/drawing/ingest route enforces 30
    requests/minute per IP. The 31st request from
    the same IP returns 429."""

    def test_ingest_within_budget_succeeds(self, client):
        """30 calls in a tight loop from the same IP
        all return non-429. The bodies may be 200 or
        415 (the test fixture is a minimal PDF that
        may or may not parse), but the rate limit
        must not fire on any of them."""
        xff = "10.0.0.1"
        for i in range(30):
            r = _post_ingest(client, xff)
            assert r.status_code != 429, (
                f"Rate limit fired on call {i+1}/30 "
                f"with status {r.status_code}: {r.text[:200]}"
            )

    def test_ingest_blocks_at_31st_call(self, client):
        """30 calls succeed, the 31st returns 429 with
        the standard rate-limit headers."""
        xff = "10.0.0.2"
        for i in range(30):
            r = _post_ingest(client, xff)
            assert r.status_code != 429
        r31 = _post_ingest(client, xff)
        assert r31.status_code == 429
        # The 429 detail.
        body = r31.json()
        assert body["detail"]["error"] == "rate_limit_exceeded"
        assert body["detail"]["bucket"] == "ingest"
        assert body["detail"]["retry_after_seconds"] >= 1
        # The standard headers.
        assert r31.headers["Retry-After"] == str(
            body["detail"]["retry_after_seconds"]
        )
        assert r31.headers["X-RateLimit-Limit"] == "30"
        assert r31.headers["X-RateLimit-Remaining"] == "0"


class TestIngestAndBuildRouteRateLimit:
    """The /api/drawing/ingest-and-build route enforces
    5 requests/minute per IP. The 6th request from
    the same IP returns 429. The limit is tighter
    than /drawing/ingest because the orchestrator
    call is expensive (SCAD -> STL -> PNG -> BOM
    -> Evaluation)."""

    def test_ingest_and_build_blocks_at_6th_call(self, client):
        xff = "10.0.0.3"
        for i in range(5):
            r = _post_ingest_and_build(client, xff)
            assert r.status_code != 429, (
                f"Rate limit fired on call {i+1}/5 with "
                f"status {r.status_code}: {r.text[:200]}"
            )
        r6 = _post_ingest_and_build(client, xff)
        assert r6.status_code == 429
        body = r6.json()
        assert body["detail"]["bucket"] == "ingest_and_build"
        assert r6.headers["X-RateLimit-Limit"] == "5"
        assert r6.headers["X-RateLimit-Remaining"] == "0"


class TestCommitRouteRateLimit:
    """The /api/drawing/ingest/{id}/commit route
    enforces 10 requests/minute per IP. The 11th
    request from the same IP returns 429. The
    1-per-ingestion_id invariant is enforced at the
    storage layer; the rate limiter is a
    front-line defense."""

    def test_commit_blocks_at_11th_call(self, client):
        xff = "10.0.0.4"
        for i in range(10):
            r = _post_commit(client, xff)
            assert r.status_code != 429, (
                f"Rate limit fired on call {i+1}/10 with "
                f"status {r.status_code}: {r.text[:200]}"
            )
        r11 = _post_commit(client, xff)
        assert r11.status_code == 429
        body = r11.json()
        assert body["detail"]["bucket"] == "commit"
        assert r11.headers["X-RateLimit-Limit"] == "10"
        assert r11.headers["X-RateLimit-Remaining"] == "0"


class TestPerIPIsolation:
    """Two distinct X-Forwarded-For addresses have
    independent buckets. A burst from IP A that
    exhausts A's bucket does not affect IP B."""

    def test_two_ips_have_independent_buckets(self, client):
        # Exhaust IP A.
        xff_a = "10.0.0.10"
        for _ in range(30):
            _post_ingest(client, xff_a)
        r_blocked = _post_ingest(client, xff_a)
        assert r_blocked.status_code == 429
        # IP B is untouched; 30 calls all succeed.
        xff_b = "10.0.0.11"
        for i in range(30):
            r = _post_ingest(client, xff_b)
            assert r.status_code != 429, (
                f"IP B call {i+1} was rate-limited even "
                f"though IP B is independent of IP A"
            )


class TestRateLimitHeaders:
    """Every response (200, 415, 429, etc.) from a
    rate-limited route carries the X-RateLimit-Limit
    and X-RateLimit-Remaining headers. A 429 also
    carries Retry-After."""

    def test_200_includes_ratelimit_headers(self, client):
        """A successful (or 415) call from a fresh
        IP shows the limit and the full budget of
        remaining tokens."""
        r = _post_ingest(client, "10.0.0.20")
        assert r.headers["X-RateLimit-Limit"] == "30"
        assert int(r.headers["X-RateLimit-Remaining"]) >= 0
        # The remaining count should be 29 after the
        # first call (one consumed from a 30-token
        # bucket).
        assert int(r.headers["X-RateLimit-Remaining"]) == 29

    def test_remaining_decreases_with_each_call(self, client):
        """Three calls in a row from the same IP
        show 29, 28, 27 remaining. The decrement
        is monotonic; the bucket does not refill
        within a single test (refill rate is
        0.5 tokens/sec)."""
        xff = "10.0.0.21"
        expected = [29, 28, 27]
        for want in expected:
            r = _post_ingest(client, xff)
            assert int(r.headers["X-RateLimit-Remaining"]) == want


class TestTokenBucketRefill:
    """The token bucket refills over time at the
    configured refill rate. A bucket that is empty
    refills one token per (1 / refill_per_sec)
    seconds. With the production config
    (capacity=30, refill=0.5/s), a fresh bucket
    regenerates fully in 60 seconds. This test
    uses a small custom config to keep the test
    fast: capacity=2, refill=2/sec, so the bucket
    refills in 1 second."""

    def test_bucket_refills_over_time(
        self, client, monkeypatch,
    ):
        """Override BUCKET_INGEST to a fast-refilling
        config, exhaust the bucket, wait 1.5s, the
        next call succeeds. The route's import of
        ``BUCKET_INGEST`` is inside the function body
        (a lazy local import), so monkeypatching
        ``app.api.rate_limit.BUCKET_INGEST`` is
        sufficient — the route re-binds on every call."""
        from app.api import rate_limit
        # Custom config: capacity=2, refill=2/sec.
        # Two calls exhaust; one second later,
        # 2 tokens are available again.
        fast_cfg = rate_limit.BucketConfig(
            capacity=2, refill_per_sec=2.0,
        )
        monkeypatch.setattr(rate_limit, "BUCKET_INGEST", fast_cfg)
        xff = "10.0.0.30"
        # Two calls exhaust.
        r1 = _post_ingest(client, xff)
        r2 = _post_ingest(client, xff)
        assert r1.status_code != 429
        assert r2.status_code != 429
        # Third call fires the 429.
        r3 = _post_ingest(client, xff)
        assert r3.status_code == 429
        # Wait 1.5s for the bucket to refill.
        import time
        time.sleep(1.5)
        # Next call succeeds.
        r4 = _post_ingest(client, xff)
        assert r4.status_code != 429, (
            f"Bucket did not refill after 1.5s; "
            f"got status {r4.status_code}: {r4.text[:200]}"
        )


class TestUnrelatedRoutesNotRateLimited:
    """Routes outside the drawing-ingest surface
    (e.g. /api/health) are not rate-limited. The
    rate limiter is scoped to the three Phase 17
    drawing routes."""

    def test_health_endpoint_not_rate_limited(self, client):
        # Send 100 calls to /api/health. None should
        # 429. (The route is GET, not POST, so the
        # rate limiter's bucket registry is not
        # touched.)
        for i in range(100):
            r = client.get(
                "/api/health",
                headers={"X-Forwarded-For": "10.0.0.40"},
            )
            assert r.status_code != 429, (
                f"/api/health was rate-limited on call {i+1}"
            )
            assert r.status_code == 200


class TestAuditLogOn429:
    """Every 429 is recorded in the global audit
    log at outputs/audit/audit_<date>.jsonl. The
    audit log is the persistent forensic record;
    the in-memory bucket is ephemeral."""

    def test_429_writes_audit_log_entry(self, client, tmp_path):
        """Trigger a 429, then read the audit log
        file and assert the entry shape. The
        audit logger was reset by the autouse
        fixture, so the file lives under
        tmp_path/outputs/audit/."""
        from app.api.rate_limit import reset_rate_limiter
        from app.runtime.audit import reset_audit_logger
        # Re-reset to be safe.
        reset_rate_limiter()
        reset_audit_logger()
        xff = "10.0.0.50"
        # Exhaust the bucket.
        for _ in range(30):
            _post_ingest(client, xff)
        # The 31st call triggers the 429 + audit.
        r = _post_ingest(client, xff)
        assert r.status_code == 429
        # Read the audit log file. The
        # ``_isolated_limiter`` fixture chdir's to
        # tmp_path, so the audit log lives at
        # tmp_path/outputs/audit/audit_<date>.jsonl.
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        audit_path = (
            Path("outputs") / "audit" / f"audit_{today}.jsonl"
        )
        assert audit_path.exists(), (
            f"Audit log file not found at {audit_path}"
        )
        lines = [
            l for l in audit_path.read_text(
                encoding="utf-8"
            ).splitlines() if l
        ]
        assert len(lines) >= 1, (
            f"Expected at least one audit entry; got {len(lines)}"
        )
        # Find the rate_limit_exceeded entry.
        rl_entries = [
            json.loads(l) for l in lines
            if json.loads(l).get("action") == "rate_limit_exceeded"
        ]
        assert len(rl_entries) >= 1, (
            f"No rate_limit_exceeded entry in audit log: "
            f"{lines[:3]}"
        )
        entry = rl_entries[-1]  # most recent
        assert entry["action"] == "rate_limit_exceeded"
        assert entry["success"] is False
        assert entry["resource"] == "ingest"
        assert entry["ip_address"] == xff
        # The detail carries the retry_after hint.
        assert "retry_after" in entry["detail"]

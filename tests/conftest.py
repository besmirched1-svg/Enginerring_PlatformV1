"""Platform-wide pytest configuration.

The Phase 17.6 (task #30) rate limiter is on by
default in production. Tests that don't exercise
the limiter set ``RATE_LIMIT_ENABLED=0`` so the
in-memory bucket does not interfere with cases
that share a module-scoped TestClient and route
through ``request.client.host == "testclient"``,
which would otherwise be a single shared bucket.

The rate-limit test file
(``tests/test_rate_limit.py``) sets the env var
to ``"1"`` in its own autouse fixture, so the
limiter is active for the dedicated suite and
inert for everything else.

The fixture uses ``monkeypatch.setenv`` (not
``os.environ``) so the override is per-test and
the env var is restored after the test.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_rate_limiter_by_default(monkeypatch):
    """Disable the Phase 17.6 rate limiter for
    every test in the suite, unless the test file
    overrides this fixture (e.g.
    ``tests/test_rate_limit.py``). The override
    pattern is to set the env var to ``"1"`` in
    a fixture with the same name in the
    dedicated test module — pytest's fixture
    resolution picks the closest one."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "0")
    yield

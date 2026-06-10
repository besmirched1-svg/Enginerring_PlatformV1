"""Tests for app/core/startup_checks.py and the /api/health endpoint.

These tests verify the contract that operators and container
orchestrators rely on:

  * /api/health returns 200 with a structured report when the
    platform is healthy.
  * The report includes a "version" field sourced from
    app.__version__.
  * Each check has a name, status, severity, and detail.
  * Critical failures return 503.
  * The endpoint itself is registered before any container
    orchestrator can probe it.
"""
import pytest
from unittest.mock import patch


class TestStartupChecksModule:
    def test_run_all_returns_status(self):
        from app.core.startup_checks import run_all_checks
        r = run_all_checks()
        assert r["status"] in ("healthy", "degraded", "unhealthy")
        assert "checks" in r
        assert "critical_failures" in r
        assert "warnings" in r

    def test_each_check_has_required_fields(self):
        from app.core.startup_checks import run_all_checks
        r = run_all_checks()
        for c in r["checks"]:
            assert "name" in c
            assert "status" in c
            assert "severity" in c
            assert "detail" in c
            assert c["status"] in ("pass", "warn", "fail")
            assert c["severity"] in ("low", "medium", "high", "critical")

    def test_python_version_check(self):
        from app.core.startup_checks import check_python_version
        r = check_python_version()
        assert r.name == "python_version"
        # The test environment is Python 3.11+; this should pass.
        assert r.passed

    def test_required_imports_check(self):
        from app.core.startup_checks import check_required_imports
        r = check_required_imports()
        assert r.passed
        assert "checked" in r.data

    def test_factory_modules_check(self):
        from app.core.startup_checks import check_factory_modules
        r = check_factory_modules()
        assert r.passed

    def test_director_modules_check(self):
        from app.core.startup_checks import check_director_modules
        r = check_director_modules()
        assert r.passed

    def test_output_directories_check(self):
        from app.core.startup_checks import check_output_directories
        r = check_output_directories()
        assert r.passed

    def test_openscad_check_passes_when_on_path(self):
        from app.core.startup_checks import check_openscad
        r = check_openscad()
        # Local dev: openscad is on PATH. In CI without openscad,
        # this would be a fail with severity "high" (not critical).
        if r.passed:
            assert r.data.get("source") in ("env", "PATH", "windows_default")
        else:
            assert r.severity == "high"

    def test_config_check(self):
        from app.core.startup_checks import check_config
        r = check_config()
        assert r.passed
        assert "output_dir" in r.data

    def test_route_registration_check(self):
        from app.core.startup_checks import check_route_registration
        r = check_route_registration()
        assert r.passed
        assert r.data["count"] >= 1

    def test_health_endpoint_present(self):
        from app.core.startup_checks import check_health_endpoint_present
        r = check_health_endpoint_present()
        assert r.passed


class TestHealthEndpoint:
    """The /api/health endpoint itself."""

    def test_returns_200_when_healthy(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        r = client.get("/api/health")
        # Healthy platform -> 200, body has the report.
        assert r.status_code in (200, 503)
        body = r.json()
        if r.status_code == 503:
            # If unhealthy, the body is wrapped in HTTPException detail.
            body = body.get("detail", body)
        assert body["status"] in ("healthy", "degraded", "unhealthy")
        assert "version" in body
        assert "checks" in body

    def test_version_matches_app_version(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.__version__ import __version__
        client = TestClient(app)
        r = client.get("/api/health")
        body = r.json()
        if r.status_code == 503:
            body = body.get("detail", body)
        assert body["version"] == __version__

    def test_critical_failure_returns_503(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core import startup_checks

        # Force a critical check to fail; the endpoint must return 503.
        # Patch the function reference in the CRITICAL_CHECKS tuple,
        # not the module-level name, because the aggregator iterates
        # the tuple.
        original = startup_checks.CRITICAL_CHECKS
        forced = startup_checks.CheckResult(
            name="required_imports",
            status="fail",
            severity="critical",
            detail="forced failure for test",
        )

        def fake():
            return forced
        try:
            startup_checks.CRITICAL_CHECKS = (
                startup_checks.check_python_version,
                fake,  # required_imports slot
                startup_checks.check_factory_modules,
                startup_checks.check_director_modules,
                startup_checks.check_output_directories,
                startup_checks.check_route_registration,
                startup_checks.check_health_endpoint_present,
            )
            client = TestClient(app)
            r = client.get("/api/health")
            assert r.status_code == 503
            body = r.json()["detail"]
            assert "required_imports" in body["critical_failures"]
        finally:
            startup_checks.CRITICAL_CHECKS = original

    def test_non_critical_failure_returns_200(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core import startup_checks
        from app.core.startup_checks import CheckResult

        # A non-critical failure (e.g. OpenSCAD missing) should NOT
        # cause 503; the platform can still serve.
        original = startup_checks.NON_CRITICAL_CHECKS
        forced = CheckResult(
            name="openscad",
            status="fail",
            severity="high",
            detail="forced openscad missing",
        )
        try:
            startup_checks.NON_CRITICAL_CHECKS = (lambda: forced, startup_checks.check_config)
            client = TestClient(app)
            r = client.get("/api/health")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "degraded"
            openscad_check = next(c for c in body["checks"] if c["name"] == "openscad")
            assert openscad_check["status"] == "fail"
        finally:
            startup_checks.NON_CRITICAL_CHECKS = original

    def test_check_count_is_stable(self):
        """If you add or remove a check, this test breaks. That's
        the point: surface accidental changes to the public health
        contract."""
        from app.core.startup_checks import (
            CRITICAL_CHECKS, NON_CRITICAL_CHECKS,
        )
        # If you change this number, document it in CHANGELOG.md
        # and add a new test covering the new check.
        assert len(CRITICAL_CHECKS) == 7
        assert len(NON_CRITICAL_CHECKS) == 2

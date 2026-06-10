"""Platform startup checks (Phase 16.7).

Single source of truth for "is the platform ready to serve?".

This module is consumed by the ``/api/health`` endpoint and (in
production) by container health probes. Each check is a small
function returning a :class:`CheckResult`; the aggregator runs them
in order and short-circuits on the first failure inside any
critical group so the operator sees the most actionable signal.

Design notes
------------

* Checks are **non-destructive**. A failing check must never mutate
  state. The platform may run in degraded mode and the operator
  can still use the API to inspect what is wrong.
* Each check is **independent and self-contained**. Adding a new
  check should not require touching the others. New checks belong
  in their own function with a docstring explaining what they
  verify and why it matters.
* The result is **serializable**. ``/api/health`` returns it as
  JSON; logs and dashboards can consume the same shape.
* Severity bands match the rest of the platform (low / medium /
  high / critical). A "critical" failure is one that makes the
  platform un-servable; a "low" failure is a non-blocking warning.
"""
from __future__ import annotations

import importlib
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("engine.core.startup_checks")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """The outcome of a single startup check.

    Attributes
    ----------
    name:
        Stable identifier; becomes a JSON key in /api/health.
    status:
        "pass", "warn", or "fail".
    severity:
        "low" / "medium" / "high" / "critical". A "fail" with
        severity "critical" makes the whole platform unhealthy.
    detail:
        Human-readable explanation of the result. Should be
        short enough to fit in a log line.
    data:
        Optional machine-readable payload. For example, the
        OpenSCAD check returns the resolved binary path.
    """

    name: str
    status: str
    severity: str = "low"
    detail: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_python_version() -> CheckResult:
    """Verify the Python runtime meets the platform's minimum.

    The platform is tested on Python 3.11. Earlier versions may
    work (3.10+ is the practical floor) but the test matrix does
    not cover them; this check warns rather than fails.
    """
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 11):
        return CheckResult(
            name="python_version",
            status="pass",
            detail=f"Python {major}.{minor}",
            data={"version": f"{major}.{minor}"},
        )
    if (major, minor) >= (3, 10):
        return CheckResult(
            name="python_version",
            status="warn",
            severity="medium",
            detail=f"Python {major}.{minor} is below tested 3.11",
            data={"version": f"{major}.{minor}"},
        )
    return CheckResult(
        name="python_version",
        status="fail",
        severity="critical",
        detail=f"Python {major}.{minor} is unsupported (need >=3.10)",
        data={"version": f"{major}.{minor}"},
    )


def check_required_imports() -> CheckResult:
    """Verify every import the platform needs at boot is available.

    Catches missing optional dependencies (e.g. numpy, jinja2) and
    typos in module names before a runtime call does. A failure
    here is a build / install problem, not a configuration one.
    """
    required = [
        "fastapi", "uvicorn", "pydantic", "redis", "yaml",
        "jinja2", "watchdog", "requests", "numpy",
    ]
    missing: List[str] = []
    for name in required:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    if not missing:
        return CheckResult(
            name="required_imports",
            status="pass",
            detail=f"all {len(required)} required modules importable",
            data={"checked": required},
        )
    return CheckResult(
        name="required_imports",
        status="fail",
        severity="critical",
        detail=f"missing modules: {', '.join(missing)}",
        data={"missing": missing},
    )


def check_factory_modules() -> CheckResult:
    """Verify the factory layer packages import cleanly.

    The factory layer (16.1) is the heart of the platform. If any
    factory module fails to import, the build pipeline cannot run.
    """
    modules = [
        "app.factory",
        "app.factory.validation",
        "app.factory.predictive_maintenance",
        "app.factory.mass_balance",
        "app.factory.energy_balance",
        "app.factory.bottleneck",
        "app.factory.layout",
    ]
    failed: Dict[str, str] = {}
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            failed[name] = f"{type(exc).__name__}: {exc}"
    if not failed:
        return CheckResult(
            name="factory_modules",
            status="pass",
            detail=f"all {len(modules)} factory modules importable",
        )
    return CheckResult(
        name="factory_modules",
        status="fail",
        severity="critical",
        detail=f"{len(failed)} factory module(s) failed to import",
        data={"failed": failed},
    )


def check_director_modules() -> CheckResult:
    """Verify the per-machine director and the factory director load.

    Both director layers are part of the v1.0 surface. A failure
    in either blocks the closed loop.
    """
    modules = [
        "app.director",
        "app.director.engineer",
        "app.director.models",
        "app.factory_director",
        "app.factory_director.director",
        "app.factory_director.planner",
    ]
    failed: Dict[str, str] = {}
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            failed[name] = f"{type(exc).__name__}: {exc}"
    if not failed:
        return CheckResult(
            name="director_modules",
            status="pass",
            detail=f"all {len(modules)} director modules importable",
        )
    return CheckResult(
        name="director_modules",
        status="fail",
        severity="critical",
        detail=f"{len(failed)} director module(s) failed to import",
        data={"failed": failed},
    )


def check_openscad() -> CheckResult:
    """Verify OpenSCAD is resolvable on the host.

    The renderer's resolver priority is OPENSCAD_BIN env var ->
    PATH -> Windows default. The check honors the same priority.
    """
    env_path = os.getenv("OPENSCAD_BIN")
    if env_path and Path(env_path).exists():
        return CheckResult(
            name="openscad",
            status="pass",
            detail=f"OPENSCAD_BIN={env_path}",
            data={"path": env_path, "source": "env"},
        )
    on_path = shutil.which("openscad")
    if on_path:
        return CheckResult(
            name="openscad",
            status="pass",
            detail=f"openscad on PATH at {on_path}",
            data={"path": on_path, "source": "PATH"},
        )
    if sys.platform.startswith("win"):
        default = r"C:\Program Files\OpenSCAD\openscad.exe"
        if Path(default).exists():
            return CheckResult(
                name="openscad",
                status="pass",
                detail=f"Windows default at {default}",
                data={"path": default, "source": "windows_default"},
            )
    return CheckResult(
        name="openscad",
        status="fail",
        severity="high",
        detail=(
            "OpenSCAD binary not found. Set OPENSCAD_BIN env var, "
            "add 'openscad' to PATH, or install to the Windows default."
        ),
    )


def check_output_directories() -> CheckResult:
    """Verify the output tree exists and is writable.

    The platform writes to outputs/{scad,stl,bom,png,logs,revisions}/
    (lowercase, locked in Phase 16.5). A missing or read-only
    directory blocks every build.
    """
    from app.core.paths import ALL_DIRS, BASE_OUTPUT

    missing: List[str] = []
    not_writable: List[str] = []
    for d in ALL_DIRS:
        if not d.exists():
            missing.append(str(d))
            continue
        # Writability probe: try creating + removing a sentinel file.
        try:
            probe = d / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except Exception:
            not_writable.append(str(d))
    if not missing and not not_writable:
        return CheckResult(
            name="output_directories",
            status="pass",
            detail=f"all {len(ALL_DIRS)} output dirs exist and writable",
            data={"base": str(BASE_OUTPUT), "count": len(ALL_DIRS)},
        )
    return CheckResult(
        name="output_directories",
        status="fail",
        severity="critical",
        detail=(
            f"missing: {missing or '[]'}; not writable: {not_writable or '[]'}"
        ),
        data={"missing": missing, "not_writable": not_writable},
    )


def check_config() -> CheckResult:
    """Verify required configuration is set.

    The platform has very little required configuration: an output
    directory (defaulted to ./outputs) and an optional Redis URL.
    Missing the Redis URL is a warning, not a failure, because the
    platform degrades gracefully to NullEventBus.
    """
    from app.core.paths import BASE_OUTPUT

    redis_url = os.getenv("REDIS_URL") or os.getenv("ENGINEERING_REDIS_HOST")
    has_redis = bool(redis_url)

    return CheckResult(
        name="config",
        status="pass",
        detail=(
            f"output_dir={BASE_OUTPUT}; "
            f"redis={'configured' if has_redis else 'not configured (NullEventBus fallback)'}"
        ),
        data={"output_dir": str(BASE_OUTPUT), "redis": has_redis},
    )


def check_route_registration() -> CheckResult:
    """Verify the FastAPI app has registered its routes.

    This is the last check because it depends on the FastAPI app
    being importable. A failure here typically means a route
    decorator hit a syntax error.
    """
    try:
        from app.main import app
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="route_registration",
            status="fail",
            severity="critical",
            detail=f"app.main import failed: {type(exc).__name__}: {exc}",
        )
    routes = [r for r in app.routes if hasattr(r, "path")]
    if not routes:
        return CheckResult(
            name="route_registration",
            status="fail",
            severity="critical",
            detail="FastAPI app has zero routes registered",
        )
    return CheckResult(
        name="route_registration",
        status="pass",
        detail=f"{len(routes)} routes registered",
        data={"count": len(routes)},
    )


def check_health_endpoint_present() -> CheckResult:
    """Verify the /api/health route itself is registered.

    This check exists so the health endpoint can be a victim of
    its own audit. If it ever disappears, this check fires
    first, before the operator calls /api/health and gets a
    mysterious 404.
    """
    try:
        from app.main import app
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="health_endpoint",
            status="fail",
            severity="high",
            detail=f"app.main import failed: {exc}",
        )
    health_paths = {"/api/health", "/health", "/healthz"}
    registered = {r.path for r in app.routes if hasattr(r, "path")}
    present = health_paths & registered
    if present:
        return CheckResult(
            name="health_endpoint",
            status="pass",
            detail=f"health endpoint registered at {sorted(present)}",
        )
    return CheckResult(
        name="health_endpoint",
        status="fail",
        severity="high",
        detail=(
            f"none of {sorted(health_paths)} are registered; "
            "operators will get 404 on health probes"
        ),
    )


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


# Critical checks. A failure in any of these makes the platform
# un-servable; the aggregator returns ``unhealthy``.
CRITICAL_CHECKS = (
    check_python_version,
    check_required_imports,
    check_factory_modules,
    check_director_modules,
    check_output_directories,
    check_route_registration,
    check_health_endpoint_present,
)

# Non-critical checks. A failure here is a warning; the platform
# can still serve (e.g. OpenSCAD missing means STL renders will
# fall back to placeholders, but the API itself works).
NON_CRITICAL_CHECKS = (
    check_openscad,
    check_config,
)


def run_all_checks() -> Dict[str, Any]:
    """Run every check and return a structured report.

    Returns
    -------
    dict
        {
            "status": "healthy" | "degraded" | "unhealthy",
            "checks": [CheckResult.to_dict(), ...],
            "critical_failures": [name, ...],
            "warnings": [name, ...],
        }
    """
    results: List[CheckResult] = []
    for fn in (*CRITICAL_CHECKS, *NON_CRITICAL_CHECKS):
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001
            # A check that raises is treated as a critical failure of
            # itself; we surface the exception in the detail so the
            # operator can investigate.
            logger.exception("Startup check %s raised", fn.__name__)
            results.append(CheckResult(
                name=fn.__name__.replace("check_", ""),
                status="fail",
                severity="high",
                detail=f"check raised: {type(exc).__name__}: {exc}",
            ))

    critical_failures = [
        r.name for r in results
        if r.status == "fail" and r.severity == "critical"
    ]
    non_critical_failures = [
        r.name for r in results
        if r.status == "fail" and r.severity != "critical"
    ]
    warnings = [r.name for r in results if r.status == "warn"]

    if critical_failures:
        status = "unhealthy"
    elif non_critical_failures or warnings:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "checks": [r.to_dict() for r in results],
        "critical_failures": critical_failures,
        "warnings": warnings,
    }


def is_healthy() -> bool:
    """One-shot helper: True if no critical check failed."""
    return run_all_checks()["status"] != "unhealthy"


__all__ = [
    "CheckResult",
    "run_all_checks",
    "is_healthy",
    "CRITICAL_CHECKS",
    "NON_CRITICAL_CHECKS",
]

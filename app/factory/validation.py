"""Input validation for the factory analyzers.

Phase 16.1 brought the factory layer up to the same defensive standards as
``app/manufacturing/`` and ``app/physics/``:

  * out-of-range inputs are clamped and produce a warning rather than
    silently propagating NaN / negative values into the optimization
    pipeline;
  * the returned warnings list is the same shape that
    ``manufacturing.cutlists`` uses so callers can pattern-match across
    layers;
  * the validator is a *helper* (not a wrapper). Analyzers still own their
    domain; this module only normalizes inputs and surfaces problems.

The pattern intentionally mirrors ``app/manufacturing/cutlists.py``: a
dict of bounds, a function that returns a (clamped_value, warnings_list)
pair, and module-level helpers for the common cases.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Engineering bounds
# ---------------------------------------------------------------------------
# These are the same kind of "soft bounds" the manufacturing and physics
# layers use: they document the engineering envelope and catch obvious
# mistakes (negative mass flow, NaN, unit confusion), but they are not
# safety-critical limits. Callers that need stricter limits pass them
# explicitly through their own analyzer.

FACTORY_INPUT_BOUNDS: Dict[str, Tuple[float, float]] = {
    "feed_rate_kg_hr": (0.0, 1.0e8),
    "throughput_kg_hr": (0.0, 1.0e8),
    "target_rate_kg_hr": (1.0, 1.0e8),  # 0 makes the whole line undefined
    "tolerance": (1.0e-9, 1.0),
    "max_iterations": (1, 10000),
    "population_size": (1, 10000),
    "generations": (0, 10000),
    "mutation_rate": (0.0, 1.0),
    "crossover_rate": (0.0, 1.0),
    "spacing_m": (0.0, 100.0),
    "efficiency": (0.0, 1.0),
    "max_capacity_kg_hr": (0.0, 1.0e8),
    "footprint_m2": (0.0, 1.0e5),
    "tournament_size": (2, 100),
}


def _is_finite_number(value: Any) -> bool:
    """True if value is a real, finite number (not bool, not NaN, not None)."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def clamp_factory_input(
    name: str,
    value: Any,
    *,
    default: Optional[float] = None,
    warnings: Optional[List[str]] = None,
) -> float:
    """Clamp a single factory input to its declared bounds.

    Returns a finite float, falling back to ``default`` (or 0.0) for
    non-numeric or non-finite input. Appends a human-readable warning to
    ``warnings`` whenever a clamp or fallback occurs.

    The function is intentionally permissive: it never raises. This is
    the right behavior for engineering analyzers that are called from
    inside an optimization loop where a single bad value would otherwise
    produce a NaN that poisons the entire population.
    """
    if warnings is None:
        warnings = []

    bounds = FACTORY_INPUT_BOUNDS.get(name)
    if bounds is None:
        # Unknown parameter: just sanitise, don't warn at length.
        if _is_finite_number(value):
            return float(value)
        fallback = float(default) if default is not None and _is_finite_number(default) else 0.0
        warnings.append(f"Factory input '{name}' not numeric ({value!r}); using {fallback}")
        return fallback

    lo, hi = bounds
    if not _is_finite_number(value):
        fallback = float(default) if default is not None and _is_finite_number(default) else lo
        warnings.append(f"Factory input '{name}' not finite ({value!r}); using {fallback}")
        return fallback

    v = float(value)
    if v < lo:
        warnings.append(f"Factory input '{name}'={v} below bound {lo}; clamped to {lo}")
        return lo
    if v > hi:
        warnings.append(f"Factory input '{name}'={v} above bound {hi}; clamped to {hi}")
        return hi
    return v


def validate_factory_graph(graph: Any, warnings: Optional[List[str]] = None) -> List[str]:
    """Normalize a FactoryProcessGraph: ensure each unit's numeric fields
    are within engineering bounds. Returns the (possibly extended)
    warnings list. Mutates unit fields in place (clamp is the standard
    behavior across the platform).
    """
    if warnings is None:
        warnings = []

    units = getattr(graph, "units", None)
    if not units:
        warnings.append("Factory graph has no units")
        return warnings

    for unit in units.values():
        if hasattr(unit, "efficiency"):
            unit.efficiency = clamp_factory_input(
                "efficiency", unit.efficiency, default=0.95, warnings=warnings
            )
        if hasattr(unit, "max_capacity_kg_hr"):
            unit.max_capacity_kg_hr = clamp_factory_input(
                "max_capacity_kg_hr",
                unit.max_capacity_kg_hr,
                default=1000.0,
                warnings=warnings,
            )
        if hasattr(unit, "footprint_m2"):
            unit.footprint_m2 = clamp_factory_input(
                "footprint_m2",
                unit.footprint_m2,
                default=10.0,
                warnings=warnings,
            )
        if hasattr(unit, "power_kw") and not _is_finite_number(unit.power_kw):
            unit.power_kw = 0.0
            warnings.append(f"Unit {unit.unit_id} power_kw reset to 0.0 (non-finite)")
    return warnings


__all__ = [
    "FACTORY_INPUT_BOUNDS",
    "clamp_factory_input",
    "validate_factory_graph",
]

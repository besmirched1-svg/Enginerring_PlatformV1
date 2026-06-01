# Parameter Bounds Specification

**Last Updated**: June 1, 2026  
**Status**: Production  
**Owner**: Engineering Team

---

## Overview

All design parameters in the OpenSCAD Engineering Platform are constrained to strict **physical** and **engineering limits**. These bounds are non-negotiable and enforced at three independent validation layers:

1. **API Input Validation** (Pydantic models)
2. **Mutation Engine** (hard clamping with logging)
3. **OpenSCAD Template Generation** (defensive re-validation)

This three-layer approach ensures that even if one validation layer fails, bounds cannot be violated.

---

## Parameter Specifications

### 1. wall_thickness

| Property | Value | Unit |
| --- | --- | --- |
| **Minimum** | 1.5 | mm |
| **Maximum** | 15.0 | mm |
| **Default** | 3.0 | mm |
| **Typical Mutation** | ±0.5 | mm |

**Engineering Rationale**:

- **Min (1.5mm)**: Below this thickness, structural integrity fails under typical loads. FEA indicates stress concentration > 200 MPa for thinner walls.
- **Max (15.0mm)**: Above this, material cost and weight become impractical. Exceeds 12-hour print time threshold.

**Scoring Impact**:

- Contributes 40% to composite score via structural_stability metric
- +0.1mm wall thickness ≈ +0.05 stability score
- -0.1mm wall thickness ≈ -0.08 stability score (higher sensitivity downward)

**Failure Signals**:

- wall_thickness_insufficient: Triggered when structural_stability < 0.60
- Mutation Response: Increase wall by (1.0 - stability) multiplied by learning_rate multiplied by 3.5 (clamped to bounds)

---

### 2. roller_radius

| Property | Value | Unit |
| --- | --- | --- |
| **Minimum** | 15.0 | mm |
| **Maximum** | 80.0 | mm |
| **Default** | 30.0 | mm |
| **Typical Mutation** | ±1.0-2.0 | mm |

**Engineering Rationale**:

- **Min (15.0mm)**: Minimum bearing width and mounting requirements. Smaller dimensions cannot accommodate standard bearing races.
- **Max (80.0mm)**: Maximum machine envelope constraint. Exceeds physical machine bed dimensions.

**Scoring Impact**:

- Contributes 40% to composite score via material_efficiency metric
- Larger radius increases material volume but improves load distribution
- +2.0mm radius ≈ -0.08 efficiency score (more material)
- -2.0mm radius ≈ +0.06 efficiency score (less material)

**Failure Signals**:

- material_inefficient: Triggered when material_efficiency < 0.50
- Mutation Response: Decrease radius by (1.0 - efficiency) multiplied by learning_rate multiplied by 1.5 multiplied by 2.0

---

### 3. clearance

| Property | Value | Unit |
| --- | --- | --- |
| **Minimum** | 0.2 | mm |
| **Maximum** | 3.0 | mm |
| **Default** | 0.5 | mm |
| **Typical Mutation** | ±0.1 | mm |

**Engineering Rationale**:

- **Min (0.2mm)**: Manufacturing tolerance floor. Typical 3D printers have ±0.1mm precision.
- **Max (3.0mm)**: Above this, assembly becomes loose and alignment fails.

**Scoring Impact**:

- Contributes 20% to composite score via performance_heuristics metric
- Tight clearance improves precision fit (+performance)
- Loose clearance reduces assembly difficulty (-performance)
- +0.1mm clearance ≈ +0.02 performance score
- -0.1mm clearance ≈ +0.01 performance score (diminishing returns below 0.3mm)

**Failure Signals**:

- clearance_binding: Triggered when clearance < 0.3 (tolerance too tight)
- Mutation Response: Increase clearance by 0.3mm (clamped to max)
- Mutation Response (No Signal): Decrease clearance by 0.05mm to improve fit (clamped to min)

---

### 4. bore_clearance

| Property | Value | Unit |
| --- | --- | --- |
| **Minimum** | 0.1 | mm |
| **Maximum** | 1.0 | mm |
| **Default** | 0.6 | mm |
| **Typical Mutation** | ±0.05 | mm |

**Engineering Rationale**:

- **Min (0.1mm)**: Bearing precision requirement. Standard bearings have tolerance stack-up of ~0.1mm.
- **Max (1.0mm)**: Maximum allowable shaft-bearing play while maintaining functionality.

**Note**: bore_clearance is not currently mutated (used only in design generation). Future enhancements may add mutation logic for this parameter.

---

## Validation Architecture

### Layer 1: API Input Validation (Pydantic)

```python
from pydantic import BaseModel, Field

class DesignConfig(BaseModel):
    wall_thickness: float = Field(
        default=3.0,
        ge=1.5,
        le=15.0
    )
    roller_radius: float = Field(
        default=30.0,
        ge=15.0,
        le=80.0
    )
    clearance: float = Field(
        default=0.5,
        ge=0.2,
        le=3.0
    )
    bore_clearance: float = Field(
        default=0.6,
        ge=0.1,
        le=1.0
    )
```

**When Enforced**: When POST /improve/register is called or any API accepts a DesignConfig

**Behavior**: Rejects request with 422 Validation Error if bounds violated

### Layer 2: Mutation Engine (Hard Clamping with Logging)

Located in app/core/mutation.py:

```python
PARAMETER_BOUNDS = {
    "wall_thickness": {"min": 1.5, "max": 15.0},
    "roller_radius": {"min": 15.0, "max": 80.0},
    "clearance": {"min": 0.2, "max": 3.0},
    "bore_clearance": {"min": 0.1, "max": 1.0},
}

def _validate_bounds(param_name: str, value: float) -> tuple[float, bool]:
    """Clamp value to bounds; log if modified."""
    if param_name not in PARAMETER_BOUNDS:
        return value, False

    bounds = PARAMETER_BOUNDS[param_name]
    if value < bounds["min"]:
        logger.debug(f"Parameter '{param_name}' clamped to min: {value} → {bounds['min']}")
        return bounds["min"], True
    elif value > bounds["max"]:
        logger.debug(f"Parameter '{param_name}' clamped to max: {value} → {bounds['max']}")
        return bounds["max"], True

    return value, False
```

**When Enforced**: During propose_next_config() in optimization loop

**Behavior**: Silently clamps violations and logs with DEBUG level (visible in logs but does not crash)

### Layer 3: OpenSCAD Template Generation (Defensive)

Located in app/core/orchestrator.py:

```python
def _generate_scad_template(self, config: Dict[str, Any]) -> str:
    wall = min(15.0, max(1.5, float(config.get("wall_thickness", 3.0))))
    radius = min(80.0, max(15.0, float(config.get("roller_radius", 30.0))))
    clearance = min(3.0, max(0.2, float(config.get("clearance", 0.5))))

    return f"... wall_thickness = {wall}; roller_radius = {radius}; ..."
```

**When Enforced**: When generating .scad file before OpenSCAD rendering

**Behavior**: Silently clamped (no logging, but prevents invalid geometry)

---

## Mutation Step Sizes

### Learning Rate Calculation

```python
error_delta = max(0.0, 1.0 - score)
learning_rate_step = min(1.5, 0.5 + (error_delta * 1.2))
```

### Specific Step Sizes by Issue Type

| Issue | Parameter | Formula | Typical Range |
| --- | --- | --- | --- |
| wall_thickness_insufficient | wall_thickness | error times learning_rate times 3.5 | +0.5 to +5.0mm |
| material_inefficient | wall_thickness | error times learning_rate times 1.5 | -0.5 to -2.5mm |
| material_inefficient | roller_radius | error times learning_rate times 3.0 | -1.0 to -5.0mm |
| clearance_binding | clearance | +0.3mm (fixed) | +0.3mm (once) |
| normal | clearance | -0.05mm (fixed) | -0.05mm (per cycle) |

---

## How to Update Bounds

### Process

1. **Identify Need**: Issue in production (always hitting max, never improving)
2. **Analyze**: Review logs to confirm bound is constraint, not design issue
3. **Propose Change**: Document engineering rationale for new bound
4. **Update Files**:
   - app/core/mutation.py → PARAMETER_BOUNDS constant
   - app/core/orchestrator.py → Template generation (if applicable)
   - PARAMETER_BOUNDS.md → This file (update rationale)
5. **Test**: Run edge case tests to verify new bounds work
6. **Deploy**: Include in release notes

### Example: Increase wall_thickness max from 15.0 to 20.0

```python
PARAMETER_BOUNDS = {
    "wall_thickness": {"min": 1.5, "max": 20.0},
    ...
}
```

---

## Monitoring & Alerts

### Key Metrics to Watch

1. **Clamping Frequency**: How often mutations hit bounds
   - Command: grep "clamped to" logs/*.log | wc -l
   - Expected: Low frequency (<5% of mutations)
   - Alert: If >10%, suggests bounds are too tight

2. **Final Score Distribution**: Do designs cluster at bounds?
   - Command: Check dashboard metrics over time
   - Expected: Normal distribution centered around 0.7
   - Alert: If skewed toward 0.5 or 1.0, bounds may be constraining

3. **Chain Termination Reason**: Are chains terminating due to bounds?
   - Command: grep "Halting optimization" logs/*.log
   - Expected: Rare; most chains complete naturally
   - Alert: If frequent, suggests mutation strategy needs tuning

---

## FAQ

**Q: Why not make bounds dynamic/adaptive?**

A: Dynamic bounds introduce non-determinism. Testing and auditing become harder. Static bounds are predictable.

**Q: What if a design legitimately needs values outside bounds?**

A: Bounds were set conservatively. If your design needs different values, contact engineering team to evaluate new bounds with same rationale.

**Q: How do I test new bounds before deploying?**

A: Update bounds, run pytest tests/test_mutation_edge_cases.py -v to verify no crashes, review logs for clamping patterns.

**Q: Can I override bounds via API?**

A: No. Bounds are enforced at 3 layers; no override mechanism exists. This is intentional for safety.

---

## Related Documents

- CURRENT_STATE_AND_ROADMAP.md - System overview
- IMPLEMENTATION_GUIDE.md - Task checklist for hardening
- MASTER_PROMPT.md - Development principles and error handling patterns
- app/core/mutation.py - PARAMETER_BOUNDS constant and validate_bounds function
- tests/test_mutation_edge_cases.py - Tests validating bounds enforcement

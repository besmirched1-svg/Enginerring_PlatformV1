from __future__ import annotations

from .base import AgentInput, AgentScore, BaseAgent


class ManufacturingAgent(BaseAgent):
    """Evaluates manufacturability: material utilisation, fabrication hours, assembly complexity."""

    name = "manufacturing"
    description = "Manufacturability scoring (utilisation, hours, complexity)"

    def evaluate(self, inp: AgentInput) -> AgentScore:
        config = inp.config
        issues: list[str] = []
        score = 0.0
        max_score = 0.0

        utilisation = _cf(config, "material_utilisation", "utilisation_pct")
        if utilisation is not None:
            max_score += 0.25
            if utilisation >= 75:
                score += 0.25
            elif utilisation >= 60:
                score += 0.18
                issues.append("Material utilisation {:.0f}% below 75% target".format(utilisation))
            elif utilisation >= 40:
                score += 0.10
                issues.append("Material utilisation {:.0f}% is low".format(utilisation))
            else:
                issues.append("Material utilisation {:.0f}% is very low — excessive waste".format(utilisation))

        total_hours = _cf(
            config, "total_fabrication_hours", "fabrication_hours",
            "total_manufacturing_hours",
        )
        if total_hours is not None:
            max_score += 0.15
            ref_hours = inp.target_mass_kg * 0.016 if inp.target_mass_kg > 0 else 20.0
            if total_hours <= ref_hours * 0.8:
                score += 0.15
            elif total_hours <= ref_hours * 1.2:
                score += 0.10
            elif total_hours <= ref_hours * 2.0:
                score += 0.05
                issues.append("Fabrication hours {:.1f}h above estimate".format(total_hours))
            else:
                issues.append("Fabrication hours {:.1f}h too high".format(total_hours))

        svc_index = _cf(config, "serviceability_index", "svc_index")
        if svc_index is not None:
            max_score += 0.20
            if svc_index >= 80:
                score += 0.20
            elif svc_index >= 60:
                score += 0.15
            elif svc_index >= 40:
                score += 0.08
                issues.append("Serviceability index {:.0f}/100 below 60 target".format(svc_index))
            else:
                issues.append("Serviceability index {:.0f}/100 too low — hard to maintain".format(svc_index))

        weld_length = _cf(config, "total_weld_length_m", "weld_length_m")
        mass = _cf(config, "total_mass_kg", "mass_kg")
        if weld_length is not None and mass is not None and mass > 0:
            max_score += 0.15
            ratio = weld_length / mass
            if ratio <= 0.008:
                score += 0.15
            elif ratio <= 0.015:
                score += 0.10
            elif ratio <= 0.025:
                score += 0.05
                issues.append("Weld length/mass ratio {:.4f} above 0.015 target".format(ratio))
            else:
                issues.append("Weld length/mass ratio {:.4f} too high".format(ratio))

        build_cost = _cf(config, "total_build_cost_aud", "build_cost_aud")
        if inp.target_cost_aud > 0 and build_cost is not None and build_cost > 0:
            max_score += 0.15
            ratio = build_cost / inp.target_cost_aud
            if ratio <= 0.9:
                score += 0.15
            elif ratio <= 1.1:
                score += 0.10
            elif ratio <= 1.5:
                score += 0.05
                issues.append("Build cost AUD${:.0f} exceeds target by {:.0f}%".format(
                    build_cost, (ratio - 1.0) * 100))
            else:
                issues.append("Build cost AUD${:.0f} exceeds target by >50%".format(build_cost))

        sheets = _cf(config, "sheets_required", "sheets")
        if sheets is not None:
            max_score += 0.10
            if sheets <= 5:
                score += 0.10
            elif sheets <= 10:
                score += 0.06
                issues.append("Requires {:.0f} sheets — consider nesting optimisation".format(sheets))
            else:
                issues.append("Requires {:.0f} sheets — high material handling".format(sheets))

        normalized = score / max_score if max_score > 0 else 0.5

        return AgentScore(
            name=self.name,
            score=min(1.0, normalized),
            passed=normalized >= 0.5,
            details={"issues": issues, "mfg_flags": len(issues)},
            weight=1.1,
        )


def _cf(config, *keys):
    for k in keys:
        v = config.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None

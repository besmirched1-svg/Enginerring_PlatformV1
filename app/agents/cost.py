from __future__ import annotations

from .base import AgentInput, AgentScore, BaseAgent


class CostAgent(BaseAgent):
    """Evaluates cost efficiency: build cost, cost per kg, cost vs target."""

    name = "cost"
    description = "Cost efficiency scoring"

    def evaluate(self, inp: AgentInput) -> AgentScore:
        config = inp.config
        issues: list[str] = []
        score = 0.0
        max_score = 0.0

        build_cost = _cf(config, "total_build_cost_aud", "build_cost_aud")
        mass = _cf(config, "total_mass_kg", "mass_kg")

        # Absolute cost vs target
        if inp.target_cost_aud > 0 and build_cost is not None and build_cost > 0:
            max_score += 0.25
            ratio = build_cost / inp.target_cost_aud
            if ratio <= 0.8:
                score += 0.25
            elif ratio <= 1.0:
                score += 0.18
            elif ratio <= 1.2:
                score += 0.08
                issues.append("Cost AUD${:.0f} within 20% of target".format(build_cost))
            else:
                issues.append("Cost AUD${:.0f} exceeds target AUD${:.0f}".format(build_cost, inp.target_cost_aud))

        # Cost per kg
        cost_per_kg = _cf(config, "cost_per_kg_aud", "cost_per_kg")
        if cost_per_kg is not None and cost_per_kg > 0:
            max_score += 0.25
            if cost_per_kg <= 15:
                score += 0.25
            elif cost_per_kg <= 25:
                score += 0.18
            elif cost_per_kg <= 40:
                score += 0.10
                issues.append("Cost per kg AUD${:.2f} above $25 target".format(cost_per_kg))
            else:
                issues.append("Cost per kg AUD${:.2f} too high".format(cost_per_kg))
        elif mass is not None and mass > 0 and build_cost is not None and build_cost > 0:
            max_score += 0.25
            cpk = build_cost / mass
            if cpk <= 15:
                score += 0.25
            elif cpk <= 25:
                score += 0.18
            elif cpk <= 40:
                score += 0.10
                issues.append("Implied cost per kg AUD${:.2f} above $25 target".format(cpk))
            else:
                issues.append("Implied cost per kg AUD${:.2f} too high".format(cpk))

        # Material cost efficiency
        material_cost = _cf(config, "material_cost_aud", "material_cost")
        if build_cost is not None and build_cost > 0 and material_cost is not None and material_cost > 0:
            max_score += 0.20
            mat_ratio = material_cost / build_cost
            if mat_ratio <= 0.4:
                score += 0.20
            elif mat_ratio <= 0.6:
                score += 0.12
                issues.append("Material cost {:.0f}% of total — above 40% benchmark".format(mat_ratio * 100))
            else:
                issues.append("Material cost {:.0f}% of total is high".format(mat_ratio * 100))

        # Manufacturing hours cost
        total_hours = _cf(config, "total_fabrication_hours", "fabrication_hours", "total_manufacturing_hours")
        if total_hours is not None and build_cost is not None and build_cost > 0:
            max_score += 0.15
            implied_labour_rate = build_cost / max(1.0, total_hours)
            if implied_labour_rate <= 80:
                score += 0.15
            elif implied_labour_rate <= 120:
                score += 0.08
                issues.append("Implied labour rate AUD${:.0f}/hr above $80 target".format(implied_labour_rate))
            else:
                issues.append("Implied labour rate AUD${:.0f}/hr too high".format(implied_labour_rate))

        # Absolute score if no cost data available
        if max_score == 0:
            return AgentScore(
                name=self.name,
                score=0.5,
                passed=True,
                details={"issues": ["No cost data available — neutral score"]},
                weight=1.0,
            )

        normalized = score / max_score

        return AgentScore(
            name=self.name,
            score=min(1.0, normalized),
            passed=normalized >= 0.5,
            details={"issues": issues, "cost_flags": len(issues)},
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

from __future__ import annotations

from .base import AgentInput, AgentScore, BaseAgent


class ValidatorAgent(BaseAgent):
    """Checks design constraints and parameter bounds compliance."""

    name = "validator"
    description = "Constraint and bounds validation"

    def evaluate(self, inp: AgentInput) -> AgentScore:
        issues: list[str] = []
        score = 1.0
        config = inp.config

        # Temperature check
        temp = inp.temperature_c
        if temp > 100:
            if temp > 300:
                issues.append("Temperature {:.0f}C exceeds structural limit of 300C".format(temp))
                score -= 0.30
            elif temp > 200:
                issues.append("Temperature {:.0f}C requires special materials".format(temp))
                score -= 0.15
            else:
                issues.append("Temperature {:.0f}C above 100C — derating applied".format(temp))
                score -= 0.05

        # Mass constraint
        target_mass = inp.target_mass_kg
        mass = config.get("total_mass_kg") or config.get("mass_kg")
        if target_mass > 0 and mass:
            try:
                m = float(mass)
                if m > target_mass * 1.2:
                    ratio = m / target_mass
                    issues.append("Mass {:.0f}kg exceeds target {:.0f}kg by {:.0f}%".format(
                        m, target_mass, (ratio - 1.0) * 100))
                    score -= min(0.30, (ratio - 1.0) * 0.5)
            except (TypeError, ValueError):
                pass

        # Cost constraint
        target_cost = inp.target_cost_aud
        cost = config.get("total_build_cost_aud") or config.get("build_cost_aud")
        if target_cost > 0 and cost:
            try:
                c = float(cost)
                if c > target_cost * 1.2:
                    ratio = c / target_cost
                    issues.append("Cost AUD${:.0f} exceeds target AUD${:.0f}".format(c, target_cost))
                    score -= min(0.30, (ratio - 1.0) * 0.5)
            except (TypeError, ValueError):
                pass

        # Check for known invalid config combinations
        drum_diameter = config.get("drum_diameter")
        drum_length = config.get("drum_length")
        if drum_diameter and drum_length:
            try:
                if float(drum_length) > float(drum_diameter) * 10:
                    issues.append("Drum length/diameter ratio >10:1 is structurally unsound")
                    score -= 0.25
            except (TypeError, ValueError):
                pass

        score = max(0.0, score)

        return AgentScore(
            name=self.name,
            score=score,
            passed=score >= 0.5,
            details={"issues": issues, "constraint_flags": len(issues)},
            weight=1.0,
        )

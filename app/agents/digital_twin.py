from __future__ import annotations

from .base import AgentInput, AgentScore, BaseAgent


class DigitalTwinAgent(BaseAgent):
    """Evaluates digital twin predictions: wear, fatigue life, reliability."""

    name = "digital_twin"
    description = "Digital twin wear/fatigue/reliability prediction scoring"

    def evaluate(self, inp: AgentInput) -> AgentScore:
        config = inp.config
        issues: list[str] = []
        score = 0.0
        max_score = 0.0

        wear_rate = _cf(config, "wear_rate_mm_per_hr", "wear_rate")
        if wear_rate is not None:
            max_score += 0.30
            if wear_rate <= 0.01:
                score += 0.30
            elif wear_rate <= 0.05:
                score += 0.20
                issues.append("Wear rate {:.4f} mm/hr above ideal 0.01".format(wear_rate))
            elif wear_rate <= 0.10:
                score += 0.10
                issues.append("Wear rate {:.4f} mm/hr requires frequent maintenance".format(wear_rate))
            else:
                issues.append("Wear rate {:.4f} mm/hr too high".format(wear_rate))

        fatigue_life = _cf(config, "fatigue_life_cycles", "fatigue_cycles")
        if fatigue_life is not None:
            max_score += 0.25
            if fatigue_life >= 1e6:
                score += 0.25
            elif fatigue_life >= 1e5:
                score += 0.15
                issues.append("Fatigue life {:.0e} cycles below 1e6 target".format(fatigue_life))
            else:
                issues.append("Fatigue life {:.0e} cycles too low".format(fatigue_life))

        mtbf = _cf(config, "mtbf_hours", "mtbf")
        if mtbf is not None:
            max_score += 0.25
            if mtbf >= 10000:
                score += 0.25
            elif mtbf >= 5000:
                score += 0.15
                issues.append("MTBF {:.0f}h below 10,000h target".format(mtbf))
            else:
                issues.append("MTBF {:.0f}h below 5,000h minimum".format(mtbf))

        reliability = _cf(config, "reliability_1yr", "reliability")
        if reliability is not None:
            max_score += 0.20
            if reliability >= 0.95:
                score += 0.20
            elif reliability >= 0.85:
                score += 0.12
                issues.append("1-year reliability {:.1%} below 95% target".format(reliability))
            else:
                issues.append("1-year reliability {:.1%} too low".format(reliability))

        normalized = score / max_score if max_score > 0 else 0.5

        return AgentScore(
            name=self.name,
            score=min(1.0, normalized),
            passed=normalized >= 0.5,
            details={"issues": issues, "dt_flags": len(issues)},
            weight=1.0,
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

from __future__ import annotations

from .base import AgentInput, AgentScore, BaseAgent


class ReliabilityAgent(BaseAgent):
    """Estimates and scores reliability metrics: MTBF, failure rate, maintenance."""

    name = "reliability"
    description = "Reliability and maintenance scoring"

    def evaluate(self, inp: AgentInput) -> AgentScore:
        config = inp.config
        issues: list[str] = []
        score = 0.0
        max_score = 0.0

        mtbf = _cf(config, "mtbf_hours", "mtbf")
        if mtbf is not None:
            max_score += 0.30
            if mtbf >= 20000:
                score += 0.30
            elif mtbf >= 10000:
                score += 0.20
            elif mtbf >= 5000:
                score += 0.12
                issues.append("MTBF {:.0f}h below 10,000h target".format(mtbf))
            else:
                issues.append("MTBF {:.0f}h below 5,000h minimum".format(mtbf))

        failure_rate = _cf(config, "failure_rate_per_year", "failure_rate")
        if failure_rate is not None:
            max_score += 0.20
            if failure_rate <= 0.5:
                score += 0.20
            elif failure_rate <= 1.0:
                score += 0.14
            elif failure_rate <= 2.0:
                score += 0.08
                issues.append("Failure rate {:.1f}/year above 1.0 target".format(failure_rate))
            else:
                issues.append("Failure rate {:.1f}/year too high".format(failure_rate))

        maintenance_req = _cf(config, "maintenance_hours_per_year", "maintenance_hrs_yr")
        if maintenance_req is not None:
            max_score += 0.20
            if maintenance_req <= 50:
                score += 0.20
            elif maintenance_req <= 100:
                score += 0.14
            elif maintenance_req <= 200:
                score += 0.08
                issues.append("Maintenance {:.0f}h/yr above 100h target".format(maintenance_req))
            else:
                issues.append("Maintenance {:.0f}h/yr too high".format(maintenance_req))

        reliability_1yr = _cf(config, "reliability_1yr", "reliability")
        if reliability_1yr is not None:
            max_score += 0.30
            if reliability_1yr >= 0.98:
                score += 0.30
            elif reliability_1yr >= 0.95:
                score += 0.24
            elif reliability_1yr >= 0.90:
                score += 0.15
                issues.append("1-yr reliability {:.1%} below 95% target".format(reliability_1yr))
            else:
                issues.append("1-yr reliability {:.1%} too low".format(reliability_1yr))

        # Estimate from bearing life if no direct reliability data
        if reliability_1yr is None and mtbf is None:
            bearing_life = _cf(config, "bearing_life_hours", "bearing_life")
            if bearing_life is not None:
                max_score += 0.30
                if bearing_life >= 50000:
                    score += 0.20
                elif bearing_life >= 20000:
                    score += 0.12
                elif bearing_life >= 10000:
                    score += 0.06
                issues.append("Reliability estimated from bearing life ({:.0f}h)".format(bearing_life))

        if max_score == 0:
            return AgentScore(
                name=self.name,
                score=0.5,
                passed=True,
                details={"issues": ["No reliability data — neutral score"]},
                weight=1.0,
            )

        normalized = score / max_score

        return AgentScore(
            name=self.name,
            score=min(1.0, normalized),
            passed=normalized >= 0.5,
            details={"issues": issues, "rel_flags": len(issues)},
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

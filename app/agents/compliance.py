from __future__ import annotations

from .base import AgentInput, AgentScore, BaseAgent


class ComplianceAgent(BaseAgent):
    """Checks standards compliance: ISO, AS/NZS, CE, safety clearances."""

    name = "compliance"
    description = "Standards compliance checking (ISO, AS/NZS, CE)"

    def evaluate(self, inp: AgentInput) -> AgentScore:
        config = inp.config
        issues: list[str] = []
        score = 1.0

        machine_type = config.get("type", inp.machine_type)

        # Guarding checks
        has_guarding = config.get("has_guarding") or config.get("safety_guards")
        if has_guarding is not None:
            if not has_guarding:
                issues.append("No safety guarding specified (AS/NZS 4024.1 required)")
                score -= 0.25
        else:
            issues.append("Safety guarding status unknown")
            score -= 0.10

        # Emergency stop
        has_estop = config.get("has_emergency_stop") or config.get("estop")
        if has_estop is not None:
            if not has_estop:
                issues.append("No emergency stop (AS/NZS 4024.1201 required)")
                score -= 0.20
        else:
            issues.append("Emergency stop status unknown")
            score -= 0.10

        # PTO safety (agricultural machinery)
        if "roller" in machine_type or "decorticator" in machine_type:
            pto_guard = config.get("pto_guard") or config.get("pto_shielding")
            if pto_guard is not None:
                if not pto_guard:
                    issues.append("No PTO shielding (AS/NZS 2153 required)")
                    score -= 0.20
            else:
                issues.append("PTO shielding status unknown")
                score -= 0.05

        # Noise compliance
        noise_db = _cf(config, "noise_level_db", "noise_db")
        if noise_db is not None:
            if noise_db > 85:
                issues.append("Noise level {:.0f}dB exceeds 85dB limit (AS/NZS 2107)".format(noise_db))
                score -= 0.15
            elif noise_db > 80:
                issues.append("Noise level {:.0f}dB approaching 85dB limit".format(noise_db))
                score -= 0.05

        # Guard opening check (finger/ hand safety)
        opening = _cf(config, "guard_opening_mm", "guard_opening")
        if opening is not None:
            if opening > 10:
                issues.append("Guard opening {:.1f}mm exceeds 10mm for finger safety".format(opening))
                score -= 0.10

        # Temperature compliance
        temp = inp.temperature_c
        if temp > 100:
            issues.append("Operating temp {:.0f}C requires hot-surface guarding".format(temp))
            score -= 0.05

        score = max(0.0, score)

        return AgentScore(
            name=self.name,
            score=score,
            passed=score >= 0.5,
            details={"issues": issues, "compliance_flags": len(issues)},
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

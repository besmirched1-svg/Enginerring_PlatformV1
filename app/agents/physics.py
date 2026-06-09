from __future__ import annotations

from .base import AgentInput, AgentScore, BaseAgent


class PhysicsAgent(BaseAgent):
    """Evaluates physics analysis results: safety factors, bearing life, fatigue."""

    name = "physics"
    description = "Physics analysis scoring (safety factors, bearing life, fatigue)"

    def evaluate(self, inp: AgentInput) -> AgentScore:
        config = inp.config
        issues: list[str] = []
        score = 0.0
        max_score = 0.0

        # Shaft safety factor
        sf = _cf(config, "shaft_safety_factor", "shaft_sf")
        if sf is not None:
            max_score += 0.20
            if sf >= 2.0:
                score += 0.20
            elif sf >= 1.5:
                score += 0.15
            elif sf >= 1.0:
                score += 0.10
                issues.append("Shaft SF {:.2f} below recommended 2.0".format(sf))
            else:
                issues.append("Shaft SF {:.2f} below minimum 1.0".format(sf))

        # Frame safety factor
        sf = _cf(config, "frame_safety_factor", "frame_sf")
        if sf is not None:
            max_score += 0.20
            if sf >= 2.5:
                score += 0.20
            elif sf >= 2.0:
                score += 0.16
            elif sf >= 1.0:
                score += 0.10
                issues.append("Frame SF {:.2f} below recommended 2.5".format(sf))
            else:
                issues.append("Frame SF {:.2f} below minimum 1.0".format(sf))

        # Rotor safety factor
        sf = _cf(config, "rotor_safety_factor", "rotor_sf")
        if sf is not None:
            max_score += 0.15
            if sf >= 2.0:
                score += 0.15
            elif sf >= 1.0:
                score += 0.08
                issues.append("Rotor SF {:.2f} below recommended 2.0".format(sf))
            else:
                issues.append("Rotor SF {:.2f} below minimum 1.0".format(sf))

        # Bearing life
        bl = _cf(config, "bearing_life_hours", "bearing_life")
        if bl is not None:
            max_score += 0.20
            if bl >= 50000:
                score += 0.20
            elif bl >= 20000:
                score += 0.15
            elif bl >= 10000:
                score += 0.10
                issues.append("Bearing life {:.0f}h below 50,000h target".format(bl))
            else:
                issues.append("Bearing life {:.0f}h below 10,000h minimum".format(bl))

        # Fatigue safety factor
        sf = _cf(config, "fatigue_safety_factor", "fatigue_sf")
        if sf is not None:
            max_score += 0.15
            if sf >= 2.0:
                score += 0.15
            elif sf >= 1.0:
                score += 0.08
                issues.append("Fatigue SF {:.2f} below recommended 2.0".format(sf))
            else:
                issues.append("Fatigue SF {:.2f} below minimum 1.0".format(sf))

        # Natural frequency
        nf = _cf(config, "natural_frequency_hz", "nat_freq_hz")
        if nf is not None:
            max_score += 0.10
            if nf >= 10.0:
                score += 0.10
            elif nf >= 5.0:
                score += 0.05
                issues.append("Natural frequency {:.1f}Hz below 10Hz target".format(nf))

        if max_score == 0:
            return AgentScore(
                name=self.name,
                score=0.5,
                passed=True,
                details={"issues": ["No physics data — neutral score"]},
                weight=1.2,
            )

        normalized = score / max_score

        return AgentScore(
            name=self.name,
            score=min(1.0, normalized),
            passed=normalized >= 0.5,
            details={"issues": issues, "physics_flags": len(issues), "raw_score": score, "max_score": max_score},
            weight=1.2,
        )


def _cf(config, *keys):
    """Get config float by any of several key names."""
    for k in keys:
        v = config.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None

from __future__ import annotations

from typing import Any, Dict

from .base import AgentInput, AgentScore, BaseAgent


class DesignerAgent(BaseAgent):
    """Evaluates design quality: proportions, standard sizes, best-practice ratios."""

    name = "designer"
    description = "Design quality assessment (proportions, ratios, standards)"

    def evaluate(self, inp: AgentInput) -> AgentScore:
        config = inp.config
        issues: list[str] = []
        score = 1.0

        config_type = config.get("type", inp.machine_type)

        # Drum L/D ratio check (hemp decorticators)
        drum_diameter = _get_float(config, "drum_diameter", "drum", "diameter")
        drum_length = _get_float(config, "drum_length", "drum", "length")
        if drum_diameter and drum_length and drum_diameter > 0:
            ld_ratio = drum_length / drum_diameter
            if ld_ratio < 1.5:
                issues.append("Drum L/D ratio {:.1f} below minimum 1.5".format(ld_ratio))
                score -= 0.15
            elif ld_ratio > 6.0:
                issues.append("Drum L/D ratio {:.1f} above maximum 6.0".format(ld_ratio))
                score -= 0.10

        # Wall thickness minimum
        wall = _get_float(config, "wall_thickness", "frame", "wall_thickness", "drum", "wall_thickness")
        if wall and wall < 4.0:
            issues.append("Wall thickness {:.1f}mm below minimum 4.0mm".format(wall))
            score -= 0.20

        # Roller clearance
        bore_clearance = _get_float(config, "bore_clearance", "roller", "bore_clearance")
        roller_diameter = _get_float(config, "roller_diameter", "roller", "diameter")
        if bore_clearance is not None and roller_diameter and roller_diameter > 0:
            clearance_ratio = bore_clearance / roller_diameter
            if clearance_ratio < 0.01:
                issues.append("Bore clearance ratio {:.4f} too tight".format(clearance_ratio))
                score -= 0.10
            elif clearance_ratio > 0.05:
                issues.append("Bore clearance ratio {:.4f} too loose".format(clearance_ratio))
                score -= 0.05

        # Flight pitch ratio
        pitch = _get_float(config, "flight_pitch", "drum", "flight_pitch", "spindle", "flight_pitch")
        shaft_dia = _get_float(config, "shaft_diameter", "spindle", "diameter")
        if pitch and shaft_dia and shaft_dia > 0:
            pitch_ratio = pitch / shaft_dia
            if pitch_ratio < 0.5:
                issues.append("Flight pitch/shaft ratio {:.2f} below 0.5".format(pitch_ratio))
                score -= 0.10
            elif pitch_ratio > 3.0:
                issues.append("Flight pitch/shaft ratio {:.2f} above 3.0".format(pitch_ratio))
                score -= 0.05

        # Skid width vs drum OD
        drum_od = _get_float(config, "drum_od", "drum", "outer_diameter", "drum", "od")
        skid_width = _get_float(config, "skid_width", "frame", "skid_width")
        if drum_od and skid_width and skid_width > 0:
            if drum_od > skid_width:
                issues.append("Drum OD {:.1f} exceeds skid width {:.1f}".format(drum_od, skid_width))
                score -= 0.15

        # Mass check
        mass = _get_float(config, "total_mass_kg", "mass_kg")
        if inp.target_mass_kg > 0 and mass and mass > 0:
            if mass > inp.target_mass_kg * 1.5:
                issues.append("Mass {:.0f}kg exceeds target by >50%".format(mass))
                score -= 0.10

        score = max(0.0, score)

        return AgentScore(
            name=self.name,
            score=score,
            passed=score >= 0.5,
            details={"issues": issues, "quality_flags": len(issues)},
            weight=1.0,
        )


def _get_float(config: Dict[str, Any], *keys: str) -> float | None:
    """Safely extract a float value from config, trying top-level keys first,
    then nested section.key pairs."""
    for k in keys:
        if k in config:
            try:
                return float(config[k])
            except (TypeError, ValueError):
                pass
    for i in range(0, len(keys) - 1, 2):
        section = config.get(keys[i])
        if isinstance(section, dict):
            val = section.get(keys[i + 1])
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
    return None

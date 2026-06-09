# app/domain/hemp/models.py
#
# Hemp decorticator domain models.
# These are the engineering parameters specific to hemp fibre processing
# that the generic evaluation engine does not capture.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class HempProcessConditions:
    """
    Operating conditions for a hemp decorticator run.

    All values are SI or industry-standard units as noted.
    """
    # Feedstock
    moisture_content_pct: float = 15.0    # % wet basis (typical: 10–25%)
    stalk_diameter_mm: float = 8.0        # mm (typical: 5–15 mm)
    feed_rate_kg_hr: float = 1000.0       # kg/hr dry matter

    # Machine operating parameters
    drum_rpm: float = 18.0                # rev/min (typical: 12–25)
    compression_force_kn: float = 5.0    # kN nip force
    drum_inclination_deg: float = 3.0    # degrees from horizontal

    # Target outputs
    target_fibre_recovery_pct: float = 85.0   # % of bast fibre recovered
    target_fibre_quality: str = "long"         # "long", "short", "mixed"
    target_throughput_kg_hr: float = 800.0    # kg/hr fibre output


@dataclass
class HempPerformanceResult:
    """
    Predicted performance of a hemp decorticator configuration.
    """
    # Outputs
    fibre_recovery_pct: float = 0.0
    fibre_quality_score: float = 0.0      # 0.0–1.0
    throughput_kg_hr: float = 0.0
    power_draw_kw: float = 0.0
    specific_energy_kwh_t: float = 0.0   # kWh per tonne processed

    # Quality breakdown
    long_fibre_pct: float = 0.0
    short_fibre_pct: float = 0.0
    shive_contamination_pct: float = 0.0

    # Reliability
    estimated_wear_rate: float = 0.0     # relative 0.0–1.0 (1.0 = high wear)
    maintenance_interval_hr: float = 500.0

    # Composite score (0.0–1.0, higher is better)
    composite_score: float = 0.0
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fibre_recovery_pct": round(self.fibre_recovery_pct, 2),
            "fibre_quality_score": round(self.fibre_quality_score, 3),
            "throughput_kg_hr": round(self.throughput_kg_hr, 1),
            "power_draw_kw": round(self.power_draw_kw, 1),
            "specific_energy_kwh_t": round(self.specific_energy_kwh_t, 2),
            "long_fibre_pct": round(self.long_fibre_pct, 1),
            "short_fibre_pct": round(self.short_fibre_pct, 1),
            "shive_contamination_pct": round(self.shive_contamination_pct, 1),
            "estimated_wear_rate": round(self.estimated_wear_rate, 3),
            "maintenance_interval_hr": round(self.maintenance_interval_hr, 0),
            "composite_score": round(self.composite_score, 4),
            "issues": self.issues,
        }

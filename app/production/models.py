# app/production/models.py
# Phase 15 Autonomous Manufacturing & Deployment: shared dataclasses.
#
# This package produces manufacturing OUTPUT artifacts (G-code, documents,
# plans, telemetry schemas). It does not drive machines or field hardware -
# physical execution is a deliberate outward-facing opt-in.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


@dataclass
class GCodeProgram:
    """An ISO 6983 (G-code) part program as ordered text lines."""
    name: str = "program"
    lines: List[str] = field(default_factory=list)
    units: str = "mm"
    tool: int = 1
    spindle_rpm: float = 0.0
    feed_mm_min: float = 0.0
    operation: str = ""

    def to_text(self) -> str:
        return "\n".join(self.lines) + ("\n" if self.lines else "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "operation": self.operation,
            "units": self.units,
            "tool": self.tool,
            "spindle_rpm": self.spindle_rpm,
            "feed_mm_min": self.feed_mm_min,
            "line_count": len(self.lines),
            "gcode": self.to_text(),
        }


@dataclass
class CutListDocument:
    """A production-ready cut list (rows + totals) exportable to CSV/text."""
    title: str = "Cut List"
    process: str = ""
    rows: List[Dict[str, Any]] = field(default_factory=list)
    sheets_required: int = 0
    total_parts: int = 0
    material_utilisation: float = 0.0
    total_mass_kg: float = 0.0
    notes: List[str] = field(default_factory=list)

    def to_csv(self) -> str:
        if not self.rows:
            return ""
        headers = list(self.rows[0].keys())
        out = [",".join(headers)]
        for row in self.rows:
            out.append(",".join(str(row.get(h, "")) for h in headers))
        return "\n".join(out) + "\n"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "process": self.process,
            "rows": self.rows,
            "sheets_required": self.sheets_required,
            "total_parts": self.total_parts,
            "material_utilisation": round(self.material_utilisation, 4),
            "total_mass_kg": round(self.total_mass_kg, 3),
            "notes": self.notes,
        }


@dataclass
class WeldMapDocument:
    """A production-ready weld schedule exportable to CSV/text."""
    title: str = "Weld Map"
    rows: List[Dict[str, Any]] = field(default_factory=list)
    total_weld_length_mm: float = 0.0
    total_deposit_mass_kg: float = 0.0
    electrode_mass_kg: float = 0.0
    gas_volume_litres: float = 0.0
    notes: List[str] = field(default_factory=list)

    def to_csv(self) -> str:
        if not self.rows:
            return ""
        headers = list(self.rows[0].keys())
        out = [",".join(headers)]
        for row in self.rows:
            out.append(",".join(str(row.get(h, "")) for h in headers))
        return "\n".join(out) + "\n"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "rows": self.rows,
            "total_weld_length_mm": round(self.total_weld_length_mm, 1),
            "total_deposit_mass_kg": round(self.total_deposit_mass_kg, 3),
            "electrode_mass_kg": round(self.electrode_mass_kg, 3),
            "gas_volume_litres": round(self.gas_volume_litres, 1),
            "notes": self.notes,
        }


class QASeverity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


@dataclass
class QACheck:
    """A single inspection / acceptance check."""
    check_id: str
    description: str = ""
    method: str = "visual"            # visual | dimensional | ndt | functional
    nominal: Optional[float] = None
    tolerance: Optional[float] = None
    unit: str = ""
    severity: QASeverity = QASeverity.MAJOR

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "description": self.description,
            "method": self.method,
            "nominal": self.nominal,
            "tolerance": self.tolerance,
            "unit": self.unit,
            "severity": self.severity.value,
        }


@dataclass
class QAInspectionPlan:
    """An ordered set of QA checks for a build."""
    title: str = "QA Inspection Plan"
    checks: List[QACheck] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "check_count": len(self.checks),
            "checks": [c.to_dict() for c in self.checks],
            "notes": self.notes,
        }


@dataclass
class CommissioningStep:
    """A single commissioning procedure step."""
    step_no: int
    title: str = ""
    action: str = ""
    acceptance: str = ""
    hold_point: bool = False          # requires sign-off before proceeding

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_no": self.step_no,
            "title": self.title,
            "action": self.action,
            "acceptance": self.acceptance,
            "hold_point": self.hold_point,
        }


@dataclass
class CommissioningPlan:
    """Ordered commissioning / handover procedure."""
    title: str = "Commissioning Plan"
    steps: List[CommissioningStep] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "step_count": len(self.steps),
            "steps": [s.to_dict() for s in self.steps],
            "notes": self.notes,
        }


@dataclass
class TelemetryChannel:
    """A field telemetry channel definition for a deployed machine."""
    name: str
    unit: str = ""
    sample_rate_hz: float = 1.0
    warn_low: Optional[float] = None
    warn_high: Optional[float] = None
    alarm_low: Optional[float] = None
    alarm_high: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "sample_rate_hz": self.sample_rate_hz,
            "warn_low": self.warn_low,
            "warn_high": self.warn_high,
            "alarm_low": self.alarm_low,
            "alarm_high": self.alarm_high,
        }


@dataclass
class FieldTelemetrySchema:
    """Telemetry schema registered for a deployed machine.

    Defines what a commissioned machine should report; the existing telemetry
    subsystem consumes data against this contract. No live connection here.
    """
    machine_id: str = ""
    machine_name: str = ""
    channels: List[TelemetryChannel] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "machine_name": self.machine_name,
            "channel_count": len(self.channels),
            "channels": [c.to_dict() for c in self.channels],
            "notes": self.notes,
        }


@dataclass
class ProductionPackage:
    """Complete manufacturing & deployment output for a machine/design."""
    machine_name: str = ""
    cut_list: Optional[CutListDocument] = None
    weld_map: Optional[WeldMapDocument] = None
    cnc_programs: List[GCodeProgram] = field(default_factory=list)
    qa_plan: Optional[QAInspectionPlan] = None
    commissioning: Optional[CommissioningPlan] = None
    telemetry: Optional[FieldTelemetrySchema] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "machine_name": self.machine_name,
            "cut_list": self.cut_list.to_dict() if self.cut_list else None,
            "weld_map": self.weld_map.to_dict() if self.weld_map else None,
            "cnc_programs": [p.to_dict() for p in self.cnc_programs],
            "qa_plan": self.qa_plan.to_dict() if self.qa_plan else None,
            "commissioning": self.commissioning.to_dict() if self.commissioning else None,
            "telemetry": self.telemetry.to_dict() if self.telemetry else None,
            "notes": self.notes,
        }

# app/production/__init__.py
# Phase 15 Autonomous Manufacturing & Deployment: close the loop between
# digital and physical engineering by producing manufacturing output artifacts.

from .cnc import (
    generate_drilling_program,
    generate_profile_program,
    rectangle_points,
)
from .commissioning import build_commissioning_plan
from .documents import (
    ProductionCutListGenerator,
    build_cutlist_document,
    build_weldmap_document,
)
from .field_telemetry import build_telemetry_schema
from .models import (
    CommissioningPlan,
    CommissioningStep,
    CutListDocument,
    FieldTelemetrySchema,
    GCodeProgram,
    ProductionPackage,
    QACheck,
    QAInspectionPlan,
    QASeverity,
    TelemetryChannel,
    WeldMapDocument,
)
from .package import build_production_package
from .qa import build_qa_plan

__all__ = [
    # models
    "GCodeProgram",
    "CutListDocument",
    "WeldMapDocument",
    "QASeverity",
    "QACheck",
    "QAInspectionPlan",
    "CommissioningStep",
    "CommissioningPlan",
    "TelemetryChannel",
    "FieldTelemetrySchema",
    "ProductionPackage",
    # cnc
    "generate_drilling_program",
    "generate_profile_program",
    "rectangle_points",
    # documents
    "build_cutlist_document",
    "build_weldmap_document",
    "ProductionCutListGenerator",
    # qa / commissioning / telemetry
    "build_qa_plan",
    "build_commissioning_plan",
    "build_telemetry_schema",
    # orchestration
    "build_production_package",
]

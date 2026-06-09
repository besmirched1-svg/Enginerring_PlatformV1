# app/production/package.py
# Phase 15: production package orchestration.

from __future__ import annotations

import logging
from typing import Any, List, Optional

from .commissioning import build_commissioning_plan
from .documents import build_cutlist_document, build_weldmap_document
from .field_telemetry import build_telemetry_schema
from .models import GCodeProgram, ProductionPackage
from .qa import build_qa_plan

logger = logging.getLogger("engine.production.package")


def build_production_package(
    machine_name: str = "machine",
    cut_list_result: Any = None,
    weld_map: Any = None,
    cnc_programs: Optional[List[GCodeProgram]] = None,
    rated_rpm: float = 0.0,
    rated_power_kw: float = 0.0,
    rated_throughput_kg_hr: float = 0.0,
    machine_id: str = "",
    process: str = "",
) -> ProductionPackage:
    """Assemble a complete manufacturing & deployment package for a machine.

    Combines cut list and weld map documents, CNC programs, a QA inspection
    plan, a commissioning plan, and a field telemetry schema into one
    deployable artifact set.
    """
    pkg = ProductionPackage(machine_name=machine_name)

    if cut_list_result is not None:
        pkg.cut_list = build_cutlist_document(cut_list_result, process=process)
    if weld_map is not None:
        pkg.weld_map = build_weldmap_document(weld_map)

    pkg.cnc_programs = list(cnc_programs or [])

    pkg.qa_plan = build_qa_plan(cut_list=cut_list_result, weld_map=weld_map)
    pkg.commissioning = build_commissioning_plan(
        machine_name=machine_name,
        rated_rpm=rated_rpm,
        rated_throughput_kg_hr=rated_throughput_kg_hr,
    )
    pkg.telemetry = build_telemetry_schema(
        machine_id=machine_id,
        machine_name=machine_name,
        rated_rpm=rated_rpm or None,
        rated_power_kw=rated_power_kw or None,
        rated_throughput_kg_hr=rated_throughput_kg_hr or None,
    )

    logger.info(
        "Built production package for '%s': cut_list=%s weld_map=%s cnc=%d qa=%d commissioning=%d telemetry=%d",
        machine_name, pkg.cut_list is not None, pkg.weld_map is not None,
        len(pkg.cnc_programs),
        len(pkg.qa_plan.checks) if pkg.qa_plan else 0,
        len(pkg.commissioning.steps) if pkg.commissioning else 0,
        len(pkg.telemetry.channels) if pkg.telemetry else 0,
    )
    return pkg

# app/production/qa.py
# Phase 15: QA inspection plan generation.

from __future__ import annotations

import logging
from typing import Any, List, Optional

from .models import QACheck, QAInspectionPlan, QASeverity

logger = logging.getLogger("engine.production.qa")


def build_qa_plan(
    cut_list: Any = None,
    weld_map: Any = None,
    dimensional_tolerance_mm: float = 0.5,
    title: str = "QA Inspection Plan",
) -> QAInspectionPlan:
    """Derive a QA inspection plan from cut parts and weld joints.

    Generates dimensional checks for cut parts, weld inspection checks per
    joint (visual + NDT for thicker/multi-pass welds), and standard material
    certification and functional checks.
    """
    checks: List[QACheck] = []
    n = 0

    # Standard incoming checks.
    n += 1
    checks.append(QACheck(
        check_id=f"QA-{n:03d}", description="Material certificates match BOM",
        method="visual", severity=QASeverity.CRITICAL,
    ))

    # Dimensional checks per cut part.
    for part in getattr(cut_list, "parts", []) or []:
        n += 1
        checks.append(QACheck(
            check_id=f"QA-{n:03d}",
            description=f"Part {part.part_id} length",
            method="dimensional",
            nominal=part.length_mm, tolerance=dimensional_tolerance_mm, unit="mm",
            severity=QASeverity.MAJOR,
        ))
        if part.width_mm:
            n += 1
            checks.append(QACheck(
                check_id=f"QA-{n:03d}",
                description=f"Part {part.part_id} width",
                method="dimensional",
                nominal=part.width_mm, tolerance=dimensional_tolerance_mm, unit="mm",
                severity=QASeverity.MAJOR,
            ))

    # Weld inspection checks per joint.
    for joint in getattr(weld_map, "joints", []) or []:
        n += 1
        checks.append(QACheck(
            check_id=f"QA-{n:03d}",
            description=f"Weld {joint.joint_id} visual inspection (profile, undercut, porosity)",
            method="visual", severity=QASeverity.MAJOR,
        ))
        thick = max(joint.plate_thickness_mm_1, joint.plate_thickness_mm_2)
        if joint.passes > 1 or thick >= 10.0:
            n += 1
            checks.append(QACheck(
                check_id=f"QA-{n:03d}",
                description=f"Weld {joint.joint_id} NDT (penetrant or ultrasonic)",
                method="ndt", severity=QASeverity.CRITICAL,
            ))

    # Standard functional checks.
    for desc, sev in (
        ("Fastener torque to specification", QASeverity.MAJOR),
        ("Protective coating thickness", QASeverity.MINOR),
        ("Rotating assembly free of binding", QASeverity.CRITICAL),
    ):
        n += 1
        checks.append(QACheck(
            check_id=f"QA-{n:03d}", description=desc,
            method="functional", severity=sev,
        ))

    logger.info("Built QA plan with %d checks", len(checks))
    return QAInspectionPlan(title=title, checks=checks)

# app/production/documents.py
# Phase 15: production-ready cut list and weld map documents.
#
# Wraps the existing app/manufacturing analysis results into exportable
# documents (CSV/text) rather than re-implementing the analysis.

from __future__ import annotations

import logging
from typing import Any

from .models import CutListDocument, WeldMapDocument

logger = logging.getLogger("engine.production.documents")


def build_cutlist_document(result: Any, process: str = "") -> CutListDocument:
    """Build a cut list document from a manufacturing CutListResult."""
    rows = []
    for part in getattr(result, "parts", []):
        rows.append({
            "part_id": part.part_id,
            "shape": part.shape.value if hasattr(part.shape, "value") else part.shape,
            "length_mm": part.length_mm,
            "width_mm": part.width_mm,
            "thickness_mm": part.thickness_mm,
            "quantity": part.quantity,
            "material": part.material,
        })
    return CutListDocument(
        title="Cut List",
        process=process,
        rows=rows,
        sheets_required=getattr(result, "sheets_required", 0),
        total_parts=getattr(result, "total_parts", len(rows)),
        material_utilisation=getattr(result, "material_utilisation", 0.0),
        total_mass_kg=getattr(result, "total_mass_kg", 0.0),
        notes=list(getattr(result, "notes", []) or []),
    )


def build_weldmap_document(weld_map: Any) -> WeldMapDocument:
    """Build a weld map document from a manufacturing WeldMap."""
    rows = []
    for joint in getattr(weld_map, "joints", []):
        rows.append({
            "joint_id": joint.joint_id,
            "joint_type": joint.joint_type.value if hasattr(joint.joint_type, "value") else joint.joint_type,
            "process": joint.process.value if hasattr(joint.process, "value") else joint.process,
            "weld_length_mm": joint.weld_length_mm,
            "throat_thickness_mm": joint.throat_thickness_mm,
            "passes": joint.passes,
            "quantity": joint.quantity,
            "material": joint.material,
        })
    consumables = getattr(weld_map, "consumables", None)
    return WeldMapDocument(
        title="Weld Map",
        rows=rows,
        total_weld_length_mm=getattr(weld_map, "total_weld_length_mm", 0.0),
        total_deposit_mass_kg=getattr(weld_map, "total_deposit_mass_kg", 0.0),
        electrode_mass_kg=getattr(consumables, "electrode_mass_kg", 0.0) if consumables else 0.0,
        gas_volume_litres=getattr(consumables, "gas_volume_litres", 0.0) if consumables else 0.0,
        notes=list(getattr(weld_map, "notes", []) or []),
    )

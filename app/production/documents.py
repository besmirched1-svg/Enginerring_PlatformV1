# app/production/documents.py
# Phase 15: production-ready cut list and weld map documents.
#
# Two surfaces live here:
#   1. In-memory adapters: ``build_cutlist_document`` and
#      ``build_weldmap_document`` wrap a manufacturing result into an
#      exportable document (CSV / dict / text). No math, no lookups.
#   2. On-disk generators: ``ProductionCutListGenerator`` writes a job's
#      cut list directly to disk (CSV + text summary) under a job-id
#      output directory. This is the file-system equivalent of the
#      in-memory adapter and is consumed by the CLI / shop-floor tools.
#
# The dependency direction is one-way: ``app.production`` imports
# manufacturing types (``CutListAnalyzer``, ``CutPart``) but never the
# other way around. See ``app/production/models.py`` for the layer rules.

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.manufacturing.cutlists import CutListAnalyzer, CutPart

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


class ProductionCutListGenerator:
    """Generates production-ready cut lists as CSV and formatted reports.

    On-disk counterpart to :func:`build_cutlist_document`. Writes:

    * ``cutlist_{job_id}.csv`` — one row per part, shop-floor format.
    * ``cutlist_summary_{job_id}.txt`` — totals, utilisation, cut time,
      and any notes from the analyzer.

    The class is purely a packaging / IO concern: it consumes a
    ``CutListAnalyzer`` (manufacturing) and writes files. No engineering
    math is performed here.
    """

    def __init__(self, analyzer: Optional[CutListAnalyzer] = None):
        self.analyzer = analyzer or CutListAnalyzer()

    def generate(
        self,
        parts: List[CutPart],
        job_id: str,
        output_dir: Path,
    ) -> Dict[str, Path]:
        """Generate the CSV and text summary for a job."""
        logger.info("Generating production cut list for job %s", job_id)

        # 1. Perform analysis to get totals and efficiency
        analysis_result = self.analyzer.analyze(parts)

        # 2. Generate CSV for the shop floor
        csv_path = output_dir / f"cutlist_{job_id}.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Part ID", "Quantity", "Length (mm)", "Width (mm)",
                "Thickness (mm)", "Material", "Shape",
            ])
            for p in parts:
                writer.writerow([
                    p.part_id, p.quantity, p.length_mm, p.width_mm,
                    p.thickness_mm, p.material, p.shape.value,
                ])

        # 3. Generate formatted text summary (proxy for PDF)
        summary_path = output_dir / f"cutlist_summary_{job_id}.txt"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write(f"PRODUCTION CUT LIST SUMMARY - Job: {job_id}\n")
            f.write("=" * 60 + "\n")
            f.write(f"Process:            {self.analyzer.config.process.value}\n")
            f.write(
                f"Sheet Dimensions:   "
                f"{self.analyzer.config.sheet_width_mm}x"
                f"{self.analyzer.config.sheet_length_mm}x"
                f"{self.analyzer.config.sheet_thickness_mm} mm\n"
            )
            f.write(f"Material:           {self.analyzer.config.sheet_material}\n")
            f.write("-" * 60 + "\n")
            f.write(f"Total Parts:        {analysis_result.total_parts}\n")
            f.write(f"Sheets Required:    {analysis_result.sheets_required}\n")
            f.write(f"Total Mass:         {analysis_result.total_mass_kg:.2f} kg\n")
            f.write(f"Material Util:      {analysis_result.material_utilisation:.1f}%\n")
            f.write(f"Estimated Cut Time: {analysis_result.total_cut_time_minutes:.1f} min\n")
            f.write("-" * 60 + "\n")
            if analysis_result.notes:
                f.write("Notes:\n")
                for note in analysis_result.notes:
                    f.write(f"- {note}\n")
            f.write("=" * 60 + "\n")

        return {"csv": csv_path, "summary": summary_path}

import os
import uuid
import logging
import subprocess
from pathlib import Path
from app.cad.renderer import render_stl
from typing import Any, Dict, Optional
from app.core.evaluation import (
    evaluate_build,
    total_mass_from_bom_rows,
)

from app.bom.generator import generate_bom
from app.core.revisions import archive_revision, update_promotion_status
from app.core.promotion import get_current_champion, should_promote, set_new_champion
from app.core.lineage import log_design_evolution
from app.core.notifier import dispatch_cluster_alert

logger = logging.getLogger("engine.orchestrator")

class EngineeringOrchestrator:
    def __init__(self, event_bus: Any):
        self.event_bus = event_bus

    def _generate_scad_template(self, config: Dict[str, Any]) -> str:
        wall = config.get("wall_thickness", 3.0)
        clearance = config.get("clearance", 0.5)
        radius = config.get("roller_radius", 30.0)
        return f"$fn = 100; wall_thickness = {wall}; roller_clearance = {clearance}; roller_radius = {radius}; module roller_assembly() {{ difference() {{ cylinder(h=150, r=roller_radius + wall_thickness, center=true); cylinder(h=160, r=roller_radius - roller_clearance, center=true); }} }} roller_assembly();"

    def _calculate_live_metrics(self, config: Dict[str, Any], attempt: int) -> Dict[str, Any]:
        wall = float(config.get("wall_thickness", 3.0))
        radius = float(config.get("roller_radius", 30.0))
        clearance = float(config.get("clearance", 0.5))
        stability = round(min(1.0, (wall / 6.0) * (50.0 / radius)), 2)
        material_efficiency = round(max(0.1, 1.0 - (wall / 15.0) - (radius / 150.0)), 2)
        performance = round(min(1.0, (clearance * 2.0) / (wall + 0.1)), 2)
        composite_score = round((stability * 0.4) + (material_efficiency * 0.4) + (performance * 0.2), 2)
        return {"score": composite_score, "metrics": {"structural_stability": stability, "material_efficiency": material_efficiency, "performance_heuristics": performance}, "issues": []}

    def _emit_event(self, event_type: str, payload: Dict[str, Any] | None = None) -> None:
        if self.event_bus is None:
            return
        if hasattr(self.event_bus, "publish"):
            self.event_bus.publish(event_type, payload or {})
        elif hasattr(self.event_bus, "broadcast"):
            self.event_bus.broadcast(event_type, payload or {})
        elif hasattr(self.event_bus, "emit"):
            self.event_bus.emit(event_type, payload or {})

    def _make_stl_url(self, machine_name: str, revision_id: str) -> str:
        return f"/outputs/revisions/{machine_name}/{revision_id}/output.stl"

    def _extract_evaluation_metrics(self, evaluation_result: Dict[str, Any]) -> Dict[str, Any]:
        metrics = evaluation_result.get("metrics", {})
        return {
            "score": evaluation_result.get("composite", 0.0),
            "composite_score": evaluation_result.get("composite", 0.0),
            "structural_stability": metrics.get("structural_validity", {}).get("score") if isinstance(metrics.get("structural_validity"), dict) else metrics.get("structural_validity"),
            "material_efficiency": metrics.get("material_efficiency", {}).get("score") if isinstance(metrics.get("material_efficiency"), dict) else metrics.get("material_efficiency"),
            "manufacturing_simplicity": metrics.get("manufacturability", {}).get("score") if isinstance(metrics.get("manufacturability"), dict) else metrics.get("manufacturability"),
            "evaluation": evaluation_result,
        }

    def run_machine_job(
        self, 
        machine_name: str, 
        config: Dict[str, Any], 
        chain_id: Optional[str] = None, 
        attempt_in_chain: int = 0
    ) -> Dict[str, Any]:
        revision_id = f"rev_{uuid.uuid4().hex[:8]}"
        logger.info("Running build pipeline for %s [%s]", machine_name, revision_id)
        logger.info("Config received: %s", config)
        
        champion = get_current_champion(machine_name)
        old_rev = champion.get("revision", "v0")
        old_score = champion.get("score", 0.0)
        
        parent_info = {"chain_id": chain_id, "attempt_in_chain": attempt_in_chain, "parent_revision": old_rev} if chain_id else None
        
        self._emit_event("build_started", {"machine_name": machine_name, "revision_id": revision_id, "chain_id": chain_id})
        
        rev_dir = os.path.normpath(os.path.join("outputs", "revisions", machine_name, revision_id))
        os.makedirs(rev_dir, exist_ok=True)
        
        scad_path = os.path.join(rev_dir, "model.scad")
        stl_path = os.path.join(rev_dir, "output.stl")
        
        with open(scad_path, 'w', encoding='utf-8') as sf:
            sf.write(self._generate_scad_template(config))
        self._emit_event("scad_generated", {"machine_name": machine_name, "revision_id": revision_id, "scad_path": scad_path})

        try:
            render_result = render_stl(Path(scad_path))

            stl_path = render_result["stl"]
            png_path = render_result["png"]

            self._emit_event(
                "stl_generated",
                {
                    "machine_name": machine_name,
                    "revision_id": revision_id,
                    "stl_path": stl_path,
                    "png_path": png_path,
                    "stl_url": self._make_stl_url(machine_name, revision_id),
                },
            )

        except Exception as e:
            logger.error(
                f"OpenSCAD execution failure, substituting fallback STL mesh: {e}"
            )

            self._emit_event(
                "build_failed",
                {
                    "machine_name": machine_name,
                    "revision_id": revision_id,
                    "error": str(e),
                },
            )

            with open(stl_path, "w", encoding="utf-8") as f:
                f.write("FALLBACK STL")

        # -------------------------------------------------
        # Generate BOM from detected subsystems
        # -------------------------------------------------

        bom_parts = []

        if config.get("frame"):
            bom_parts.append({
                "part": "Frame",
                "config": config["frame"],
            })

        if config.get("roller"):
            bom_parts.append({
                "part": "Roller",
                "config": config["roller"],
            })

        if config.get("hopper"):
            bom_parts.append({
                "part": "Hopper",
                "config": config["hopper"],
            })

        if config.get("spindle"):
            bom_parts.append({
                "part": "Spindle",
                "config": config["spindle"],
            })

        if config.get("drum"):
            bom_parts.append({
                "part": "Drum",
                "config": config["drum"],
            })

        if config.get("compression_rollers"):
            bom_parts.append({
                "part": "CompressionRoller",
                "config": config["compression_rollers"],
            })

        bom_data = {
            "parts": bom_parts
        }

        bom_csv = generate_bom(bom_data)

        total_mass = total_mass_from_bom_rows(bom_parts)

        logger.info(
            "Generated BOM %s (mass %.2f kg)",
            bom_csv,
            total_mass,
        )

        evaluation_result = evaluate_build(
            config,
            total_mass,
        )
        archive_revision(machine_name, revision_id, config, parent_info)
        evaluation_payload = {
            "machine_name": machine_name,
            "revision_id": revision_id,
            "evaluation": evaluation_result,
            "config": config,
            "parent_info": parent_info,
        }
        evaluation_payload.update(self._extract_evaluation_metrics(evaluation_result))
        self._emit_event("evaluation_complete", evaluation_payload)

        if evaluation_result.get("needs_improvement", False):
            self._emit_event("improvement_suggested", {
                "machine_name": machine_name,
                "root_revision": old_rev,
                "chain_id": chain_id or f"chain_{uuid.uuid4().hex[:8]}",
                "config": config,
                "evaluation_result": evaluation_result,
            })

        score = evaluation_result.get("composite", 0.0)
        is_promoted, reason = should_promote(score, old_score)
        promotion_triggered = False

        if is_promoted:
            if set_new_champion(machine_name, revision_id, score):
                try:
                    update_promotion_status(machine_name, revision_id, "champion")
                except Exception:
                    pass
                log_design_evolution(machine_name, old_rev, revision_id, old_score, score, reason)
                dispatch_cluster_alert(
                    title=f"CHAMPION PROMOTED: {machine_name}",
                    text=f"Revision [{revision_id}] outscored baseline ({old_score:.2f} -> {score:.2f}).",
                    alert_level="SUCCESS"
                )
                self._emit_event("revision_promoted", {
                    "machine_name": machine_name,
                    "revision_id": revision_id,
                    "score": score,
                    "stl_path": stl_path,
                    "stl_url": self._make_stl_url(machine_name, revision_id),
                })
                promotion_triggered = True

        return {
            "revision_id": revision_id,
            "directory": rev_dir,
            "score": score,
            "evaluation": evaluation_result,
            "promoted": promotion_triggered,
            "parent_info": parent_info,
        }















import os
import json
import uuid
import logging
import subprocess
from typing import Any, Dict, Optional
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
        return f"""\n        $fn = 100;\n        wall_thickness = {wall};\n        roller_clearance = {clearance};\n        roller_radius = {radius};\n        module roller_assembly() {{\n            difference() {{\n                cylinder(h=150, r=roller_radius + wall_thickness, center=true);\n                cylinder(h=160, r=roller_radius - roller_clearance, center=true);\n            }}\n        }}\n        roller_assembly();\n        """

    def _calculate_live_metrics(self, config: Dict[str, Any], attempt: int) -> Dict[str, Any]:
        wall = float(config.get("wall_thickness", 3.0))
        radius = float(config.get("roller_radius", 30.0))
        clearance = float(config.get("clearance", 0.5))
        stability = round(min(1.0, (wall / 6.0) * (50.0 / radius)), 2)
        material_efficiency = round(max(0.1, 1.0 - (wall / 15.0) - (radius / 150.0)), 2)
        performance = round(min(1.0, (clearance * 2.0) / (wall + 0.1)), 2)
        
        issues = []
        if stability < 0.50: issues.append("wall_thickness_insufficient")
        if material_efficiency < 0.40: issues.append("material_inefficient")
        if clearance > 3.0: issues.append("clearance_binding")
        
        composite_score = round((stability * 0.4) + (material_efficiency * 0.4) + (performance * 0.2), 2)
        return {"score": composite_score, "metrics": {"structural_stability": stability, "material_efficiency": material_efficiency, "performance_heuristics": performance}, "issues": issues}

    def run_machine_job(
        self, 
        machine_name: str, 
        config: Dict[str, Any], 
        chain_id: Optional[str] = None, 
        attempt_in_chain: int = 0
    ) -> Dict[str, Any]:
        revision_id = f"rev_{uuid.uuid4().hex[:8]}"
        logger.info(f"Starting parametric CAD compiler for job {machine_name} [{revision_id}]")
        
        champion = get_current_champion(machine_name)
        old_rev = champion.get("revision", "v0")
        old_score = champion.get("score", 0.0)
        
        parent_info = {"chain_id": chain_id, "attempt_in_chain": attempt_in_chain, "parent_revision": old_rev} if chain_id else None
            
        self.event_bus.broadcast("build_started", {"machine_name": machine_name, "revision_id": revision_id})
        rev_dir = archive_revision(machine_name, revision_id, config, parent_info)
        scad_path = os.path.join(rev_dir, "model.scad")
        stl_path = os.path.join(rev_dir, "output.stl")
        
        with open(scad_path, 'w', encoding='utf-8') as sf: sf.write(self._generate_scad_template(config))
            
        try:
            subprocess.run(["openscad", "-o", stl_path, scad_path], capture_output=True, timeout=10.0)
            self.event_bus.broadcast("stl_generated", {"machine_name": machine_name, "revision_id": revision_id})
        except Exception:
            with open(stl_path, 'w') as f: f.write("FALLBACK STL")
            
        evaluation_result = self._calculate_live_metrics(config, attempt_in_chain)
        self.event_bus.broadcast("evaluation_complete", {"machine_name": machine_name, "revision_id": revision_id, "score": evaluation_result["score"]})
        
        is_promoted, reason = should_promote(evaluation_result["score"], old_score)
        promotion_triggered = False
        
        if is_promoted:
            if set_new_champion(machine_name, rev_dir, evaluation_result["score"]):
                update_promotion_status(machine_name, revision_id, "champion")
                log_design_evolution(machine_name, old_rev, revision_id, old_score, evaluation_result["score"], reason)
                
                # Wire automated external notification triggers into successful candidate promotions
                dispatch_cluster_alert(
                    title=f"🏆 CHAMPION PROMOTED: {machine_name}",
                    text=f"Revision [{revision_id}] outscored baseline ({old_score:.2f} -> {evaluation_result['score']:.2f}). Reason: {reason}",
                    alert_level="SUCCESS"
                )
                
                self.event_bus.broadcast("revision_promoted", {"machine_name": machine_name, "revision_id": revision_id, "score": evaluation_result["score"], "reason": reason})
                promotion_triggered = True
                
        self.event_bus.broadcast("improvement_suggested", {"machine_name": machine_name, "root_revision": old_rev, "chain_id": chain_id or f"chain_{uuid.uuid4().hex[:8]}", "config": config, "evaluation_result": evaluation_result})
        return {"revision_id": revision_id, "directory": rev_dir, "score": evaluation_result["score"], "promoted": promotion_triggered}

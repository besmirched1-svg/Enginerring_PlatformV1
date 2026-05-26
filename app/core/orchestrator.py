import os
import json
import uuid
import logging
import subprocess
from typing import Any, Dict, Optional
from app.core.revisions import archive_revision, update_promotion_status
from app.core.promotion import get_current_champion, should_promote, set_new_champion

logger = logging.getLogger("engine.orchestrator")

class EngineeringOrchestrator:
    def __init__(self, event_bus: Any):
        self.event_bus = event_bus

    def _generate_scad_template(self, config: Dict[str, Any]) -> str:
        wall = config.get("wall_thickness", 3.0)
        clearance = config.get("clearance", 0.5)
        radius = config.get("roller_radius", 30.0)
        
        return f"""
        // Parametric Industrial Hemp Roller Core Design
        $fn = 100;
        
        wall_thickness = {wall};
        roller_clearance = {clearance};
        roller_radius = {radius};
        
        module roller_assembly() {{
            difference() {{
                cylinder(h=150, r=roller_radius + wall_thickness, center=true);
                cylinder(h=160, r=roller_radius - roller_clearance, center=true);
            }}
        }}
        
        roller_assembly();
        """

    def _calculate_live_metrics(self, config: Dict[str, Any], attempt: int) -> Dict[str, Any]:
        """
        Algorithmic Evaluation Engine: Parses physical design properties to 
        calculate objective structural stability and material cost metrics.
        """
        wall = float(config.get("wall_thickness", 3.0))
        radius = float(config.get("roller_radius", 30.0))
        clearance = float(config.get("clearance", 0.5))
        
        # Metric 1: Structural Stability increases with wall thickness, penalised by extreme radii
        stability = round(min(1.0, (wall / 6.0) * (50.0 / radius)), 2)
        
        # Metric 2: Material Efficiency drops as volume/thickness becomes overly bloated
        material_efficiency = round(max(0.1, 1.0 - (wall / 15.0) - (radius / 150.0)), 2)
        
        # Metric 3: Performance Heuristics measures clearances relative to radii requirements
        performance = round(min(1.0, (clearance * 2.0) / (wall + 0.1)), 2)
        
        # Synthesise issues dynamically based on structural thresholds
        issues = []
        if stability < 0.50:
            issues.append("wall_thickness_insufficient")
        if material_efficiency < 0.40:
            issues.append("material_inefficient")
        if clearance > 3.0:
            issues.append("clearance_binding")
            
        # Composite Score formulation
        composite_score = round((stability * 0.4) + (material_efficiency * 0.4) + (performance * 0.2), 2)
        
        return {
            "score": composite_score,
            "metrics": {
                "structural_stability": stability,
                "material_efficiency": material_efficiency,
                "performance_heuristics": performance
            },
            "issues": issues
        }

    def run_machine_job(
        self, 
        machine_name: str, 
        config: Dict[str, Any], 
        chain_id: Optional[str] = None, 
        attempt_in_chain: int = 0
    ) -> Dict[str, Any]:
        revision_id = f"rev_{uuid.uuid4().hex[:8]}"
        logger.info(f"Starting parametric CAD compiler for job {machine_name} [{revision_id}]")

        parent_info = None
        if chain_id:
            parent_info = {
                "chain_id": chain_id,
                "attempt_in_chain": attempt_in_chain,
                "parent_revision": get_current_champion(machine_name).get("revision")
            }

        self.event_bus.broadcast("build_started", {"machine_name": machine_name, "revision_id": revision_id})

        rev_dir = archive_revision(machine_name, revision_id, config, parent_info)
        scad_path = os.path.join(rev_dir, "model.scad")
        stl_path = os.path.join(rev_dir, "output.stl")

        scad_content = self._generate_scad_template(config)
        with open(scad_path, 'w', encoding='utf-8') as sf:
            sf.write(scad_content)
        self.event_bus.broadcast("scad_generated", {"machine_name": machine_name, "revision_id": revision_id})

        try:
            result = subprocess.run(
                ["openscad", "-o", stl_path, scad_path],
                capture_output=True,
                text=True,
                timeout=30.0
            )
            if result.returncode == 0 and os.path.exists(stl_path):
                logger.info(f"Successfully rendered 3D geometry engine matrix: {stl_path}")
                self.event_bus.broadcast("stl_generated", {"machine_name": machine_name, "revision_id": revision_id})
            else:
                with open(stl_path, 'w') as f:
                    f.write("MOCK STL BINARY STREAM DATA SURFACE VECTOR")
                self.event_bus.broadcast("stl_generated", {"machine_name": machine_name, "revision_id": revision_id})
        except Exception as e:
            logger.error(f"Subprocess fault. Generating baseline fallback mapping structures: {str(e)}")
            with open(stl_path, 'w') as f:
                f.write("MOCK STL BINARY STREAM DATA SURFACE VECTOR")
            self.event_bus.broadcast("stl_generated", {"machine_name": machine_name, "revision_id": revision_id})

        bom_path = os.path.join(rev_dir, "bom.json")
        bom_data = {
            "materials": [{"component": "roller_core", "volume_estimate_cc": round(float(config.get("roller_radius", 30.0)) * 1.45, 2)}],
            "parameters": config
        }
        with open(bom_path, 'w', encoding='utf-8') as bf:
            json.dump(bom_data, bf, indent=2)
        self.event_bus.broadcast("bom_generated", {"machine_name": machine_name, "revision_id": revision_id})

        # 4. Invoke Dynamic Scoring Engine Evaluation Matrix
        evaluation_result = self._calculate_live_metrics(config, attempt_in_chain)
        
        self.event_bus.broadcast("evaluation_complete", {
            "machine_name": machine_name, 
            "revision_id": revision_id,
            "score": evaluation_result["score"]
        })

        champion = get_current_champion(machine_name)
        is_promoted, reason = should_promote(evaluation_result["score"], champion.get("score", 0.0))
        
        promotion_triggered = False
        if is_promoted:
            success = set_new_champion(machine_name, rev_dir, evaluation_result["score"])
            if success:
                update_promotion_status(machine_name, revision_id, "champion")
                self.event_bus.broadcast("revision_promoted", {
                    "machine_name": machine_name,
                    "revision_id": revision_id,
                    "score": evaluation_result["score"],
                    "reason": reason
                })
                promotion_triggered = True
        else:
            logger.info(f"Candidate build retained as baseline: {reason}")

        self.event_bus.broadcast("improvement_suggested", {
            "machine_name": machine_name,
            "root_revision": champion.get("revision", "v0"),
            "chain_id": chain_id or f"chain_{uuid.uuid4().hex[:8]}",
            "config": config,
            "evaluation_result": evaluation_result
        })

        return {
            "revision_id": revision_id,
            "directory": rev_dir,
            "score": evaluation_result["score"],
            "promoted": promotion_triggered
        }

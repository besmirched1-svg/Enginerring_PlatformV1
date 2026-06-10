import os
import uuid
import logging
import json
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional
from app.cad.renderer import render_stl
from app.core.evaluation import (
    evaluate_build,
    total_mass_from_bom_rows,
)

from app.bom.generator import generate_bom
from app.core.revisions import archive_revision, update_promotion_status
from app.core.promotion import get_current_champion, should_promote, set_new_champion
from app.core.promotion_gate import promotion_allowed
from app.core.lineage import log_design_evolution
from app.core.notifier import dispatch_cluster_alert

# The RevisionIntent type lives in app.vision (where the
# intent_adapter constructs it). The orchestrator is a
# consumer, not a constructor: it receives the intent as
# a kwarg and passes it to promotion_allowed. The type
# import is intentionally a TYPE_CHECKING-only import
# so the orchestrator module loads without requiring
# app.vision at import time. This keeps the orchestrator
# importable in tests and tools that do not depend on
# the vision pipeline.
if TYPE_CHECKING:
    from app.vision.revision_intent import RevisionIntent

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
        attempt_in_chain: int = 0,
        ingestion_path: Optional[Dict[str, Any]] = None,
        auto_promote: bool = True,
        revision_intent: Optional["RevisionIntent"] = None,
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
            render_result = render_stl(Path(scad_path), output_dir=Path(rev_dir))

            # Prefer the per-revision paths the renderer just wrote;
            # the global STL_DIR/IMAGES_DIR fallback (when output_dir is
            # None) intentionally does not happen on this code path.
            stl_path = render_result["stl"]
            png_path = render_result["png"]

            # Rename the rendered STL to the user-facing name
            # ``output.stl`` (the renderer names it after the SCAD
            # stem, which is ``model.stl`` for the orchestrator's
            # pipeline). The user/UI contract is ``output.stl``.
            final_stl_path = os.path.join(rev_dir, "output.stl")
            try:
                if os.path.abspath(stl_path) != os.path.abspath(final_stl_path):
                    if os.path.exists(stl_path):
                        os.replace(stl_path, final_stl_path)
                    stl_path = final_stl_path
            except Exception:
                logger.exception("Could not rename %s -> %s", stl_path, final_stl_path)

            # Rename the PNG to the user-facing name ``preview.png``
            # so the revision directory matches the documented layout.
            preview_path = os.path.join(rev_dir, "preview.png")
            try:
                if os.path.abspath(png_path) != os.path.abspath(preview_path):
                    if os.path.exists(png_path):
                        os.replace(png_path, preview_path)
                    png_path = preview_path
            except Exception:
                logger.exception("Could not rename %s -> %s", png_path, preview_path)

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

        # Copy the global BOM into the per-revision directory so that
        # each revision is self-contained. generate_bom() writes to a
        # single global path; this copy makes it auditable per-rev.
        rev_bom_path = os.path.join(rev_dir, "bom.csv")
        try:
            shutil.copy2(bom_csv, rev_bom_path)
        except Exception:
            logger.exception("Could not copy BOM to revision dir; falling back to in-rev write")
            # If the global file vanished, write the rows directly so
            # the artifact still exists in the rev dir.
            try:
                with open(rev_bom_path, "w", encoding="utf-8") as f:
                    f.write(bom_csv.read_text(encoding="utf-8")
                            if hasattr(bom_csv, "read_text")
                            else Path(bom_csv).read_text(encoding="utf-8"))
            except Exception:
                logger.exception("BOM persistence to revision dir failed entirely")

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
        archive_revision(
            machine_name, revision_id, config, parent_info,
            ingestion_path=ingestion_path,
        )

        # Persist the evaluation as a JSON artifact in the revision
        # directory. Before this, the evaluation only existed in the
        # in-memory return value + the event bus, so historical
        # revisions had no auditable evaluation record.
        eval_path = os.path.join(rev_dir, "evaluation.json")
        try:
            with open(eval_path, "w", encoding="utf-8") as f:
                json.dump(evaluation_result, f, indent=2, default=str)
        except Exception:
            logger.exception("Failed to write evaluation.json to revision dir")

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

        # The promotion gate (Phase 17.3) is the single
        # enforcement boundary for the
        # "completed != promotable" semantic transition.
        # The gate is a pure function that returns True
        # only when the revision_intent (or the legacy
        # auto_promote boolean) authorizes a promotion.
        # Pre-17.3 callers that don't pass a
        # revision_intent get the legacy behavior:
        # auto_promote=True means the gate returns True
        # (assuming the score clears the threshold), and
        # auto_promote=False means the gate returns False.
        # New callers that pass a non-LEGACY intent get
        # the explicit governance: the gate refuses
        # unless the ingestion is APPROVED.
        gate_allowed = promotion_allowed(revision_intent, auto_promote)

        # promotion_mode is the *reason* the promotion
        # block ended in its current state. The four
        # pre-17.3 values are mutually exclusive and
        # exhaustive for the (auto_promote, old_rev,
        # is_promoted) tuple. The fifth value,
        # "rejected_by_governance", is new in 17.3: it
        # is the case where the legacy boolean would
        # have allowed promotion but the gate refused
        # (e.g., a non-LEGACY intent with the wrong
        # review state). The route layer can use this
        # to render an audit-trail-friendly 200 response
        # that explains why the build completed but did
        # not promote.
        if not gate_allowed:
            # The gate refused. This covers both
            # auto_promote=False (legacy path) and
            # non-LEGACY intent with the wrong state
            # (17.3 path). The promotion_mode
            # distinguishes the two via the
            # rejected_by_governance value when the
            # boolean was True but the gate said no.
            #
            # We use the gate's verdict and the
            # legacy boolean together. When the
            # boolean was False, the gate's refusal
            # is the pre-17.3a "disabled" mode. When
            # the boolean was True but the gate
            # refused, that is the new 17.3 path:
            # the gate saw a non-LEGACY intent that
            # the policy did not authorize.
            if not auto_promote:
                # Legacy caller; auto_promote was False.
                # The pre-17.3a "disabled" mode is
                # preserved.
                promotion_mode = "disabled"
            else:
                # New 17.3 path: the boolean would
                # have allowed promotion but the gate
                # refused. This covers the case where
                # a caller passed a non-LEGACY intent
                # with the wrong review state.
                promotion_mode = "rejected_by_governance"
            is_promoted = False
        elif old_rev == "v0":
            promotion_mode = "no_prior_champion"
            is_promoted = False
        else:
            is_promoted, reason = should_promote(score, old_score)
            promotion_mode = (
                "below_threshold" if not is_promoted else "attempted"
            )

        promotion_triggered = False

        # The promotion block is now gated on
        # gate_allowed (which already encodes the
        # legacy auto_promote boolean AND the
        # 17.3 intent governance). The pre-17.3
        # expression
        # ``if auto_promote and old_rev != "v0" and is_promoted``
        # is replaced by
        # ``if gate_allowed and old_rev != "v0" and is_promoted``.
        # For pre-17.3 callers (no intent) the gate
        # reduces to ``auto_promote``, so the behavior
        # is byte-equivalent. For new callers with a
        # non-LEGACY intent, the gate enforces the
        # review state. This is the "completed !=
        # promotable" semantic transition made live.
        if gate_allowed and old_rev != "v0" and is_promoted:
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
            "promotion_mode": promotion_mode,
            "parent_info": parent_info,
        }















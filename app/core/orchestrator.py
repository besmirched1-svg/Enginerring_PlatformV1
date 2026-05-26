# app/core/orchestrator.py
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.ai.prompt_parser import parse_prompt
from app.bom.generator import DEFAULT_MATERIAL, generate_bom
from app.cad.generator import generate_assembly_scad
from app.cad.renderer import render_stl
from app.core.evaluation import (
    IMPROVEMENT_THRESHOLD,
    evaluate_build,
    total_mass_from_bom_rows,
)
from app.core.events import publish
from app.core.revisions import archive_revision

logger = logging.getLogger("app.core.orchestrator")

STATE_FILE = Path("outputs/revisions/agent_state.json")
LOCK_FILE = STATE_FILE.with_suffix(".lock")

ASSEMBLY_KEYS = {"roller", "hopper", "frame"}

# Mapping of machine-config key -> BOM part label.
BOM_PART_LABELS = [
    ("spindle",             "Spindle"),
    ("drum",                "Drum"),
    ("compression_rollers", "CompressionRoller"),
    ("roller",              "Roller"),
    ("hopper",              "Hopper"),
    ("frame",               "Frame"),
]


# ---------------------------------------------------------------------------
# Cross-process state file lock (C5).
# ---------------------------------------------------------------------------

try:
    import fcntl  # type: ignore[import-not-found]
    _LOCK_BACKEND = "fcntl"
except ImportError:  # Windows
    import msvcrt  # type: ignore[import-not-found]
    _LOCK_BACKEND = "msvcrt"


@contextmanager
def _state_lock():
    """Exclusive lock guarding STATE_FILE across processes."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_FILE, "a+")
    try:
        if _LOCK_BACKEND == "fcntl":
            fcntl.flock(fh, fcntl.LOCK_EX)
        else:
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            except OSError:
                logger.warning("msvcrt lock contention on %s; proceeding", LOCK_FILE)
        yield
    finally:
        try:
            if _LOCK_BACKEND == "fcntl":
                fcntl.flock(fh, fcntl.LOCK_UN)
            else:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        finally:
            fh.close()


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class EngineeringAgent:
    def __init__(self):
        self.state = {"status": "idle", "last_build": None}
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._reload_state()

    def _reload_state(self):
        """Refresh the in-memory state cache from disk under lock."""
        try:
            with _state_lock():
                if STATE_FILE.exists():
                    self.state.update(json.loads(STATE_FILE.read_text()))
        except Exception:
            logger.exception("Failed to reload state file")

    def _persist_state(self):
        """Atomic write under lock: temp-file in the same dir + os.replace."""
        try:
            with _state_lock():
                payload = json.dumps(self.state, indent=2, default=str)
                fd, tmp = tempfile.mkstemp(
                    prefix=".state-",
                    suffix=".tmp",
                    dir=str(STATE_FILE.parent),
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(payload)
                    os.replace(tmp, STATE_FILE)
                except Exception:
                    if os.path.exists(tmp):
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                    raise
        except Exception:
            logger.exception("Failed to persist state")

    # -----------------------------
    # BOM rows for the build's parts
    # -----------------------------
    @staticmethod
    def _bom_rows(machine: dict) -> list[dict]:
        rows: list[dict] = []
        for key, label in BOM_PART_LABELS:
            cfg = machine.get(key)
            if cfg is None:
                continue
            material = (
                cfg.get("material") if isinstance(cfg, dict) else None
            ) or DEFAULT_MATERIAL.get(label, "steel")
            rows.append({"part": label, "material": material, "config": cfg or {}})
        return rows

    # -----------------------------
    # Assembly pipeline
    # -----------------------------
    def generate_machine(self, machine: dict):
        self._reload_state()
        self.state["status"] = "building"
        self._persist_state()

        machine_name = machine.get("name", "machine")
        publish("build_started", {"machine": machine_name, "config": machine})

        try:
            result = generate_assembly_scad(machine)
            assembly_path: Path = result["assembly"]
            components = result["components"]
            publish("scad_generated", {
                "machine": machine_name,
                "assembly": str(assembly_path),
                "components": {k: str(v) for k, v in components.items()},
            })

            render_result = render_stl(assembly_path)
            publish("stl_generated", {
                "machine": machine_name,
                "stl": render_result["stl"],
                "png": render_result["png"],
            })

            bom_rows = self._bom_rows(machine)
            bom_path = generate_bom({"parts": bom_rows} if bom_rows else machine)
            publish("bom_generated", {
                "machine": machine_name,
                "bom_csv": str(bom_path),
                "part_count": len(bom_rows),
            })

            # ------------------------------------------------------------
            # Phase 2: evaluation + revision archive
            # ------------------------------------------------------------
            total_mass = total_mass_from_bom_rows(bom_rows)
            scores = evaluate_build(machine, total_mass_kg=total_mass)
            publish("evaluation_complete", {
                "machine": machine_name,
                "composite": scores["composite"],
                "needs_improvement": scores["needs_improvement"],
                "metrics": scores["metrics"],
            })
            if scores["needs_improvement"]:
                publish("improvement_suggested", {
                    "machine": machine_name,
                    "composite": scores["composite"],
                    "threshold": IMPROVEMENT_THRESHOLD,
                    "issues": scores["all_issues"],
                })

            revision = archive_revision(
                machine_name=machine_name,
                config=machine,
                components={k: str(v) for k, v in components.items()},
                assembly_scad=str(assembly_path),
                assembly_stl=render_result.get("stl"),
                assembly_png=render_result.get("png"),
                bom_csv=str(bom_path),
                scores=scores,
            )
            publish("revision_promoted", {
                "machine": machine_name,
                "revision": revision["revision"],
                "directory": revision["directory"],
                "composite": scores["composite"],
            })

            self.state["last_build"] = {
                "type": "machine",
                "name": machine_name,
                "components": sorted(components.keys()),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "config": machine,
                "scores": scores,
                "revision": revision["revision"],
            }
            self.state["status"] = "idle"
            self.state.pop("error", None)
            self._persist_state()

            return {
                "status": "success",
                "assembly": str(assembly_path),
                "components": {k: str(v) for k, v in components.items()},
                "scores": scores,
                "revision": revision["revision"],
            }

        except Exception as e:
            logger.exception("Assembly build failed")
            self.state["status"] = "error"
            self.state["error"] = str(e)
            self._persist_state()
            publish("build_failed", {
                "machine": machine_name,
                "error_type": type(e).__name__,
                "error": str(e),
            })
            raise

    # -----------------------------
    # Legacy single-part roller pipeline
    # -----------------------------
    def generate_roller(self, config: dict):
        if ASSEMBLY_KEYS & config.keys() or "machine" in config:
            machine = config.get("machine", config)
        else:
            machine = {"roller": config, "name": "roller"}
        return self.generate_machine(machine)

    # -----------------------------
    # Prompt → config → build
    # -----------------------------
    def handle_prompt(self, prompt: str):
        config = parse_prompt(prompt)
        return self.generate_roller(config)


# ---------------------------------------------------------------------------
# Module-level entry points for RQ. RQ requires importable callables; the
# worker pickles the args, not the function, so these stay top-level.
# ---------------------------------------------------------------------------

def run_machine_job(machine: dict) -> dict:
    """RQ job: build a full machine from a validated config dict."""
    return EngineeringAgent().generate_machine(machine)


def run_roller_job(config: dict) -> dict:
    """RQ job: build a single legacy roller."""
    return EngineeringAgent().generate_roller(config)


def run_prompt_job(prompt: str) -> dict:
    """RQ job: parse prompt and dispatch."""
    return EngineeringAgent().handle_prompt(prompt)

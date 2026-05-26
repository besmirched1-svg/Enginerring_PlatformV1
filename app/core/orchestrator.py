# app/core/orchestrator.py
import json
from pathlib import Path
from datetime import datetime
import logging

from app.ai.prompt_parser import parse_prompt
from app.cad.generator import generate_assembly_scad, generate_roller_scad
from app.cad.renderer import render_stl
from app.bom.generator import generate_bom

logger = logging.getLogger("app.core.orchestrator")

STATE_FILE = Path("outputs/revisions/agent_state.json")

ASSEMBLY_KEYS = {"roller", "hopper", "frame"}


class EngineeringAgent:
    def __init__(self):
        self.state = {"status": "idle", "last_build": None}

        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        if STATE_FILE.exists():
            try:
                self.state.update(json.loads(STATE_FILE.read_text()))
            except Exception:
                logger.exception("Failed to load state file")

    def _persist_state(self):
        try:
            STATE_FILE.write_text(json.dumps(self.state, indent=2, default=str))
        except Exception:
            logger.exception("Failed to persist state")

    # -----------------------------
    # Assembly pipeline (machine = roller + hopper + frame)
    # -----------------------------
    def generate_machine(self, machine: dict):
        self.state["status"] = "building"
        self._persist_state()

        try:
            result = generate_assembly_scad(machine)
            assembly_path: Path = result["assembly"]
            components = result["components"]

            render_stl(assembly_path)

            # BOM aggregates materials across whatever components exist.
            bom_rows = []
            for part, cfg in (
                ("Roller", machine.get("roller")),
                ("Hopper", machine.get("hopper")),
                ("Frame", machine.get("frame")),
            ):
                if cfg:
                    bom_rows.append({"part": part, "material": cfg.get("material", "steel")})
            generate_bom({"parts": bom_rows} if bom_rows else machine)

            self.state["last_build"] = {
                "type": "machine",
                "name": machine.get("name", "machine"),
                "components": sorted(components.keys()),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "config": machine,
            }
            self.state["status"] = "idle"
            self.state.pop("error", None)
            self._persist_state()

            return {
                "status": "success",
                "assembly": str(assembly_path),
                "components": {k: str(v) for k, v in components.items()},
            }

        except Exception as e:
            logger.exception("Assembly build failed")
            self.state["status"] = "error"
            self.state["error"] = str(e)
            self._persist_state()
            raise

    # -----------------------------
    # Legacy single-part roller pipeline (kept for older callers/tests)
    # -----------------------------
    def generate_roller(self, config: dict):
        # Promote a flat roller config into an assembly with a single component.
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

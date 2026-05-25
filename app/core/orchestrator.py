# app/core/orchestrator.py
import json
from pathlib import Path
from datetime import datetime
import logging

from app.ai.prompt_parser import parse_prompt
from app.cad.generator import generate_roller_scad
from app.cad.renderer import render_stl
from app.bom.generator import generate_bom

logger = logging.getLogger("app.core.orchestrator")

STATE_FILE = Path("outputs/revisions/agent_state.json")


class EngineeringAgent:
    def __init__(self):
        self.state = {"status": "idle", "last_build": None}

        # Ensure revisions directory exists
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Load previous state if available
        if STATE_FILE.exists():
            try:
                self.state.update(json.loads(STATE_FILE.read_text()))
            except Exception:
                logger.exception("Failed to load state file")

    # -----------------------------
    # Internal: persist state to disk
    # -----------------------------
    def _persist_state(self):
        try:
            STATE_FILE.write_text(json.dumps(self.state, indent=2))
        except Exception:
            logger.exception("Failed to persist state")

    # -----------------------------
    # Main build pipeline
    # -----------------------------
    def generate_roller(self, config):
        self.state["status"] = "building"
        self._persist_state()

        try:
            # 1. Generate SCAD
            scad_path = generate_roller_scad(config)

            # 2. Render STL
            render_stl(scad_path)

            # 3. Generate BOM
            generate_bom(config)

            # 4. Update state
            self.state["last_build"] = {
                "type": "roller",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "config": config
            }
            self.state["status"] = "idle"
            self._persist_state()

            return {"status": "success", "scad": str(scad_path)}

        except Exception as e:
            logger.exception("Build failed")
            self.state["status"] = "error"
            self.state["error"] = str(e)
            self._persist_state()
            raise

    # -----------------------------
    # Prompt → config → build
    # -----------------------------
    def handle_prompt(self, prompt: str):
        config = parse_prompt(prompt)
        return self.generate_roller(config)

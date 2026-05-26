import json
import shutil
import logging
from pathlib import Path
from datetime import datetime

from app.ai.prompt_parser import parse_prompt
from app.cad.generator import generate_assembly_scad
from app.cad.renderer import render_stl
from app.bom.generator import generate_bom
from app.core.dashboard import generate_web_dashboard

logger = logging.getLogger("app.core.orchestrator")
STATE_FILE = Path("outputs/revisions/agent_state.json")

class EngineeringAgent:
    def __init__(self):
        self.state = {"status": "idle", "last_build": None}
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _persist_state(self):
        try:
            STATE_FILE.write_text(json.dumps(self.state, indent=2, default=str))
        except Exception:
            logger.exception("Failed to persist state file")

    def generate_machine(self, machine: dict):
        self.state["status"] = "building"
        self._persist_state()
        out_dir = Path("outputs")

        try:
            # 1. Generate Parametric OpenSCAD Source Files
            result = generate_assembly_scad(machine)
            assembly_path: Path = result["assembly"]
            components = result["components"]
            
            machine_id = machine.get("machine", {}).get("name", "HTDS_Machine")

            # 2. Render Main Master Assembly Visuals
            render_stl(assembly_path)
            
            # Re-route file structures to append drawing index labels safely
            shutil.move(str(out_dir / "STL/assembly.stl"), str(out_dir / f"STL/{machine_id}_assembly.stl"))
            shutil.move(str(out_dir / "IMAGES/assembly.png"), str(out_dir / f"IMAGES/{machine_id}_assembly.png"))

            # 3. Milestone 2: Loop & Compile Individual Part Subassemblies 
            for c_name, c_path in components.items():
                logger.info(f"Compiling isolated asset layer: {c_name}")
                render_stl(Path(c_path))
                # Rename to establish standard part indexes
                if (out_dir / "STL/assembly.stl").exists():
                    shutil.move(str(out_dir / "STL/assembly.stl"), str(out_dir / f"STL/{machine_id}_{c_name}.stl"))
                if (out_dir / "IMAGES/assembly.png").exists():
                    shutil.move(str(out_dir / "IMAGES/assembly.png"), str(out_dir / f"IMAGES/{machine_id}_{c_name}.png"))

            # 4. Generate Weight Cost Procurement Sheets
            generate_bom(machine, out_dir)

            # 5. Milestone 4: Refresh Live Visual Web Dashboard
            generate_web_dashboard(machine, out_dir)

            self.state["last_build"] = {
                "type": "machine",
                "name": machine_id,
                "components": sorted(components.keys()),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "config": machine,
            }
            self.state["status"] = "idle"
            self._persist_state()

            return {
                "status": "success",
                "machine_name": machine_id,
                "assembly": str(out_dir / f"STL/{machine_id}_assembly.stl")
            }

        except Exception as e:
            logger.exception("Heavy Industrial Assembly build failed")
            self.state["status"] = "error"
            self._persist_state()
            raise

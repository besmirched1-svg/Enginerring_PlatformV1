import re
import logging
from pathlib import Path
from app.core.orchestrator import EngineeringAgent

logger = logging.getLogger("app.importers.markdown_importer")
agent = EngineeringAgent()

def import_markdown(file_path: Path):
    """
    Parses GFM tables from industrial engineering specifications,
    extracts engineering revision numbers, and forces parametric heavy-mass calculations.
    """
    logger.info(f"Loading industrial specification pack: {file_path}")
    content = file_path.read_text(encoding="utf-8")
    
    # Extract structural engineering revision metadata tags
    rev_match = re.search(r'Revision:\s*([^\n\r]+)', content)
    revision_tag = rev_match.group(1).strip().replace(" ", "_") if rev_match else "REV-A"
    machine_id = f"HTDS_{revision_tag}"
    
    machine_config = {
        "machine": {"name": machine_id, "revision": revision_tag},
        "roller": {},  # Maps to Helical Spindle
        "hopper": {},  # Maps to Trommel Drum
        "frame": {}    # Maps to Skid Chassis Frame
    }
    
    sections = re.split(r'^##\s+', content, flags=re.MULTILINE)
    
    for section in sections:
        lines = section.split('\n')
        heading = lines[0].lower() if lines else ""
        
        subsystem = None
        if "spindle" in heading or "roller" in heading:
            subsystem = "roller"
        elif "drum" in heading or "trommel" in heading:
            subsystem = "hopper"
        elif "frame" in heading or "chassis" in heading:
            subsystem = "frame"
            
        if not subsystem:
            continue
            
        for line in lines:
            if '|' not in line or ':---' in line or 'Parameter' in line:
                continue
                
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if len(parts) >= 2:
                param_name = parts[0].lower().replace(" ", "_")
                raw_val = parts[1]
                
                # Coerce alphanumeric measurements out to integers
                clean_val = re.sub(r'[^\d.]', '', raw_val)
                if clean_val:
                    machine_config[subsystem][param_name] = int(float(clean_val))
                    
    logger.info(f"Successfully processed spec pack {machine_id} for orchestration loop")
    return agent.generate_machine(machine_config)

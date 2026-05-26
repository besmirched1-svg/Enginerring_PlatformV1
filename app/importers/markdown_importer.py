import re
import logging
from pathlib import Path
from app.core.orchestrator import EngineeringAgent

logger = logging.getLogger("app.importers.markdown_importer")
agent = EngineeringAgent()

def import_markdown(file_path: Path):
    """
    Parses complex GFM specification sheets. Extracts distinct data objects
    for primary spindles, drum hulls, frames, and secondary compression rollers.
    """
    logger.info(f"Loading industrial specification pack: {file_path}")
    content = file_path.read_text(encoding="utf-8")
    
    rev_match = re.search(r'Revision:\s*([^\n\r]+)', content)
    revision_tag = rev_match.group(1).strip().replace(" ", "_") if rev_match else "REV-B"
    machine_id = f"HTDS_{revision_tag}"
    
    # Isolate components into individual parameter blocks
    machine_config = {
        "machine": {"name": machine_id, "revision": revision_tag},
        "roller": {},              # Primary Spindle
        "hopper": {},              # Trommel Drum
        "frame": {},               # Base Chassis
        "compression_rollers": {}  # Secondary Roller Subsystem
    }
    
    sections = re.split(r'^##\s+', content, flags=re.MULTILINE)
    
    for section in sections:
        lines = section.split('\n')
        heading = lines[0].lower() if lines else ""
        
        subsystem = None
        if "helical spindle" in heading:
            subsystem = "roller"
        elif "drum" in heading or "trommel" in heading:
            subsystem = "hopper"
        elif "frame" in heading or "chassis" in heading:
            subsystem = "frame"
        elif "compression roller" in heading:
            subsystem = "compression_rollers"
            
        if not subsystem:
            continue
            
        for line in lines:
            if '|' not in line or ':---' in line or 'Parameter' in line:
                continue
                
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if len(parts) >= 2:
                param_name = parts[0].lower().replace(" ", "_")
                raw_val = parts[1]
                
                clean_val = re.sub(r'[^\d.]', '', raw_val)
                if clean_val:
                    machine_config[subsystem][param_name] = int(float(clean_val))
                    
    logger.info(f"Successfully processed spec pack {machine_id} for orchestration loop")
    return agent.generate_machine(machine_config)

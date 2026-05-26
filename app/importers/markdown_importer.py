import re
import logging
from pathlib import Path
from app.core.orchestrator import EngineeringAgent

logger = logging.getLogger("app.importers.markdown_importer")
agent = EngineeringAgent()

def import_markdown(file_path: Path):
    """
    Parses GitHub Flavored Markdown (GFM) tables from engineering packs
    and maps them to the multi-part machine assembly loop.
    """
    logger.info(f"Loading Markdown specification: {file_path}")
    content = file_path.read_text(encoding="utf-8")
    
    machine_config = {
        "machine": {"name": file_path.stem},
        "roller": {},
        "hopper": {},
        "frame": {}
    }
    
    # Split text blocks by markdown H2 sections to isolate component sheets
    sections = re.split(r'^##\s+', content, flags=re.MULTILINE)
    
    for section in sections:
        lines = section.split('\n')
        heading = lines[0].lower() if lines else ""
        
        # Determine target subsystem context
        subsystem = None
        if "spindle" in heading or "roller" in heading:
            subsystem = "roller"
        elif "drum" in heading or "trommel" in heading:
            subsystem = "hopper"  # Maps parameters to secondary subassembly slot
        elif "frame" in heading or "chassis" in heading:
            subsystem = "frame"
            
        if not subsystem:
            continue
            
        # Extract parameter rows from standard pipe-line table strings
        for line in lines:
            if '|' not in line or ':---' in line or 'Parameter' in line:
                continue
                
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if len(parts) >= 2:
                param_name = parts[0].lower().replace(" ", "_")
                raw_val = parts[1]
                
                # Coerce alphanumeric engineering text strings into clean integers
                clean_val = re.sub(r'[^\d.]', '', raw_val)
                if clean_val:
                    machine_config[subsystem][param_name] = int(float(clean_val))
                    
    logger.info(f"Parsed markdown spec with systems: {[k for k, v in machine_config.items() if v]}")
    return agent.generate_machine(machine_config)

import os
import shutil
import logging
from pathlib import Path
from app.core.orchestrator import EngineeringAgent
from app.importers.yaml_importer import import_yaml

logger = logging.getLogger("app.workspace.ingestion")
agent = EngineeringAgent()

def ingest_file(file_path: Path):
    logger.info(f"Ingesting file: {file_path}")
    ext = file_path.suffix.lower()
    
    processing_dir = Path("workspace/processing")
    processing_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        if ext in ['.yaml', '.yml']:
            import_yaml(file_path)
        elif ext == '.md':
            from app.importers.markdown_importer import import_markdown
            import_markdown(file_path)
        elif ext == '.dxf':
            # ─── ROUTE DXF EXTENSIONS HERE ────────────────────────
            from app.importers.dxf_importer import import_dxf
            import_dxf(file_path)
        else:
            logger.warning(f"Unsupported file type: {ext}")
            
    except Exception as e:
        logger.error(f"Ingestion pipeline failed for {file_path.name}: {str(e)}", exc_info=True)
        
    processing_path = processing_dir / file_path.name
    if processing_path.exists():
        os.remove(processing_path)
    shutil.move(str(file_path), str(processing_dir))
    logger.info(f"Moved to processing: {file_path.name}")

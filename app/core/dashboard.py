import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("app.core.dashboard")

def generate_web_dashboard(machine_config: dict, output_dir: Path):
    """
    Generates a localized engineering control dashboard page for live asset reviews.
    """
    html_path = output_dir / "index.html"
    machine_info = machine_config.get("machine", {})
    m_name = machine_info.get("name", "HTDS_Machine")
    m_rev = machine_info.get("revision", "REV-A")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>HTDS Command Console</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; background: #1a1a24; color: #e1e1e6; display: flex; height: 100vh; }}
        .sidebar {{ width: 350px; background: #111116; padding: 25px; box-shadow: 2px 0 10px rgba(0,0,0,0.5); }}
        .main {{ flex: 1; padding: 30px; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
        h1, h2 {{ color: #47a0ff; border-bottom: 1px solid #2d2d3d; padding-bottom: 8px; }}
        .metric {{ background: #22222e; padding: 12px; margin: 10px 0; border-radius: 6px; font-size: 14px; border-left: 4px solid #47a0ff; }}
        img {{ max-width: 85%; max-height: 65vh; border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.7); background: #0b0b0f; }}
        .btn {{ display: inline-block; background: #007acc; color: white; padding: 10px 18px; margin: 10px 5px 0 0; text-decoration: none; border-radius: 4px; font-weight: bold; }}
        .btn:hover {{ background: #0098ff; }}
    </style>
</head>
<body>
    <div class="sidebar">
        <h1>HTDS Platform</h1>
        <h2>System Telemetry</h2>
        <div class="metric"><strong>Assembly ID:</strong> {m_name}</div>
        <div class="metric"><strong>Drawing Index:</strong> {m_rev}</div>
        <div class="metric"><strong>Build Timestamp:</strong> {timestamp}</div>
        <h2>Manufacturing Assets</h2>
        <a class="btn" href="STL/{m_name}_assembly.stl" download>Download 3D STL</a>
        <a class="btn" href="BOM/{m_name}_bom.csv" download>Procurement BOM</a>
    </div>
    <div class="main">
        <img src="IMAGES/{m_name}_assembly.png" alt="3D Assembly Render Panel">
    </div>
</body>
</html>
"""
    html_path.write_text(html_content, encoding="utf-8")
    logger.info(f"Live HTML control dashboard generated successfully at: {html_path}")

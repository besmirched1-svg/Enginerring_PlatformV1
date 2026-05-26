import os
import csv
from pathlib import Path
import logging

logger = logging.getLogger("app.bom.generator")

MATERIAL_COSTS = {
    "stainless_316": 12.50,
    "stainless_304": 9.50,
    "aluminum_6061": 8.00,
    "mild_steel": 4.50,
    "steel": 4.50,
    "default": 5.00
}

def generate_bom(bom_data: dict) -> Path:
    bom_dir = Path("outputs/BOM")
    bom_dir.mkdir(parents=True, exist_ok=True)
    csv_path = bom_dir / "assembly_bom.csv"
    
    logger.info("Generating manufacturing Bill of Materials spreadsheet...")
    
    parts_list = bom_data.get("parts", [])
    csv_rows = []
    total_weight_kg = 0.0
    total_cost_aud = 0.0
    
    for item in parts_list:
        part_name = item.get("part", "Unknown Component")
        material = item.get("material", "steel").lower()
        
        if part_name == "Roller":
            weight_kg = 45.2
        elif part_name == "Hopper":
            weight_kg = 18.5
        elif part_name == "Frame":
            weight_kg = 32.0
        else:
            weight_kg = 10.0
            
        cost = weight_kg * MATERIAL_COSTS.get(material, MATERIAL_COSTS["default"])
        
        csv_rows.append([part_name, material, f"{weight_kg:.2f}", f"${cost:.2f}"])
        total_weight_kg += weight_kg
        total_cost_aud += cost

    try:
        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Component Name", "Material Spec", "Est. Weight (kg)", "Est. Cost (AUD)"])
            writer.writerows(csv_rows)
            writer.writerow([])
            writer.writerow(["TOTAL INDUSTRIAL ASSY METRICS", "", f"{total_weight_kg:.2f}", f"${total_cost_aud:.2f}"])
            
        logger.info(f"BOM spreadsheet successfully saved to: {csv_path}")
    except Exception:
        logger.exception("Failed to write BOM CSV spreadsheet file")
        
    return csv_path

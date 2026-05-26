# app/importers/yaml_importer.py

from pathlib import Path
import yaml
import logging

from app.core.orchestrator import EngineeringAgent

logger = logging.getLogger("app.importers.yaml_importer")

agent = EngineeringAgent()

ASSEMBLY_KEYS = {"roller", "hopper", "frame"}


def _normalize(data: dict) -> dict:
    """
    Translate a parsed YAML payload into a canonical machine config:

        {
            "name": "...",
            "roller": {...} | None,
            "hopper": {...} | None,
            "frame":  {...} | None,
        }

    Three input shapes are accepted:
      1. Wrapped:        { machine: { name, roller, hopper, frame } }
      2. Nested at root: { roller: {...}, hopper: {...}, frame: {...} }
      3. Flat (legacy):  { diameter, width, shaft, material } -> roller only
    """
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping, got {type(data).__name__}")

    if "machine" in data and isinstance(data["machine"], dict):
        machine = dict(data["machine"])
    elif ASSEMBLY_KEYS & data.keys():
        machine = {k: data[k] for k in ASSEMBLY_KEYS if k in data}
        if "name" in data:
            machine["name"] = data["name"]
    else:
        # Legacy flat roller schema.
        machine = {"roller": data}

    machine.setdefault("name", "machine")
    for key in ASSEMBLY_KEYS:
        machine.setdefault(key, None)
    return machine


def import_yaml(file_path: Path):
    logger.info(f"Loading YAML: {file_path}")

    with open(file_path, "r") as f:
        data = yaml.safe_load(f)

    logger.info(f"Parsed YAML: {data}")

    machine = _normalize(data or {})
    logger.info(
        "Normalized machine '%s' (components: %s)",
        machine.get("name"),
        [k for k in ASSEMBLY_KEYS if machine.get(k)],
    )

    result = agent.generate_machine(machine)
    logger.info(f"Build result: {result}")

    return result

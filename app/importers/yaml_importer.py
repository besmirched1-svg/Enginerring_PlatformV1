# app/importers/yaml_importer.py
from __future__ import annotations
import logging
from pathlib import Path
import yaml
from pydantic import ValidationError
from app.core.schemas import MachineConfig

logger = logging.getLogger("engine.importers.yaml_importer")

ASSEMBLY_KEYS = {"roller", "hopper", "frame"}
INDUSTRIAL_KEYS = {"spindle", "drum", "compression_rollers"}


class InvalidMachineConfigError(ValueError):
    """Raised when a parsed YAML payload fails schema validation."""


def _normalize(data: dict) -> dict:
    """
    Translate a parsed YAML payload into the canonical machine config shape.

    Accepted input shapes:
      1. Wrapped:        { machine: { name, ... } }
      2. Nested at root: { roller: {...}, hopper: {...}, frame: {...} }
                         or { spindle: {...}, drum: {...}, frame: {...} }
      3. Flat (legacy):  { diameter, width, shaft, material } -> single roller
    """
    if not isinstance(data, dict):
        raise InvalidMachineConfigError(
            f"YAML root must be a mapping, got {type(data).__name__}"
        )

    valid_subsystem_keys = ASSEMBLY_KEYS | INDUSTRIAL_KEYS

    if "machine" in data and isinstance(data["machine"], dict):
        machine = dict(data["machine"])
    elif valid_subsystem_keys & data.keys():
        machine = {k: data[k] for k in valid_subsystem_keys if k in data}
        if "name" in data:
            machine["name"] = data["name"]
    else:
        machine = {"roller": data}

    machine.setdefault("name", "machine")
    return machine


def _validate(machine: dict) -> dict:
    """Run the parsed machine dict through Pydantic. Raises on failure."""
    try:
        validated = MachineConfig.from_normalized_dict(machine)
    except ValidationError as e:
        raise InvalidMachineConfigError(str(e)) from e
    return validated.model_dump(exclude_none=True)


def import_yaml(file_path: Path):
    """
    Parse, normalize, validate, then dispatch the build.
    Raises InvalidMachineConfigError on malformed payloads so the ingestion
    layer can quarantine the file in workspace/failed/.
    """
    # Lazy import avoids module-level side-effects (Redis connection, file I/O)
    from app.core.orchestrator import EngineeringOrchestrator
    from app.core.events import get_event_bus

    logger.info("Loading YAML: %s", file_path)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise InvalidMachineConfigError(f"Malformed YAML: {e}") from e

    logger.info("Parsed YAML: %s", data)

    machine = _normalize(data or {})
    logger.info(
        "Normalized machine '%s' (subsystems: %s)",
        machine.get("name"),
        sorted(k for k in (ASSEMBLY_KEYS | INDUSTRIAL_KEYS) if machine.get(k)),
    )

    machine = _validate(machine)

    agent = EngineeringOrchestrator(event_bus=get_event_bus())
    result = agent.run_machine_job(machine.get("name", "machine"), machine)
    logger.info("Build result: %s", result)
    return result

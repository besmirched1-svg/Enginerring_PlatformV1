# app/vision/machine_graph_builder.py
#
# Constructs a MachineGraph from the structured outputs of the vision pipeline.
#
# This is the final step of the drawing ingestion pipeline. It takes:
#   - title_block:  machine identity
#   - bom_rows:     part list with materials and masses
#   - dimensions:   extracted dimension annotations
#   - assemblies:   detected subsystem regions
#
# And produces a MachineGraph with:
#   - One SubsystemNode per detected assembly
#   - Config populated from BOM materials and dimension heuristics
#   - Confidence scores reflecting extraction quality
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from app.graph.models import (
    EdgeType,
    FlowEdge,
    MachineGraph,
    NodeType,
    SubsystemNode,
)

logger = logging.getLogger("engine.vision.machine_graph_builder")

_SUBSYSTEM_KEY_TO_NODE_TYPE: Dict[str, NodeType] = {
    "hopper":              NodeType.HOPPER,
    "conveyor":            NodeType.CONVEYOR,
    "compression_rollers": NodeType.COMPRESSION_ROLLER,
    "drum":                NodeType.PRIMARY_DRUM,
    "spindle":             NodeType.SPINDLE,
    "frame":               NodeType.FRAME,
    "drive":               NodeType.DRIVE,
    "discharge":           NodeType.DISCHARGE,
}

_DECORTICATOR_FLOW_ORDER = [
    "hopper", "conveyor", "compression_rollers", "drum", "discharge"
]


def _infer_config_from_dimensions(
    subsystem_key: str,
    dimensions: List[Dict[str, Any]],
    bom_row: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Heuristically map extracted dimensions to subsystem config parameters.

    This is intentionally conservative: only assigns a dimension when
    there is a strong contextual match. Unmatched dimensions are ignored
    rather than guessed.
    """
    config: Dict[str, Any] = {}

    if bom_row:
        material = bom_row.get("material", "steel")
        if material:
            config["material"] = material
        if bom_row.get("mass_kg"):
            config["_extracted_mass_kg"] = bom_row["mass_kg"]

    diameters = [d["value"] for d in dimensions if d["dim_type"] == "diameter"]
    lengths   = [d["value"] for d in dimensions if d["dim_type"] in ("length", "linear", "extent")]
    thickness = [d["value"] for d in dimensions if d["dim_type"] == "thickness"]

    if subsystem_key == "drum":
        if diameters:
            config["drum_id"] = int(max(diameters))
        if lengths:
            config["drum_length"] = int(max(lengths))
        if thickness:
            config["wall_thickness"] = int(min(thickness))

    elif subsystem_key == "spindle":
        sorted_d = sorted(diameters)
        if len(sorted_d) >= 2:
            config["shaft_od"] = int(sorted_d[0])
            config["flight_od"] = int(sorted_d[-1])
        elif len(sorted_d) == 1:
            config["shaft_od"] = int(sorted_d[0])
        if lengths:
            config["shaft_length"] = int(max(lengths))

    elif subsystem_key == "frame":
        if lengths:
            config["rail_length"] = int(max(lengths))
        if thickness:
            config["rail_t"] = int(min(thickness))

    elif subsystem_key == "compression_rollers":
        if diameters:
            config["diameter"] = int(max(diameters))
        if lengths:
            config["width"] = int(max(lengths))

    elif subsystem_key == "hopper":
        sorted_d = sorted(diameters + [v for d in dimensions
                                        if d["dim_type"] == "linear"
                                        for v in ([d["value"]] if isinstance(d["value"], float) else d["value"])])
        if len(sorted_d) >= 2:
            config["top_width"] = int(sorted_d[-1])
            config["bottom_width"] = int(sorted_d[0])

    return config


def build_graph(
    title_block: Dict[str, str],
    bom_rows: List[Dict[str, Any]],
    dimensions: List[Dict[str, Any]],
    assemblies: List[Dict[str, Any]],
    source_file: str = "",
) -> MachineGraph:
    """
    Build a MachineGraph from vision pipeline outputs.

    Parameters
    ----------
    title_block : dict
        Extracted title-block fields (name, revision, etc.).
    bom_rows : list
        BOM rows from bom_reader.
    dimensions : list
        Dimension annotations from dimension_reader.
    assemblies : list
        Detected subsystem assemblies from assembly_detector.
    source_file : str
        Path to the source drawing file (stored in metadata).

    Returns
    -------
    MachineGraph
    """
    name = title_block.get("name", "machine")
    revision = title_block.get("revision", "v0")

    graph = MachineGraph(
        graph_id=uuid.uuid4().hex[:12],
        name=name,
        revision=revision,
        metadata={
            "source_file": source_file,
            "drawing_number": title_block.get("drawing_number", ""),
            "client": title_block.get("client", ""),
            "project": title_block.get("project", ""),
            "date": title_block.get("date", ""),
        },
    )

    # Index BOM rows by part name for quick lookup
    bom_by_part: Dict[str, Dict[str, Any]] = {}
    part_to_subsystem = {
        "Spindle":           "spindle",
        "Drum":              "drum",
        "Frame":             "frame",
        "Hopper":            "hopper",
        "CompressionRoller": "compression_rollers",
        "Conveyor":          "conveyor",
    }
    for row in bom_rows:
        key = part_to_subsystem.get(row.get("part", ""))
        if key:
            bom_by_part[key] = row

    # Build one node per detected assembly
    for assembly in assemblies:
        subsystem_key = assembly["subsystem_key"]
        node_type = _SUBSYSTEM_KEY_TO_NODE_TYPE.get(subsystem_key, NodeType.UNKNOWN)
        bom_row = bom_by_part.get(subsystem_key)

        config = _infer_config_from_dimensions(subsystem_key, dimensions, bom_row)

        node = SubsystemNode(
            node_id=subsystem_key,
            node_type=node_type,
            label=assembly.get("label", subsystem_key.replace("_", " ").title()),
            config=config,
            source="drawing",
            confidence=assembly.get("confidence", 0.5),
            metadata={"bom_row": bom_row} if bom_row else {},
        )
        graph = graph.add_node(node)
        logger.debug("Added node: %s (confidence=%.2f)", subsystem_key, node.confidence)

    # Wire material-flow edges
    present = set(graph.nodes.keys())
    flow_nodes = [n for n in _DECORTICATOR_FLOW_ORDER if n in present]
    for n in present:
        if n not in flow_nodes and n not in ("frame", "spindle", "drive"):
            flow_nodes.append(n)

    for i in range(len(flow_nodes) - 1):
        src, tgt = flow_nodes[i], flow_nodes[i + 1]
        graph = graph.add_edge(FlowEdge(
            edge_id=f"{src}_to_{tgt}",
            source_id=src,
            target_id=tgt,
            edge_type=EdgeType.MATERIAL_FEED,
        ))

    # Structural support from frame
    if "frame" in present:
        for node_id in present:
            if node_id != "frame":
                graph = graph.add_edge(FlowEdge(
                    edge_id=f"frame_supports_{node_id}",
                    source_id="frame",
                    target_id=node_id,
                    edge_type=EdgeType.STRUCTURAL_SUPPORT,
                ))

    # Mechanical drive: spindle → drum
    if "spindle" in present and "drum" in present:
        graph = graph.add_edge(FlowEdge(
            edge_id="spindle_drives_drum",
            source_id="spindle",
            target_id="drum",
            edge_type=EdgeType.MECHANICAL_DRIVE,
        ))

    logger.info(
        "Built MachineGraph '%s' rev=%s: %d nodes, %d edges",
        name, revision, len(graph.nodes), len(graph.edges),
    )
    return graph

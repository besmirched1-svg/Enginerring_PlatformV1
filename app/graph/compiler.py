# app/graph/compiler.py
#
# Bidirectional compiler: MachineGraph <-> YAML/dict
#
# to_yaml_dict(graph)  — graph → platform YAML config dict
# from_yaml_dict(data) — platform YAML config dict → graph
# from_machine_config(config) — MachineConfig Pydantic model → graph
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from app.graph.models import (
    EdgeType,
    FlowEdge,
    MachineGraph,
    NodeType,
    SubsystemNode,
)

logger = logging.getLogger("engine.graph.compiler")

# Maps YAML subsystem keys to canonical NodeTypes and their default
# material-flow order in a decorticator.
_YAML_KEY_TO_NODE_TYPE: Dict[str, NodeType] = {
    "hopper":              NodeType.HOPPER,
    "conveyor":            NodeType.CONVEYOR,
    "roller":              NodeType.ROLLER,
    "compression_rollers": NodeType.COMPRESSION_ROLLER,
    "drum":                NodeType.PRIMARY_DRUM,
    "spindle":             NodeType.SPINDLE,
    "frame":               NodeType.FRAME,
    "drive":               NodeType.DRIVE,
    "discharge":           NodeType.DISCHARGE,
}

# Default material-flow order for decorticator-style machines.
# Nodes not in this list are appended in YAML key order.
_DECORTICATOR_FLOW_ORDER = [
    "hopper",
    "conveyor",
    "compression_rollers",
    "drum",
    "discharge",
]


def from_yaml_dict(data: Dict[str, Any], source: str = "yaml") -> MachineGraph:
    """
    Convert a platform YAML config dict into a MachineGraph.

    Accepts both the flat subsystem format and the wrapped { machine: {...} }
    format produced by the YAML importer.
    """
    if "machine" in data and isinstance(data["machine"], dict):
        data = data["machine"]

    name = data.get("name", "machine")
    revision = data.get("revision", "v0")

    graph = MachineGraph(
        graph_id=uuid.uuid4().hex[:12],
        name=name,
        revision=revision,
        metadata={"source": source},
    )

    # Build nodes for every recognised subsystem key present in the config.
    node_order = []
    for yaml_key, node_type in _YAML_KEY_TO_NODE_TYPE.items():
        cfg = data.get(yaml_key)
        if cfg is None:
            continue
        node_id = yaml_key
        node = SubsystemNode(
            node_id=node_id,
            node_type=node_type,
            label=yaml_key.replace("_", " ").title(),
            config=cfg if isinstance(cfg, dict) else {},
            source=source,
            confidence=1.0,
        )
        graph = graph.add_node(node)
        node_order.append(node_id)

    # Wire material-flow edges in decorticator order.
    flow_nodes = [n for n in _DECORTICATOR_FLOW_ORDER if n in node_order]
    # Append any nodes not in the default order
    for n in node_order:
        if n not in flow_nodes and n != "frame" and n != "spindle" and n != "drive":
            flow_nodes.append(n)

    for i in range(len(flow_nodes) - 1):
        src, tgt = flow_nodes[i], flow_nodes[i + 1]
        edge = FlowEdge(
            edge_id=f"{src}_to_{tgt}",
            source_id=src,
            target_id=tgt,
            edge_type=EdgeType.MATERIAL_FEED,
        )
        graph = graph.add_edge(edge)

    # Structural support: frame supports everything
    if "frame" in node_order:
        for node_id in node_order:
            if node_id != "frame":
                graph = graph.add_edge(FlowEdge(
                    edge_id=f"frame_supports_{node_id}",
                    source_id="frame",
                    target_id=node_id,
                    edge_type=EdgeType.STRUCTURAL_SUPPORT,
                ))

    # Mechanical drive: spindle drives drum
    if "spindle" in node_order and "drum" in node_order:
        graph = graph.add_edge(FlowEdge(
            edge_id="spindle_drives_drum",
            source_id="spindle",
            target_id="drum",
            edge_type=EdgeType.MECHANICAL_DRIVE,
        ))

    logger.info(
        "Compiled MachineGraph '%s' from YAML: %d nodes, %d edges",
        name, len(graph.nodes), len(graph.edges),
    )
    return graph


def to_yaml_dict(graph: MachineGraph) -> Dict[str, Any]:
    """
    Convert a MachineGraph back into a platform YAML config dict.

    Only MATERIAL_FEED and MECHANICAL_DRIVE nodes are emitted as subsystem
    configs; STRUCTURAL_SUPPORT edges are implicit in the frame node.
    """
    result: Dict[str, Any] = {"name": graph.name}
    if graph.revision and graph.revision != "v0":
        result["revision"] = graph.revision

    # Reverse lookup: NodeType -> YAML key
    node_type_to_yaml = {v: k for k, v in _YAML_KEY_TO_NODE_TYPE.items()}

    for node in graph.material_flow_path():
        yaml_key = node_type_to_yaml.get(node.node_type, node.node_id)
        if node.config:
            result[yaml_key] = dict(node.config)

    logger.info("Compiled YAML dict from MachineGraph '%s'", graph.name)
    return result


def from_machine_config(config: Any) -> MachineGraph:
    """
    Convert a MachineConfig Pydantic model (or plain dict) into a MachineGraph.
    Accepts both model instances and raw dicts.
    """
    if hasattr(config, "model_dump"):
        data = config.model_dump(exclude_none=True)
    elif hasattr(config, "dict"):
        data = config.dict(exclude_none=True)
    elif isinstance(config, dict):
        data = config
    else:
        raise TypeError(f"Cannot convert {type(config)} to MachineGraph")

    return from_yaml_dict(data, source="pydantic")

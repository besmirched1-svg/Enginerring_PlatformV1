# app/graph/models.py
#
# Machine Graph — the universal internal representation of any machine.
#
# Every subsystem is a Node. Material/energy flows between nodes are Edges.
# The graph is the single source of truth that everything else compiles
# into and out of:
#
#   Drawing / YAML / Prompt
#         ↓
#     MachineGraph
#         ↓
#   YAML / CAD / BOM / Evaluation / Simulation
#
# Design principles:
#   - Immutable after construction (use .evolve() to produce variants)
#   - Serialisable to/from plain dicts (JSON/YAML safe)
#   - No circular imports — this module has zero app-internal dependencies
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class NodeType(str, Enum):
    """Canonical subsystem types understood by the platform."""
    HOPPER = "hopper"
    CONVEYOR = "conveyor"
    COMPRESSION_ROLLER = "compression_roller"
    PRIMARY_DRUM = "primary_drum"
    CLEANING_DRUM = "cleaning_drum"
    SPINDLE = "spindle"
    FRAME = "frame"
    ROLLER = "roller"
    DRIVE = "drive"
    DISCHARGE = "discharge"
    UNKNOWN = "unknown"


class EdgeType(str, Enum):
    """Types of flow between subsystems."""
    MATERIAL_FEED = "material_feed"       # physical material passes through
    MECHANICAL_DRIVE = "mechanical_drive" # torque / power transmission
    STRUCTURAL_SUPPORT = "structural_support"
    CONTROL_SIGNAL = "control_signal"


@dataclass
class SubsystemNode:
    """
    A single machine subsystem.

    Parameters
    ----------
    node_id:    Stable identifier (slug, e.g. "primary_drum").
    node_type:  Canonical type from NodeType enum.
    label:      Human-readable name from the drawing title block.
    config:     Raw parameter dict (dimensions, material, tolerances).
    source:     Where this node came from: "drawing", "yaml", "inferred".
    confidence: 0.0–1.0 extraction confidence (1.0 for hand-authored YAML).
    metadata:   Arbitrary extra data (drawing ref, BOM line, notes).
    """
    node_id: str
    node_type: NodeType
    label: str
    config: Dict[str, Any] = field(default_factory=dict)
    source: str = "yaml"
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "label": self.label,
            "config": self.config,
            "source": self.source,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SubsystemNode":
        d = dict(d)
        d["node_type"] = NodeType(d.get("node_type", "unknown"))
        return cls(**d)


@dataclass
class FlowEdge:
    """
    A directed flow between two subsystem nodes.

    Parameters
    ----------
    edge_id:    Stable identifier.
    source_id:  node_id of the upstream subsystem.
    target_id:  node_id of the downstream subsystem.
    edge_type:  Nature of the flow.
    properties: Quantitative flow properties (e.g. feed_rate_kg_hr).
    """
    edge_id: str
    source_id: str
    target_id: str
    edge_type: EdgeType = EdgeType.MATERIAL_FEED
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type.value,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FlowEdge":
        d = dict(d)
        d["edge_type"] = EdgeType(d.get("edge_type", "material_feed"))
        return cls(**d)


@dataclass
class MachineGraph:
    """
    Complete machine representation as a directed graph.

    Attributes
    ----------
    graph_id:   Unique identifier for this graph instance.
    name:       Machine name (from drawing title block or YAML).
    revision:   Drawing revision string (e.g. "REV-A").
    nodes:      Dict of node_id -> SubsystemNode.
    edges:      List of FlowEdge.
    metadata:   Top-level machine metadata (project, client, date, etc.).
    """
    graph_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = "machine"
    revision: str = "v0"
    nodes: Dict[str, SubsystemNode] = field(default_factory=dict)
    edges: List[FlowEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Mutation helpers (return new instances — graph is logically immutable)
    # ------------------------------------------------------------------

    def add_node(self, node: SubsystemNode) -> "MachineGraph":
        """Return a new graph with the node added."""
        new_nodes = dict(self.nodes)
        new_nodes[node.node_id] = node
        return MachineGraph(
            graph_id=self.graph_id,
            name=self.name,
            revision=self.revision,
            nodes=new_nodes,
            edges=list(self.edges),
            metadata=dict(self.metadata),
        )

    def add_edge(self, edge: FlowEdge) -> "MachineGraph":
        """Return a new graph with the edge added."""
        return MachineGraph(
            graph_id=self.graph_id,
            name=self.name,
            revision=self.revision,
            nodes=dict(self.nodes),
            edges=list(self.edges) + [edge],
            metadata=dict(self.metadata),
        )

    def get_node(self, node_id: str) -> Optional[SubsystemNode]:
        return self.nodes.get(node_id)

    def downstream(self, node_id: str) -> List[SubsystemNode]:
        """Return all nodes directly downstream of node_id."""
        target_ids = [e.target_id for e in self.edges if e.source_id == node_id]
        return [self.nodes[t] for t in target_ids if t in self.nodes]

    def upstream(self, node_id: str) -> List[SubsystemNode]:
        """Return all nodes directly upstream of node_id."""
        source_ids = [e.source_id for e in self.edges if e.target_id == node_id]
        return [self.nodes[s] for s in source_ids if s in self.nodes]

    def material_flow_path(self) -> List[SubsystemNode]:
        """
        Return nodes in material-flow order (topological sort on MATERIAL_FEED
        edges). Falls back to insertion order if the graph has cycles.
        """
        material_edges = [e for e in self.edges if e.edge_type == EdgeType.MATERIAL_FEED]
        has_incoming = {e.target_id for e in material_edges}
        roots = [n for n in self.nodes.values() if n.node_id not in has_incoming]

        visited: List[SubsystemNode] = []
        seen: set = set()

        def _visit(node: SubsystemNode):
            if node.node_id in seen:
                return
            seen.add(node.node_id)
            visited.append(node)
            for child in self.downstream(node.node_id):
                _visit(child)

        for root in roots:
            _visit(root)

        # Append any disconnected nodes
        for node in self.nodes.values():
            if node.node_id not in seen:
                visited.append(node)

        return visited

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "name": self.name,
            "revision": self.revision,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MachineGraph":
        nodes = {k: SubsystemNode.from_dict(v) for k, v in d.get("nodes", {}).items()}
        edges = [FlowEdge.from_dict(e) for e in d.get("edges", [])]
        return cls(
            graph_id=d.get("graph_id", uuid.uuid4().hex[:12]),
            name=d.get("name", "machine"),
            revision=d.get("revision", "v0"),
            nodes=nodes,
            edges=edges,
            metadata=d.get("metadata", {}),
        )

"""Tests for app/graph/ — MachineGraph models and compiler."""
import pytest
from app.graph.models import (
    MachineGraph, SubsystemNode, FlowEdge, NodeType, EdgeType
)
from app.graph.compiler import from_yaml_dict, to_yaml_dict, from_machine_config


class TestSubsystemNode:
    def test_to_dict_roundtrip(self):
        node = SubsystemNode(
            node_id="drum", node_type=NodeType.PRIMARY_DRUM,
            label="Trommel Drum", config={"drum_id": 1500},
        )
        d = node.to_dict()
        restored = SubsystemNode.from_dict(d)
        assert restored.node_id == "drum"
        assert restored.node_type == NodeType.PRIMARY_DRUM
        assert restored.config["drum_id"] == 1500

    def test_confidence_defaults_to_one(self):
        node = SubsystemNode(node_id="x", node_type=NodeType.UNKNOWN, label="X")
        assert node.confidence == 1.0


class TestFlowEdge:
    def test_to_dict_roundtrip(self):
        edge = FlowEdge(
            edge_id="a_to_b", source_id="a", target_id="b",
            edge_type=EdgeType.MATERIAL_FEED,
        )
        d = edge.to_dict()
        restored = FlowEdge.from_dict(d)
        assert restored.source_id == "a"
        assert restored.edge_type == EdgeType.MATERIAL_FEED


class TestMachineGraph:
    def _make_graph(self):
        g = MachineGraph(name="test", revision="REV-A")
        n1 = SubsystemNode("hopper", NodeType.HOPPER, "Hopper")
        n2 = SubsystemNode("drum", NodeType.PRIMARY_DRUM, "Drum")
        e = FlowEdge("hopper_to_drum", "hopper", "drum", EdgeType.MATERIAL_FEED)
        return g.add_node(n1).add_node(n2).add_edge(e)

    def test_add_node_immutable(self):
        g = MachineGraph(name="test")
        n = SubsystemNode("x", NodeType.UNKNOWN, "X")
        g2 = g.add_node(n)
        assert "x" not in g.nodes
        assert "x" in g2.nodes

    def test_add_edge_immutable(self):
        g = MachineGraph(name="test")
        e = FlowEdge("e1", "a", "b")
        g2 = g.add_edge(e)
        assert len(g.edges) == 0
        assert len(g2.edges) == 1

    def test_downstream(self):
        g = self._make_graph()
        downstream = g.downstream("hopper")
        assert any(n.node_id == "drum" for n in downstream)

    def test_upstream(self):
        g = self._make_graph()
        upstream = g.upstream("drum")
        assert any(n.node_id == "hopper" for n in upstream)

    def test_material_flow_path_ordered(self):
        g = self._make_graph()
        path = g.material_flow_path()
        ids = [n.node_id for n in path]
        assert ids.index("hopper") < ids.index("drum")

    def test_to_dict_roundtrip(self):
        g = self._make_graph()
        d = g.to_dict()
        restored = MachineGraph.from_dict(d)
        assert restored.name == "test"
        assert "hopper" in restored.nodes
        assert len(restored.edges) == 1

    def test_get_node(self):
        g = self._make_graph()
        node = g.get_node("drum")
        assert node is not None
        assert node.node_type == NodeType.PRIMARY_DRUM

    def test_get_node_missing_returns_none(self):
        g = MachineGraph(name="test")
        assert g.get_node("nonexistent") is None


class TestGraphCompiler:
    def _htds_config(self):
        return {
            "name": "HTDS-P2",
            "spindle": {"shaft_od": 260, "flight_od": 600, "shaft_length": 4000},
            "drum": {"drum_id": 1500, "drum_length": 4000, "wall_thickness": 8},
            "frame": {"rail_length": 5000, "rail_a": 250, "rail_b": 150,
                      "rail_t": 10, "skid_width": 1800, "cross_a": 150,
                      "cross_b": 100, "cross_t": 8, "cross_count": 5},
            "compression_rollers": {"compression_gap": 20},
        }

    def test_from_yaml_dict_creates_nodes(self):
        graph = from_yaml_dict(self._htds_config())
        assert "drum" in graph.nodes
        assert "spindle" in graph.nodes
        assert "frame" in graph.nodes

    def test_from_yaml_dict_name_preserved(self):
        graph = from_yaml_dict(self._htds_config())
        assert graph.name == "HTDS-P2"

    def test_from_yaml_dict_material_flow_edges(self):
        graph = from_yaml_dict({"name": "test", "hopper": {}, "drum": {}})
        material_edges = [e for e in graph.edges if e.edge_type == EdgeType.MATERIAL_FEED]
        assert len(material_edges) >= 1

    def test_from_yaml_dict_structural_support_edges(self):
        graph = from_yaml_dict(self._htds_config())
        support_edges = [e for e in graph.edges if e.edge_type == EdgeType.STRUCTURAL_SUPPORT]
        assert len(support_edges) >= 1

    def test_from_yaml_dict_mechanical_drive_edge(self):
        graph = from_yaml_dict(self._htds_config())
        drive_edges = [e for e in graph.edges if e.edge_type == EdgeType.MECHANICAL_DRIVE]
        assert any(e.source_id == "spindle" and e.target_id == "drum" for e in drive_edges)

    def test_to_yaml_dict_roundtrip(self):
        config = {"name": "test", "drum": {"drum_id": 1500}, "hopper": {}}
        graph = from_yaml_dict(config)
        yaml_out = to_yaml_dict(graph)
        assert yaml_out["name"] == "test"
        assert "drum" in yaml_out

    def test_from_machine_config_dict(self):
        config = {"name": "test", "roller": {"diameter": 180, "width": 450, "shaft": 40}}
        graph = from_machine_config(config)
        assert graph.name == "test"
        assert "roller" in graph.nodes

    def test_wrapped_machine_key_handled(self):
        config = {"machine": {"name": "wrapped", "drum": {"drum_id": 1500}}}
        graph = from_yaml_dict(config)
        assert graph.name == "wrapped"
        assert "drum" in graph.nodes

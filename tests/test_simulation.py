"""Tests for app/simulation/engine.py — process simulation."""
import pytest
from app.graph.compiler import from_yaml_dict
from app.simulation.engine import simulate, SimulationResult


def _htds_graph():
    config = {
        "name": "HTDS-P2",
        "hopper": {},
        "compression_rollers": {"compression_gap": 20, "diameter": 200},
        "drum": {"drum_id": 1500, "drum_length": 4500, "wall_thickness": 8},
        "spindle": {"shaft_od": 260, "flight_od": 600, "shaft_length": 4200},
    }
    return from_yaml_dict(config)


class TestSimulationEngine:
    def test_returns_simulation_result(self):
        graph = _htds_graph()
        result = simulate(graph, feed_rate_kg_hr=1000.0)
        assert isinstance(result, SimulationResult)

    def test_throughput_less_than_feed(self):
        graph = _htds_graph()
        result = simulate(graph, feed_rate_kg_hr=1000.0)
        assert result.system_throughput_kg_hr <= 1000.0

    def test_efficiency_in_range(self):
        graph = _htds_graph()
        result = simulate(graph, feed_rate_kg_hr=1000.0)
        assert 0.0 <= result.system_efficiency <= 1.0

    def test_power_draw_positive(self):
        graph = _htds_graph()
        result = simulate(graph, feed_rate_kg_hr=1000.0)
        assert result.total_power_kw > 0

    def test_node_results_populated(self):
        graph = _htds_graph()
        result = simulate(graph, feed_rate_kg_hr=1000.0)
        assert len(result.node_results) > 0

    def test_bottleneck_identified_or_none(self):
        graph = _htds_graph()
        result = simulate(graph, feed_rate_kg_hr=1000.0)
        # bottleneck is either None or a valid node_id
        if result.bottleneck_node is not None:
            assert result.bottleneck_node in result.node_results

    def test_to_dict_complete(self):
        graph = _htds_graph()
        result = simulate(graph, feed_rate_kg_hr=1000.0)
        d = result.to_dict()
        required = {"machine_name", "feed_rate_kg_hr", "system_throughput_kg_hr",
                    "system_efficiency", "total_power_kw", "node_results"}
        assert required.issubset(d.keys())

    def test_empty_graph_returns_warnings(self):
        from app.graph.models import MachineGraph
        graph = MachineGraph(name="empty")
        result = simulate(graph, feed_rate_kg_hr=1000.0)
        assert len(result.warnings) > 0

    def test_short_drum_lower_efficiency(self):
        short_config = {
            "name": "short",
            "drum": {"drum_id": 1500, "drum_length": 1000, "wall_thickness": 8},
        }
        long_config = {
            "name": "long",
            "drum": {"drum_id": 1500, "drum_length": 4500, "wall_thickness": 8},
        }
        short_result = simulate(from_yaml_dict(short_config), 1000.0)
        long_result = simulate(from_yaml_dict(long_config), 1000.0)
        assert short_result.system_efficiency <= long_result.system_efficiency

    def test_deterministic(self):
        graph = _htds_graph()
        r1 = simulate(graph, 1000.0)
        r2 = simulate(graph, 1000.0)
        assert r1.system_throughput_kg_hr == r2.system_throughput_kg_hr

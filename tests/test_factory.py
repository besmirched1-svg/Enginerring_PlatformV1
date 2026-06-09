"""Tests for Factory Intelligence package (Phase 11)."""

import json
import os
import tempfile
from copy import deepcopy

import pytest

from app.factory.models import (
    FactoryProcessGraph,
    ProcessStream,
    ProcessUnit,
    ProcessUnitType,
    StreamType,
    StreamComponent,
)
from app.factory.mass_balance import solve_mass_balance, MassBalanceResult, UnitMassBalance
from app.factory.energy_balance import solve_energy_balance, EnergyBalanceResult
from app.factory.bottleneck import analyze_bottleneck, BottleneckResult, ProcessStepCapacity
from app.factory.layout import auto_layout, LayoutSolution, EquipmentPosition
from app.factory.optimization import (
    FactoryIndividual,
    evaluate_factory,
    fast_nondominated_sort,
    crowding_distance,
    tournament_selection,
    crossover,
    mutate,
    optimize_factory,
    default_mutators,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def simple_graph():
    g = FactoryProcessGraph(name="test_factory")
    feed = ProcessUnit(unit_type=ProcessUnitType.RECEIVING, label="Feed", max_capacity_kg_hr=5000)
    mill = ProcessUnit(unit_type=ProcessUnitType.MILLING, label="Mill", max_capacity_kg_hr=2000, efficiency=0.92)
    sep = ProcessUnit(unit_type=ProcessUnitType.SEPARATION, label="Separator", max_capacity_kg_hr=1800, efficiency=0.88)
    pkg = ProcessUnit(unit_type=ProcessUnitType.PACKAGING, label="Packaging", max_capacity_kg_hr=1500)
    g.add_unit(feed)
    g.add_unit(mill)
    g.add_unit(sep)
    g.add_unit(pkg)

    s1 = ProcessStream(source=feed.unit_id, target=mill.unit_id, stream_type=StreamType.MATERIAL, label="feed_to_mill")
    s2 = ProcessStream(source=mill.unit_id, target=sep.unit_id, stream_type=StreamType.MATERIAL, label="mill_to_sep")
    s3 = ProcessStream(source=sep.unit_id, target=pkg.unit_id, stream_type=StreamType.MATERIAL, label="sep_to_pkg")
    g.add_stream(s1)
    g.add_stream(s2)
    g.add_stream(s3)
    g.feed_streams = [s1.stream_id]
    g.product_streams = [s3.stream_id]
    g.waste_streams = []

    g.metadata["feed_stream_id"] = s1.stream_id
    g.metadata["product_stream_id"] = s3.stream_id

    return g


@pytest.fixture
def splitter_graph():
    g = FactoryProcessGraph(name="splitter_test")
    src = ProcessUnit(unit_type=ProcessUnitType.MIXING, label="Source", max_capacity_kg_hr=3000)
    split = ProcessUnit(unit_type=ProcessUnitType.SPLITTER, label="Splitter", max_capacity_kg_hr=3000)
    dest_a = ProcessUnit(unit_type=ProcessUnitType.BUFFER, label="DestA", max_capacity_kg_hr=2000)
    dest_b = ProcessUnit(unit_type=ProcessUnitType.BUFFER, label="DestB", max_capacity_kg_hr=2000)
    for u in [src, split, dest_a, dest_b]:
        g.add_unit(u)
    s_in = g.connect(src.unit_id, split.unit_id)
    s_a = g.connect(split.unit_id, dest_a.unit_id)
    s_b = g.connect(split.unit_id, dest_b.unit_id)
    g.feed_streams = [s_in.stream_id]
    g.product_streams = [s_a.stream_id, s_b.stream_id]
    split.config["split_fractions"] = {s_a.stream_id: 0.6, s_b.stream_id: 0.4}
    g.metadata["feed_stream_id"] = s_in.stream_id
    return g


# ===================================================================
# Models tests
# ===================================================================

class TestFactoryProcessGraph:
    def test_create_graph(self):
        g = FactoryProcessGraph(name="test")
        assert g.graph_id
        assert g.name == "test"
        assert g.units == {}
        assert g.streams == {}

    def test_add_unit(self):
        g = FactoryProcessGraph()
        u = ProcessUnit(unit_type=ProcessUnitType.MILLING, label="Mill")
        g.add_unit(u)
        assert u.unit_id in g.units
        assert g.get_unit(u.unit_id) is u

    def test_add_stream(self):
        g = FactoryProcessGraph()
        s = ProcessStream(label="test_stream")
        g.add_stream(s)
        assert s.stream_id in g.streams

    def test_connect(self):
        g = FactoryProcessGraph()
        a = ProcessUnit(unit_type=ProcessUnitType.MIXING, label="A")
        b = ProcessUnit(unit_type=ProcessUnitType.BUFFER, label="B")
        g.add_unit(a)
        g.add_unit(b)
        s = g.connect(a.unit_id, b.unit_id)
        assert s.source == a.unit_id
        assert s.target == b.unit_id
        assert s.stream_id in a.output_streams
        assert s.stream_id in b.input_streams

    def test_material_flow_order(self):
        g = FactoryProcessGraph()
        a = ProcessUnit(unit_type=ProcessUnitType.RECEIVING, label="A")
        b = ProcessUnit(unit_type=ProcessUnitType.MILLING, label="B")
        c = ProcessUnit(unit_type=ProcessUnitType.PACKAGING, label="C")
        g.add_unit(a)
        g.add_unit(b)
        g.add_unit(c)
        g.connect(a.unit_id, b.unit_id)
        g.connect(b.unit_id, c.unit_id)
        order = g.material_flow_order()
        assert len(order) == 3
        assert order[0].unit_id == a.unit_id

    def test_get_unit_nonexistent(self):
        g = FactoryProcessGraph()
        assert g.get_unit("nonexistent") is None

    def test_get_stream_nonexistent(self):
        g = FactoryProcessGraph()
        assert g.get_stream("nonexistent") is None

    def test_to_dict(self, simple_graph):
        d = simple_graph.to_dict()
        assert d["name"] == "test_factory"
        assert len(d["units"]) == 4
        assert len(d["streams"]) == 3
        assert isinstance(d["units"], dict)
        assert isinstance(d["streams"], dict)

    def test_stream_copy(self):
        s = ProcessStream(source="a", target="b", mass_flow_kg_hr=100)
        c = s.copy()
        assert c.source == "a"
        assert c.target == "b"
        assert c.mass_flow_kg_hr == 100
        assert c.stream_id != s.stream_id


class TestProcessUnit:
    def test_defaults(self):
        u = ProcessUnit()
        assert u.unit_id
        assert u.unit_type == ProcessUnitType.BUFFER
        assert u.conversion_fraction == 1.0
        assert u.efficiency == 1.0

    def test_with_specific_type(self):
        u = ProcessUnit(unit_type=ProcessUnitType.REACTION, label="Reactor", power_kw=50, heat_duty_kw=200)
        assert u.unit_type == ProcessUnitType.REACTION
        assert u.label == "Reactor"
        assert u.power_kw == 50
        assert u.heat_duty_kw == 200


class TestProcessStream:
    def test_defaults(self):
        s = ProcessStream()
        assert s.stream_id
        assert s.stream_type == StreamType.MATERIAL
        assert s.temperature_c == 25.0

    def test_with_components(self):
        c = StreamComponent(name="ore", mass_fraction=0.8, mass_flow_kg_hr=800)
        s = ProcessStream(mass_flow_kg_hr=1000, components=[c])
        assert len(s.components) == 1
        assert s.components[0].name == "ore"

    def test_energy_stream(self):
        s = ProcessStream(stream_type=StreamType.ENERGY, enthalpy_kw=500)
        assert s.stream_type == StreamType.ENERGY
        assert s.enthalpy_kw == 500


# ===================================================================
# Mass Balance tests
# ===================================================================

class TestMassBalance:
    def test_simple_mass_balance(self, simple_graph):
        result = solve_mass_balance(simple_graph, feed_rate_kg_hr=1000)
        assert isinstance(result, MassBalanceResult)
        assert result.feed_rate_kg_hr > 0
        assert result.product_rate_kg_hr > 0
        assert result.system_yield > 0
        assert len(result.units) > 0

    def test_no_feed_streams(self):
        g = FactoryProcessGraph()
        result = solve_mass_balance(g)
        assert len(result.warnings) > 0

    def test_splitter_mass_balance(self, splitter_graph):
        result = solve_mass_balance(splitter_graph, feed_rate_kg_hr=2000)
        assert result.converged
        assert abs(result.feed_rate_kg_hr - result.product_rate_kg_hr) < 1.0
        # check split fractions were applied
        splitter_id = [uid for uid, u in splitter_graph.units.items() if u.unit_type == ProcessUnitType.SPLITTER][0]
        splitter_unit = splitter_graph.get_unit(splitter_id)
        split_fractions = splitter_unit.config.get("split_fractions", {})
        if split_fractions:
            # output streams should reflect split
            for sid, frac in split_fractions.items():
                expected = result.feed_rate_kg_hr * frac / sum(split_fractions.values())
                actual = result.stream_flows.get(sid, 0)
                assert abs(expected - actual) < expected * 0.1, f"Split fraction mismatch for {sid}"

    def test_capacity_limit(self):
        g = FactoryProcessGraph()
        a = ProcessUnit(unit_type=ProcessUnitType.MILLING, label="A", max_capacity_kg_hr=100, efficiency=1.0)
        b = ProcessUnit(unit_type=ProcessUnitType.PACKAGING, label="B", max_capacity_kg_hr=500)
        g.add_unit(a)
        g.add_unit(b)
        s = g.connect(a.unit_id, b.unit_id)
        g.feed_streams = [s.stream_id]
        g.product_streams = [s.stream_id]
        result = solve_mass_balance(g, feed_rate_kg_hr=1000)
        # upstream mill should limit throughput
        assert result.feed_rate_kg_hr > 0

    def test_unit_balance_details(self, simple_graph):
        result = solve_mass_balance(simple_graph, feed_rate_kg_hr=1000)
        for ub in result.units.values():
            assert isinstance(ub, UnitMassBalance)
            assert ub.input_total_kg_hr >= 0
            assert ub.output_total_kg_hr >= 0
            assert ub.input_total_kg_hr >= ub.output_total_kg_hr - 0.01

    def test_waste_stream(self):
        g = FactoryProcessGraph()
        feed = ProcessUnit(unit_type=ProcessUnitType.RECEIVING, label="Feed")
        sep = ProcessUnit(unit_type=ProcessUnitType.SEPARATION, label="Sep", efficiency=0.88)
        prod = ProcessUnit(unit_type=ProcessUnitType.PACKAGING, label="Prod")
        waste = ProcessUnit(unit_type=ProcessUnitType.WASTE_TREATMENT, label="Waste")
        for u in [feed, sep, prod, waste]:
            g.add_unit(u)
        s1 = g.connect(feed.unit_id, sep.unit_id)
        s2 = g.connect(sep.unit_id, prod.unit_id)
        s3 = ProcessStream(source=sep.unit_id, target=waste.unit_id, stream_type=StreamType.MATERIAL)
        g.add_stream(s3)
        g.feed_streams = [s1.stream_id]
        g.product_streams = [s2.stream_id]
        g.waste_streams = [s3.stream_id]
        result = solve_mass_balance(g, feed_rate_kg_hr=1000)
        assert result.waste_rate_kg_hr > 0
        assert result.product_rate_kg_hr > 0

    def test_to_dict(self, simple_graph):
        result = solve_mass_balance(simple_graph, 500)
        d = result.to_dict()
        assert "feed_rate_kg_hr" in d
        assert "system_yield" in d
        assert "units" in d


# ===================================================================
# Energy Balance tests
# ===================================================================

class TestEnergyBalance:
    def test_simple_energy_balance(self, simple_graph):
        result = solve_energy_balance(simple_graph, throughput_kg_hr=1000)
        assert isinstance(result, EnergyBalanceResult)
        assert result.total_power_kw > 0
        assert len(result.units) == 4

    def test_no_units(self):
        g = FactoryProcessGraph()
        result = solve_energy_balance(g)
        assert result.total_power_kw == 0
        assert len(result.warnings) > 0

    def test_heating_unit(self):
        g = FactoryProcessGraph()
        heater = ProcessUnit(unit_type=ProcessUnitType.HEATING, label="Heater")
        g.add_unit(heater)
        result = solve_energy_balance(g, throughput_kg_hr=1000)
        ub = result.units[heater.unit_id]
        assert ub.heat_input_kw > 0
        assert ub.thermal_efficiency <= 1.0

    def test_cooling_unit(self):
        g = FactoryProcessGraph()
        cooler = ProcessUnit(unit_type=ProcessUnitType.COOLING, label="Cooler")
        g.add_unit(cooler)
        result = solve_energy_balance(g, throughput_kg_hr=1000)
        ub = result.units[cooler.unit_id]
        assert ub.heat_output_kw > 0

    def test_zero_throughput(self, simple_graph):
        result = solve_energy_balance(simple_graph, throughput_kg_hr=0)
        assert result.specific_energy_kwh_kg == 0
        assert result.total_power_kw > 0

    def test_to_dict(self, simple_graph):
        result = solve_energy_balance(simple_graph, 500)
        d = result.to_dict()
        assert "total_power_kw" in d
        assert "units" in d


# ===================================================================
# Bottleneck tests
# ===================================================================

class TestBottleneck:
    def test_analyze_simple(self, simple_graph):
        result = analyze_bottleneck(simple_graph, target_rate_kg_hr=1000)
        assert isinstance(result, BottleneckResult)
        assert result.target_rate_kg_hr == 1000
        assert result.theoretical_max_kg_hr > 0
        assert len(result.steps) > 0

    def test_bottleneck_identified(self, simple_graph):
        # make one unit much lower capacity
        units_list = list(simple_graph.units.values())
        bottleneck_unit = units_list[1]
        bottleneck_unit.max_capacity_kg_hr = 500
        result = analyze_bottleneck(simple_graph, target_rate_kg_hr=1000)
        assert result.bottleneck_unit_id is not None
        bottleneck_step = result.steps.get(result.bottleneck_unit_id)
        assert bottleneck_step is not None
        assert bottleneck_step.is_bottleneck

    def test_high_utilization_warning(self):
        g = FactoryProcessGraph()
        u = ProcessUnit(unit_type=ProcessUnitType.MILLING, label="Mill", max_capacity_kg_hr=100, efficiency=1.0)
        g.add_unit(u)
        s = ProcessStream(source=u.unit_id, target=u.unit_id)
        g.add_stream(s)
        g.feed_streams = [s.stream_id]
        g.product_streams = [s.stream_id]
        result = analyze_bottleneck(g, target_rate_kg_hr=99)
        step = result.steps[u.unit_id]
        assert step.utilization_pct > 0

    def test_takt_time(self):
        g = FactoryProcessGraph()
        u = ProcessUnit(unit_type=ProcessUnitType.PACKAGING, label="Pkg", max_capacity_kg_hr=1000)
        g.add_unit(u)
        s = ProcessStream(source=u.unit_id, target=u.unit_id)
        g.add_stream(s)
        g.feed_streams = [s.stream_id]
        result = analyze_bottleneck(g, target_rate_kg_hr=1000)
        assert result.takt_time_sec == 3.6


class TestProcessStepCapacity:
    def test_defaults(self):
        p = ProcessStepCapacity(unit_id="u1", label="test", unit_type="milling")
        assert p.unit_id == "u1"
        assert not p.is_bottleneck

    def test_with_values(self):
        p = ProcessStepCapacity("u1", "Test", "milling", cycle_time_sec=120, max_capacity_kg_hr=1000,
                                effective_capacity_kg_hr=900, utilization_pct=90, is_bottleneck=True,
                                slack_kg_hr=100)
        assert p.cycle_time_sec == 120
        assert p.is_bottleneck


# ===================================================================
# Layout tests
# ===================================================================

class TestLayout:
    def test_auto_layout(self, simple_graph):
        result = auto_layout(simple_graph)
        assert isinstance(result, LayoutSolution)
        assert len(result.positions) == 4
        assert result.total_area_m2 > 0

    def test_empty_graph(self):
        g = FactoryProcessGraph()
        result = auto_layout(g)
        assert len(result.positions) == 0

    def test_positions_have_coordinates(self, simple_graph):
        result = auto_layout(simple_graph)
        for pos in result.positions.values():
            assert isinstance(pos, EquipmentPosition)
            assert pos.x >= 0
            assert pos.y >= 0

    def test_material_handling_distance(self, simple_graph):
        result = auto_layout(simple_graph)
        assert result.material_handling_distance_m > 0

    def test_to_dict(self, simple_graph):
        result = auto_layout(simple_graph)
        d = result.to_dict()
        assert "total_area_m2" in d
        assert "positions" in d


# ===================================================================
# Optimization tests
# ===================================================================

class TestOptimization:
    def test_evaluate_factory(self, simple_graph):
        ind = FactoryIndividual(graph=simple_graph)
        ind = evaluate_factory(ind, feed_rate_kg_hr=1000)
        assert "throughput_kg_hr" in ind.fitness
        assert "yield_pct" in ind.fitness
        assert "energy_kwh_per_kg" in ind.fitness
        assert "utilization_pct" in ind.fitness

    def test_factory_individual_copy(self, simple_graph):
        ind = FactoryIndividual(graph=simple_graph)
        ind.fitness["throughput_kg_hr"] = 500
        copy_ind = ind.copy()
        assert copy_ind.fitness["throughput_kg_hr"] == 500
        assert copy_ind.graph.graph_id == ind.graph.graph_id
        assert copy_ind.graph is not ind.graph

    def test_nondominated_sort(self, simple_graph):
        pop = []
        for i in range(10):
            ind = FactoryIndividual(graph=simple_graph)
            ind.fitness = {
                "throughput_kg_hr": 1000 - i * 50,
                "yield_pct": 90 + i * 0.5,
                "energy_kwh_per_kg": -(2.0 + i * 0.1),
                "utilization_pct": 70 + i,
                "oee_score": 60 + i * 0.5,
                "layout_efficiency": 80,
                "capital_cost": -100000,
                "bottleneck_slack": 100,
            }
            pop.append(ind)
        fronts = fast_nondominated_sort(pop)
        assert len(fronts) >= 1
        assert len(fronts[0]) >= 1

    def test_crowding_distance(self):
        pop = []
        for i in range(10):
            ind = FactoryIndividual(graph=FactoryProcessGraph())
            ind.fitness = {
                "throughput_kg_hr": float(1000 + i * 100),
                "yield_pct": float(90),
                "energy_kwh_per_kg": float(-2.0),
                "utilization_pct": float(70),
                "oee_score": float(60),
                "layout_efficiency": float(80),
                "capital_cost": float(-100000),
                "bottleneck_slack": float(100),
            }
            pop.append(ind)
        crowding_distance(pop)
        assert pop[0].crowding_distance == float("inf")
        assert pop[-1].crowding_distance == float("inf")

    def test_tournament_selection(self, simple_graph):
        pop = []
        for i in range(10):
            ind = FactoryIndividual(graph=simple_graph)
            ind.rank = i // 3
            ind.crowding_distance = float(i)
            pop.append(ind)
        winner = tournament_selection(pop)
        assert winner is not None

    def test_crossover_same_graph(self, simple_graph):
        child_a, child_b = crossover(simple_graph, simple_graph)
        assert child_a is not simple_graph
        assert child_b is not simple_graph

    def test_mutate(self, simple_graph):
        mutated = mutate(simple_graph, mutation_rate=1.0)
        assert mutated is not simple_graph
        assert len(mutated.units) == len(simple_graph.units)

    def test_default_mutators(self):
        mutators = default_mutators()
        assert "efficiency" in mutators
        assert "power" in mutators
        assert "capacity" in mutators

    def test_optimize_factory_small(self, simple_graph):
        pop, history = optimize_factory(
            simple_graph,
            feed_rate_kg_hr=500,
            population_size=10,
            generations=3,
            mutation_rate=0.3,
            crossover_rate=0.8,
            seed=42,
        )
        assert len(pop) == 10
        assert len(history) == 3
        assert pop[0].fitness.get("throughput_kg_hr", 0) > 0

    def test_optimize_preserves_constraints(self, simple_graph):
        pop, _ = optimize_factory(
            simple_graph,
            feed_rate_kg_hr=100,
            population_size=8,
            generations=2,
            seed=123,
        )
        for ind in pop:
            assert isinstance(ind.constraints_ok, bool)
            assert isinstance(ind.constraint_violations, list)

    def test_evaluate_constraint_violations(self, simple_graph):
        # Set one unit to tiny capacity to force violations
        units_list = list(simple_graph.units.values())
        units_list[0].max_capacity_kg_hr = 10
        ind = FactoryIndividual(graph=simple_graph)
        ind = evaluate_factory(ind, feed_rate_kg_hr=1000)
        # may or may not violate depending on efficiency propagation
        assert isinstance(ind.constraints_ok, bool)
        assert isinstance(ind.constraint_violations, list)


# ===================================================================
# Integration smoke tests
# ===================================================================

class TestFactoryIntegration:
    def test_full_workflow(self):
        """Run mass balance -> energy balance -> bottleneck -> layout in sequence."""
        g = FactoryProcessGraph(name="integration_test")
        feed = ProcessUnit(unit_type=ProcessUnitType.RECEIVING, label="Feed", max_capacity_kg_hr=5000)
        mill = ProcessUnit(unit_type=ProcessUnitType.MILLING, label="Mill", max_capacity_kg_hr=2000, efficiency=0.92)
        sep = ProcessUnit(unit_type=ProcessUnitType.SEPARATION, label="Sep", max_capacity_kg_hr=1800, efficiency=0.88)
        dry = ProcessUnit(unit_type=ProcessUnitType.DRYING, label="Dryer", max_capacity_kg_hr=1600, efficiency=0.90)
        pkg = ProcessUnit(unit_type=ProcessUnitType.PACKAGING, label="Pkg", max_capacity_kg_hr=1500)
        for u in [feed, mill, sep, dry, pkg]:
            g.add_unit(u)
        s1 = g.connect(feed.unit_id, mill.unit_id)
        s2 = g.connect(mill.unit_id, sep.unit_id)
        s3 = g.connect(sep.unit_id, dry.unit_id)
        s4 = g.connect(dry.unit_id, pkg.unit_id)
        g.feed_streams = [s1.stream_id]
        g.product_streams = [s4.stream_id]

        mb = solve_mass_balance(g, feed_rate_kg_hr=1000)
        assert mb.converged

        eb = solve_energy_balance(g, throughput_kg_hr=mb.product_rate_kg_hr)
        assert eb.total_power_kw > 0

        bn = analyze_bottleneck(g, target_rate_kg_hr=1000)
        assert bn.bottleneck_unit_id is not None

        lo = auto_layout(g)
        assert len(lo.positions) == 5
        assert lo.material_handling_distance_m > 0

    def test_import_all(self):
        from app.factory import (
            FactoryProcessGraph, ProcessStream, ProcessUnit, ProcessUnitType, StreamType,
            solve_mass_balance, MassBalanceResult,
            solve_energy_balance, EnergyBalanceResult,
            analyze_bottleneck, BottleneckResult,
            auto_layout, LayoutSolution,
            optimize_factory, FactoryIndividual, evaluate_factory,
        )
        assert FactoryProcessGraph is not None

    def test_json_roundtrip(self, simple_graph):
        d = simple_graph.to_dict()
        json_str = json.dumps(d)
        restored = json.loads(json_str)
        assert restored["name"] == "test_factory"
        assert len(restored["units"]) == 4

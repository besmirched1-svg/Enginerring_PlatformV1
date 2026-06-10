"""Tests for ``app.vision.orchestrator_adapter`` (Phase 17.2a).

The adapter is a pure function: ``MachineGraph`` + ``bom_rows`` ->
dict. No I/O, no FastAPI. Tests pin the shape that
``EngineeringOrchestrator.run_machine_job`` is known to read, so
any future change to the adapter is intentional and reviewable.
"""
import pytest

from app.graph.models import (
    MachineGraph,
    NodeType,
    SubsystemNode,
)
from app.vision.orchestrator_adapter import (
    _BOM_SUBSYSTEM_KEYS,
    _SCAD_DEFAULTS,
    graph_to_orchestrator_config,
)


# --- Fixture helpers --------------------------------------------------------


def _node(node_id, node_type, label=None, config=None, confidence=0.8):
    """Build a SubsystemNode with sensible defaults for tests."""
    return SubsystemNode(
        node_id=node_id,
        node_type=node_type,
        label=label or node_id.replace("_", " ").title(),
        config=config or {},
        source="drawing",
        confidence=confidence,
    )


def _graph(*nodes):
    """Build a MachineGraph from a sequence of SubsystemNodes."""
    g = MachineGraph(name="test_machine", revision="v1")
    for n in nodes:
        g = g.add_node(n)
    return g


# --- Shape contract ---------------------------------------------------------


class TestScadDefaults:
    """The three SCAD-template keys are always present with safe
    defaults — the orchestrator's ``_generate_scad_template`` reads
    them and the SCAD file would be malformed without them."""

    def test_all_three_scad_keys_present_for_empty_graph(self):
        cfg = graph_to_orchestrator_config(_graph(), bom_rows=[])
        assert set(_SCAD_DEFAULTS) <= set(cfg)
        for k, v in _SCAD_DEFAULTS.items():
            assert cfg[k] == v, f"{k} default drifted"

    def test_scad_defaults_pin_values(self):
        """If a future change touches the defaults, this test fails
        — the change must be intentional and reviewed."""
        assert _SCAD_DEFAULTS == {
            "wall_thickness": 4.0,
            "clearance": 0.6,
            "roller_radius": 30.0,
        }


class TestEmptyGraph:
    """An empty graph (no subsystem nodes) still produces a valid
    orchestrator config — the SCAD template can render something
    and the BOM is just the empty set of subsystems."""

    def test_only_scad_keys(self):
        cfg = graph_to_orchestrator_config(_graph(), bom_rows=[])
        assert set(cfg) == {"wall_thickness", "clearance", "roller_radius"}

    def test_no_subsystem_keys(self):
        cfg = graph_to_orchestrator_config(_graph(), bom_rows=[])
        assert not (_BOM_SUBSYSTEM_KEYS & set(cfg))


# --- Single-subsystem case --------------------------------------------------


class TestSingleSubsystem:
    def test_drum_node_emits_drum_key(self):
        """NodeType.PRIMARY_DRUM must map to the ``drum`` key the
        orchestrator's BOM builder reads (not ``primary_drum``)."""
        g = _graph(_node("drum", NodeType.PRIMARY_DRUM,
                         config={"diameter": 400, "width": 800}))
        cfg = graph_to_orchestrator_config(g, bom_rows=[])
        assert cfg["drum"] == {"diameter": 400, "width": 800}

    def test_compression_roller_node_emits_correct_key(self):
        """NodeType.COMPRESSION_ROLLER must map to
        ``compression_rollers`` (plural, with underscore)."""
        g = _graph(_node("cr", NodeType.COMPRESSION_ROLLER,
                         config={"diameter": 200, "width": 500}))
        cfg = graph_to_orchestrator_config(g, bom_rows=[])
        assert cfg["compression_rollers"] == {"diameter": 200, "width": 500}

    def test_unknown_node_type_does_not_appear(self):
        """NodeType.UNKNOWN has no orchestrator slot; the adapter
        must not invent one."""
        g = _graph(_node("mystery", NodeType.UNKNOWN, config={"x": 1}))
        cfg = graph_to_orchestrator_config(g, bom_rows=[])
        assert "mystery" not in cfg

    def test_discharge_node_does_not_appear(self):
        """NodeType.DISCHARGE is recognized by the compiler's
        forward map but not by the BOM builder; the adapter
        must not add a ``discharge`` key."""
        g = _graph(_node("d", NodeType.DISCHARGE, config={"x": 1}))
        cfg = graph_to_orchestrator_config(g, bom_rows=[])
        assert "discharge" not in cfg

    def test_drive_node_does_not_appear(self):
        """NodeType.DRIVE is similarly not in the orchestrator's
        current shape; the adapter does not invent a slot."""
        g = _graph(_node("drv", NodeType.DRIVE, config={"power_kw": 5}))
        cfg = graph_to_orchestrator_config(g, bom_rows=[])
        assert "drive" not in cfg


class TestNodeConfigForwarded:
    def test_subsystem_config_copied_verbatim(self):
        """The node's config dict is the substance of the
        subsystem entry; it must be forwarded as-is."""
        node_config = {
            "diameter": 200,
            "width": 500,
            "shaft": 50,
            "material": "hardox_400",
        }
        g = _graph(_node("roller", NodeType.ROLLER, config=node_config))
        cfg = graph_to_orchestrator_config(g, bom_rows=[])
        assert cfg["roller"] == node_config

    def test_subsystem_config_is_shallow_copy(self):
        """Mutating the returned dict after the call must not
        mutate the graph's node config — a leak would silently
        corrupt later passes (e.g. confidence-floor handling
        in the route might attach a warning dict)."""
        node = _node("hopper", NodeType.HOPPER, config={"volume_l": 100})
        g = _graph(node)
        cfg = graph_to_orchestrator_config(g, bom_rows=[])
        cfg["hopper"]["_marker"] = True
        assert "_marker" not in g.nodes["hopper"].config

    def test_empty_node_config_falls_back_to_label(self):
        """A node with no config still produces a truthy
        subsystem entry (so the BOM builder still emits a
        row), via a ``{"label": ...}`` fallback."""
        g = _graph(_node("frame", NodeType.FRAME, label="Main Frame",
                         config={}))
        cfg = graph_to_orchestrator_config(g, bom_rows=[])
        assert cfg["frame"] == {"label": "Main Frame"}


# --- Multi-subsystem case ---------------------------------------------------


class TestMultiSubsystem:
    def test_multiple_nodes_produce_multiple_keys(self):
        """A graph with hopper + drum + frame produces three
        subsystem entries plus the three SCAD defaults."""
        g = _graph(
            _node("hopper", NodeType.HOPPER, config={"volume_l": 200}),
            _node("drum", NodeType.PRIMARY_DRUM, config={"diameter": 400}),
            _node("frame", NodeType.FRAME, config={"length": 1500,
                                                    "width": 800}),
        )
        cfg = graph_to_orchestrator_config(g, bom_rows=[])
        assert set(cfg) == {
            "wall_thickness", "clearance", "roller_radius",
            "hopper", "drum", "frame",
        }
        assert cfg["hopper"] == {"volume_l": 200}
        assert cfg["drum"] == {"diameter": 400}
        assert cfg["frame"] == {"length": 1500, "width": 800}

    def test_all_six_orchestrator_subsystem_keys(self):
        """All six orchestrator subsystem keys are reachable
        from the corresponding NodeTypes — pin that the
        mapping is complete, not partial."""
        g = _graph(
            _node("f", NodeType.FRAME, config={"x": 1}),
            _node("r", NodeType.ROLLER, config={"x": 2}),
            _node("h", NodeType.HOPPER, config={"x": 3}),
            _node("s", NodeType.SPINDLE, config={"x": 4}),
            _node("d", NodeType.PRIMARY_DRUM, config={"x": 5}),
            _node("cr", NodeType.COMPRESSION_ROLLER, config={"x": 6}),
        )
        cfg = graph_to_orchestrator_config(g, bom_rows=[])
        for key in ("frame", "roller", "hopper", "spindle",
                    "drum", "compression_rollers"):
            assert key in cfg, f"missing orchestrator key: {key}"
        assert cfg["compression_rollers"] == {"x": 6}

    def test_conveyor_node_works(self):
        """NodeType.CONVEYOR is in the orchestrator's subsystem
        set even though the orchestrator's BOM builder doesn't
        read it directly — it shows up in the config as a
        subsystem the BOM builder's ``if config.get(...)``
        check can find."""
        g = _graph(_node("c", NodeType.CONVEYOR, config={"length": 2000}))
        cfg = graph_to_orchestrator_config(g, bom_rows=[])
        assert cfg["conveyor"] == {"length": 2000}


# --- BOM rows parameter (reserved for 17.3) ---------------------------------


class TestBomRowsParameter:
    def test_bom_rows_is_accepted_but_unused(self):
        """The 17.2a adapter accepts ``bom_rows`` for forward
        compatibility with 17.3 (the review-then-commit flow
        may want to merge BOM-row material specs into the
        subsystem configs), but does not consume it today.
        Pin that contract: any value is accepted, the
        returned config does not change with different values.
        """
        g = _graph(_node("drum", NodeType.PRIMARY_DRUM,
                         config={"diameter": 400}))
        cfg_empty = graph_to_orchestrator_config(g, bom_rows=[])
        cfg_with_rows = graph_to_orchestrator_config(
            g, bom_rows=[{"part": "Drum", "material": "hardox_400"}]
        )
        cfg_with_many = graph_to_orchestrator_config(
            g, bom_rows=[{"part": "Drum"}, {"part": "Frame"},
                         {"part": "Roller"}]
        )
        # The three SCAD defaults and the single subsystem
        # entry are the only keys; bom_rows does not
        # introduce new keys in 17.2a.
        for cfg in (cfg_empty, cfg_with_rows, cfg_with_many):
            assert set(cfg) == {"wall_thickness", "clearance",
                                "roller_radius", "drum"}
            assert cfg["drum"] == {"diameter": 400}


# --- Closure contract -------------------------------------------------------


class TestClosureContract:
    """Pin the exact set of keys the adapter may emit. If a
    future refactor accidentally adds or removes one, this test
    fails and the change must be intentional."""

    def test_closure_is_scad_plus_subsystem_keys(self):
        g = _graph(
            _node("f", NodeType.FRAME, config={"x": 1}),
            _node("d", NodeType.PRIMARY_DRUM, config={"x": 2}),
            _node("cr", NodeType.COMPRESSION_ROLLER, config={"x": 3}),
            _node("c", NodeType.CONVEYOR, config={"x": 4}),
            # These two must NOT contribute to the closure.
            _node("drive", NodeType.DRIVE, config={"x": 5}),
            _node("mystery", NodeType.UNKNOWN, config={"x": 6}),
        )
        cfg = graph_to_orchestrator_config(g, bom_rows=[])
        assert set(cfg) == {
            "wall_thickness", "clearance", "roller_radius",
            "frame", "drum", "compression_rollers", "conveyor",
        }

    def test_subsystem_keys_constant_pinned(self):
        """If a future refactor extends ``_BOM_SUBSYSTEM_KEYS``,
        this test fails and the change must be intentional."""
        assert _BOM_SUBSYSTEM_KEYS == frozenset({
            "frame", "roller", "hopper", "spindle",
            "drum", "compression_rollers", "conveyor",
        })

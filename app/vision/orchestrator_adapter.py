"""Adapter: MachineGraph -> orchestrator config dict (Phase 17.2a).

The orchestrator's :func:`EngineeringOrchestrator.run_machine_job`
expects a plain dict config with two kinds of keys:

1. **SCAD-template keys** — ``wall_thickness``, ``clearance``,
   ``roller_radius``. Read by ``_generate_scad_template`` and
   ``_calculate_live_metrics`` in ``app/core/orchestrator.py``.
2. **Subsystem keys** — ``frame``, ``roller``, ``hopper``,
   ``spindle``, ``drum``, ``compression_rollers``. Read by the
   orchestrator's BOM builder, which emits one row per truthy
   subsystem key. The contents of each subsystem dict are
   forwarded to the BOM row.

A ``MachineGraph`` produced by the vision pipeline has subsystem
nodes (with their own ``config`` dicts) but the orchestrator's
shape is different. This module is the one place that knows
both shapes — the project's "official bridge" between the
drawing and the orchestrator, in the same spirit as
``app/factory_director/planner.py:reliefs_to_dynamic_constraints``
being the bridge between the plant and machine pipelines
(per ``docs/ARCHITECTURE.md``).

The adapter is **pure** — no I/O, no FastAPI, no logging. It
returns a plain dict. The route in
``app/api/routes.py:ingest_and_build`` (Commit 3b) is the only
caller; tests in ``tests/test_orchestrator_adapter.py`` pin
its shape.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.graph.models import MachineGraph, NodeType, SubsystemNode


# SCAD-template defaults. Safe for any graph; the orchestrator's
# _generate_scad_template reads these three keys and uses the
# provided values verbatim in the emitted SCAD.
_SCAD_DEFAULTS: Dict[str, float] = {
    "wall_thickness": 4.0,
    "clearance": 0.6,
    "roller_radius": 30.0,
}

# Subsystem keys the orchestrator's BOM builder reads. Kept
# narrow on purpose: the BOM builder is the only consumer, and
# it checks ``if config.get(<key>):`` — so any other key on the
# config dict is silently ignored. Pinned here as a frozenset
# so the test surface can assert the closure.
_BOM_SUBSYSTEM_KEYS: frozenset = frozenset({
    "frame",
    "roller",
    "hopper",
    "spindle",
    "drum",
    "compression_rollers",
    "conveyor",
})

# Reverse of app.graph.compiler._YAML_KEY_TO_NODE_TYPE. The
# compiler's forward map couples YAML strings to NodeType
# enums; we need the reverse for graph -> YAML translation.
# Inlined here rather than imported from the compiler to keep
# this module free of the compiler's import surface and to
# avoid coupling the adapter to compiler internals that may
# change in future sub-phases.
_NODE_TYPE_TO_YAML_KEY: Dict[NodeType, str] = {
    NodeType.HOPPER: "hopper",
    NodeType.CONVEYOR: "conveyor",
    NodeType.COMPRESSION_ROLLER: "compression_rollers",
    NodeType.PRIMARY_DRUM: "drum",
    NodeType.SPINDLE: "spindle",
    NodeType.FRAME: "frame",
    NodeType.ROLLER: "roller",
}


def graph_to_orchestrator_config(
    graph: MachineGraph,
    bom_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Project a ``MachineGraph`` into the orchestrator's config shape.

    The returned dict has the three SCAD-template keys
    (``wall_thickness``, ``clearance``, ``roller_radius``) with
    safe defaults, plus one entry per recognized subsystem node
    in the graph. The orchestrator's BOM builder reads the
    subsystem entries and emits one row per truthy one.

    Parameters
    ----------
    graph:
        The drawing's reconstructed ``MachineGraph``. May be
        empty (no nodes); the function still returns a valid
        orchestrator config with just the SCAD defaults.
    bom_rows:
        The drawing's extracted BOM rows. Reserved for
        downstream use (e.g. a future 17.3 commit may want
        to merge BOM-row material specifications into the
        subsystem configs). The 17.2a adapter does not
        consume it; the parameter is in the signature so
        the 17.3 commit does not have to change the call
        site. Pinned in the test suite as "accepted but
        currently unused".

    Returns
    -------
    dict
        A new dict suitable for ``run_machine_job(..., config=...)``.
        The orchestrator reads three top-level keys and a
        handful of optional subsystem keys. The adapter's
        return value contains only the keys the orchestrator
        is known to read; if a future orchestrator version
        tightens its tolerance for unknown keys, this
        function is the single point of update.

    Notes
    -----
    The mapping uses ``SubsystemNode.node_type`` (the canonical
    ``NodeType`` enum) as the source of truth, not ``label``
    (a human-readable string from the title block). The two
    are independent — the same label can correspond to multiple
    node types across drawings, but the enum value is exact.
    This makes the adapter deterministic regardless of OCR-
    derived label noise.
    """
    cfg: Dict[str, Any] = dict(_SCAD_DEFAULTS)

    for node in graph.nodes.values():
        yaml_key = _NODE_TYPE_TO_YAML_KEY.get(node.node_type)
        if yaml_key is None or yaml_key not in _BOM_SUBSYSTEM_KEYS:
            # Either not a recognized subsystem, or a
            # recognized subsystem the BOM builder doesn't
            # read. Skip silently — the graph may carry
            # nodes (e.g. DRIVE, DISCHARGE) that the
            # orchestrator's current shape has no slot for.
            continue
        cfg[yaml_key] = _node_to_subsystem_config(node)

    # bom_rows is reserved for downstream use. The 17.2a
    # adapter does not consume it; explicitly reference the
    # parameter so linters / future readers do not strip it.
    _ = bom_rows

    return cfg


def _node_to_subsystem_config(node: SubsystemNode) -> Dict[str, Any]:
    """Convert a single ``SubsystemNode`` to a subsystem config dict.

    The orchestrator's BOM builder only checks truthiness on
    each subsystem key; it does not inspect the inner shape.
    We forward the node's ``config`` dict verbatim when
    present (it carries dimensions / material from the
    drawing), and fall back to a minimal ``{"label": ...}``
    placeholder when the node had no config — keeping the
    BOM builder's truthy check passing.

    A shallow ``dict(node.config)`` copy is used so a later
    mutation in the route (e.g. confidence-floor handling)
    cannot leak back into the graph.
    """
    if node.config:
        return dict(node.config)
    return {"label": node.label}

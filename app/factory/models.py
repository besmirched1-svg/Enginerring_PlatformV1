from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


class ProcessUnitType(str, Enum):
    RECEIVING = "receiving"
    STORAGE = "storage"
    CONVEYING = "conveying"
    SCREENING = "screening"
    SEPARATION = "separation"
    MILLING = "milling"
    GRINDING = "grinding"
    MIXING = "mixing"
    REACTION = "reaction"
    HEATING = "heating"
    COOLING = "cooling"
    DRYING = "drying"
    PRESSING = "pressing"
    EXTRUSION = "extrusion"
    PACKAGING = "packaging"
    UTILITY = "utility"
    WASTE_TREATMENT = "waste_treatment"
    BUFFER = "buffer"
    SPLITTER = "splitter"
    MERGER = "merger"


class StreamType(str, Enum):
    MATERIAL = "material"
    ENERGY = "energy"
    UTILITY = "utility"


@dataclass
class StreamComponent:
    name: str
    mass_fraction: float = 0.0
    mass_flow_kg_hr: float = 0.0


@dataclass
class ProcessStream:
    stream_id: str = ""
    source: str = ""
    target: str = ""
    stream_type: StreamType = StreamType.MATERIAL
    mass_flow_kg_hr: float = 0.0
    temperature_c: float = 25.0
    pressure_bar: float = 1.0
    components: List[StreamComponent] = field(default_factory=list)
    enthalpy_kw: float = 0.0
    label: str = ""

    def __post_init__(self):
        if not self.stream_id:
            self.stream_id = uuid.uuid4().hex[:8]
        # Phase 16.1: defensive clamp on stream numerics. Same pattern
        # as ProcessUnit: non-finite or negative values get safe defaults.
        if not _is_finite_number(self.mass_flow_kg_hr):
            self.mass_flow_kg_hr = 0.0
        else:
            self.mass_flow_kg_hr = max(0.0, float(self.mass_flow_kg_hr))
        if not _is_finite_number(self.enthalpy_kw):
            self.enthalpy_kw = 0.0
        # temperature_c and pressure_bar can legitimately be negative
        # (cryogenics, vacuum) so we only sanitise, not clamp.

    def copy(self) -> ProcessStream:
        return ProcessStream(
            stream_id=uuid.uuid4().hex[:8],
            source=self.source,
            target=self.target,
            stream_type=self.stream_type,
            mass_flow_kg_hr=self.mass_flow_kg_hr,
            temperature_c=self.temperature_c,
            pressure_bar=self.pressure_bar,
            components=[StreamComponent(**c.__dict__) for c in self.components],
            enthalpy_kw=self.enthalpy_kw,
            label=self.label,
        )


@dataclass
class ProcessUnit:
    unit_id: str = ""
    unit_type: ProcessUnitType = ProcessUnitType.BUFFER
    label: str = ""
    input_streams: List[str] = field(default_factory=list)
    output_streams: List[str] = field(default_factory=list)
    conversion_fraction: float = 1.0
    power_kw: float = 0.0
    heat_duty_kw: float = 0.0
    efficiency: float = 1.0
    max_capacity_kg_hr: float = 1e6
    footprint_m2: float = 10.0
    height_m: float = 3.0
    capital_cost: float = 0.0
    operating_cost_per_hr: float = 0.0
    config: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.unit_id:
            self.unit_id = uuid.uuid4().hex[:8]
        # Phase 16.1: defensive clamps on the numeric fields. The
        # analyzers also validate, but clamping here at construction
        # means downstream code never has to handle an obviously-broken
        # value. Non-finite values fall back to safe defaults; out-of-
        # range values get clamped to the engineering envelope.
        if not _is_finite_number(self.efficiency):
            self.efficiency = 0.95
        else:
            self.efficiency = max(0.0, min(1.0, float(self.efficiency)))
        if not _is_finite_number(self.max_capacity_kg_hr):
            self.max_capacity_kg_hr = 1000.0
        else:
            self.max_capacity_kg_hr = max(0.0, float(self.max_capacity_kg_hr))
        if not _is_finite_number(self.footprint_m2):
            self.footprint_m2 = 10.0
        else:
            self.footprint_m2 = max(0.0, float(self.footprint_m2))
        if not _is_finite_number(self.power_kw):
            self.power_kw = 0.0
        if not _is_finite_number(self.heat_duty_kw):
            self.heat_duty_kw = 0.0
        if not _is_finite_number(self.capital_cost):
            self.capital_cost = 0.0
        if not _is_finite_number(self.operating_cost_per_hr):
            self.operating_cost_per_hr = 0.0


@dataclass
class FactoryProcessGraph:
    graph_id: str = ""
    name: str = "factory"
    units: Dict[str, ProcessUnit] = field(default_factory=dict)
    streams: Dict[str, ProcessStream] = field(default_factory=dict)
    feed_streams: List[str] = field(default_factory=list)
    product_streams: List[str] = field(default_factory=list)
    waste_streams: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.graph_id:
            self.graph_id = uuid.uuid4().hex[:12]

    def get_unit(self, unit_id: str) -> Optional[ProcessUnit]:
        return self.units.get(unit_id)

    def get_stream(self, stream_id: str) -> Optional[ProcessStream]:
        return self.streams.get(stream_id)

    def add_unit(self, unit: ProcessUnit) -> ProcessUnit:
        self.units[unit.unit_id] = unit
        return unit

    def add_stream(self, stream: ProcessStream) -> ProcessStream:
        self.streams[stream.stream_id] = stream
        src = self.units.get(stream.source)
        tgt = self.units.get(stream.target)
        if src and stream.stream_id not in src.output_streams:
            src.output_streams.append(stream.stream_id)
        if tgt and stream.stream_id not in tgt.input_streams:
            tgt.input_streams.append(stream.stream_id)
        return stream

    def connect(self, source_id: str, target_id: str, stream: Optional[ProcessStream] = None) -> ProcessStream:
        if stream is None:
            stream = ProcessStream(source=source_id, target=target_id)
        else:
            stream.source = source_id
            stream.target = target_id
        self.streams[stream.stream_id] = stream
        src = self.units.get(source_id)
        tgt = self.units.get(target_id)
        if src and stream.stream_id not in src.output_streams:
            src.output_streams.append(stream.stream_id)
        if tgt and stream.stream_id not in tgt.input_streams:
            tgt.input_streams.append(stream.stream_id)
        return stream

    def material_flow_order(self) -> List[ProcessUnit]:
        material_streams = [s for s in self.streams.values() if s.stream_type == StreamType.MATERIAL]
        has_incoming = set()
        for s in material_streams:
            has_incoming.add(s.target)
        roots = [u for u in self.units.values() if u.unit_id not in has_incoming]
        visited: List[ProcessUnit] = []
        seen: set = set()

        def _visit(uid: str):
            if uid in seen:
                return
            seen.add(uid)
            unit = self.units.get(uid)
            if unit:
                visited.append(unit)
                for sid in unit.output_streams:
                    s = self.streams.get(sid)
                    if s and s.target:
                        _visit(s.target)

        for root in roots:
            _visit(root.unit_id)

        for unit in self.units.values():
            if unit.unit_id not in seen:
                visited.append(unit)
        return visited

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "name": self.name,
            "units": {k: {**v.__dict__, "unit_type": v.unit_type.value} for k, v in self.units.items()},
            "streams": {k: {**v.__dict__, "stream_type": v.stream_type.value} for k, v in self.streams.items()},
            "feed_streams": self.feed_streams,
            "product_streams": self.product_streams,
            "waste_streams": self.waste_streams,
            "metadata": self.metadata,
        }

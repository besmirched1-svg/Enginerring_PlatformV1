import itertools
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .models import FactoryProcessGraph, ProcessUnitType

logger = logging.getLogger("engine.factory.layout")


@dataclass
class EquipmentPosition:
    unit_id: str
    label: str
    unit_type: str
    x: float = 0.0
    y: float = 0.0
    width_m: float = 2.0
    depth_m: float = 2.0
    rotation_deg: float = 0.0


@dataclass
class TransportDistance:
    from_unit: str
    to_unit: str
    distance_m: float = 0.0
    stream_id: str = ""


@dataclass
class LayoutSolution:
    positions: Dict[str, EquipmentPosition] = field(default_factory=dict)
    total_area_m2: float = 0.0
    material_handling_distance_m: float = 0.0
    overlap_count: int = 0
    placement_efficiency: float = 0.0
    bounding_box: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_area_m2": round(self.total_area_m2, 1),
            "material_handling_distance_m": round(self.material_handling_distance_m, 1),
            "overlap_count": self.overlap_count,
            "placement_efficiency": round(self.placement_efficiency, 3),
            "bounding_box": {
                "x_min": round(self.bounding_box[0], 1),
                "y_min": round(self.bounding_box[1], 1),
                "x_max": round(self.bounding_box[2], 1),
                "y_max": round(self.bounding_box[3], 1),
            },
            "positions": {
                k: {"x": round(v.x, 1), "y": round(v.y, 1), "width_m": v.width_m, "depth_m": v.depth_m}
                for k, v in self.positions.items()
            },
        }


_DEFAULT_FOOTPRINT: Dict[ProcessUnitType, Tuple[float, float]] = {
    ProcessUnitType.RECEIVING: (6.0, 4.0),
    ProcessUnitType.STORAGE: (8.0, 6.0),
    ProcessUnitType.CONVEYING: (10.0, 1.5),
    ProcessUnitType.SCREENING: (3.0, 3.0),
    ProcessUnitType.SEPARATION: (4.0, 3.0),
    ProcessUnitType.MILLING: (5.0, 4.0),
    ProcessUnitType.GRINDING: (5.0, 4.0),
    ProcessUnitType.MIXING: (3.0, 3.0),
    ProcessUnitType.REACTION: (4.0, 4.0),
    ProcessUnitType.HEATING: (3.0, 3.0),
    ProcessUnitType.COOLING: (3.0, 3.0),
    ProcessUnitType.DRYING: (6.0, 4.0),
    ProcessUnitType.PRESSING: (4.0, 3.0),
    ProcessUnitType.EXTRUSION: (8.0, 3.0),
    ProcessUnitType.PACKAGING: (5.0, 4.0),
    ProcessUnitType.UTILITY: (4.0, 4.0),
    ProcessUnitType.WASTE_TREATMENT: (5.0, 4.0),
    ProcessUnitType.BUFFER: (2.0, 2.0),
    ProcessUnitType.SPLITTER: (1.0, 1.0),
    ProcessUnitType.MERGER: (1.0, 1.0),
}


def auto_layout(
    graph: FactoryProcessGraph,
    spacing_m: float = 2.0,
    rows: Optional[int] = None,
) -> LayoutSolution:
    flow_order = graph.material_flow_order()
    positions: Dict[str, EquipmentPosition] = {}
    total_area = 0.0
    total_distance = 0.0
    overlap_count = 0

    if not flow_order:
        return LayoutSolution()

    n = len(flow_order)
    if rows is None:
        rows = max(1, int(math.sqrt(n)))

    cols = math.ceil(n / rows)
    x_positions: Dict[str, float] = {}
    y_positions: Dict[str, float] = {}

    for i, unit in enumerate(flow_order):
        fp = _DEFAULT_FOOTPRINT.get(unit.unit_type, (2.0, 2.0))
        width = unit.footprint_m2 ** 0.5 if unit.footprint_m2 > 0 else fp[0]
        depth = unit.footprint_m2 ** 0.5 if unit.footprint_m2 > 0 else fp[1]

        row = i // cols
        col = i % cols
        x = col * (width + spacing_m)
        y = row * (depth + spacing_m)

        positions[unit.unit_id] = EquipmentPosition(
            unit_id=unit.unit_id,
            label=unit.label or unit.unit_type.value,
            unit_type=unit.unit_type.value,
            x=x,
            y=y,
            width_m=width,
            depth_m=depth,
        )
        x_positions[unit.unit_id] = x
        y_positions[unit.unit_id] = y
        total_area += width * depth

    for stream in graph.streams.values():
        src_pos = x_positions.get(stream.source)
        tgt_pos = x_positions.get(stream.target)
        if src_pos is not None and tgt_pos is not None:
            sx = x_positions[stream.source]
            sy = y_positions[stream.source]
            tx = x_positions[stream.target]
            ty = y_positions[stream.target]
            dist = math.sqrt((tx - sx) ** 2 + (ty - sy) ** 2)
            total_distance += dist

    for (a_id, a_pos), (b_id, b_pos) in itertools.combinations(positions.items(), 2):
        overlap_x = max(0, a_pos.width_m + b_pos.width_m - abs(a_pos.x - b_pos.x))
        overlap_y = max(0, a_pos.depth_m + b_pos.depth_m - abs(a_pos.y - b_pos.y))
        if overlap_x > 0 and overlap_y > 0:
            overlap_count += 1

    if positions:
        x_min = min(p.x for p in positions.values())
        x_max = max(p.x + p.width_m for p in positions.values())
        y_min = min(p.y for p in positions.values())
        y_max = max(p.y + p.depth_m for p in positions.values())
    else:
        x_min = y_min = x_max = y_max = 0.0

    bounding_area = (x_max - x_min) * (y_max - y_min) if (x_max - x_min) * (y_max - y_min) > 0 else 1.0
    placement_efficiency = total_area / bounding_area

    return LayoutSolution(
        positions=positions,
        total_area_m2=total_area,
        material_handling_distance_m=total_distance,
        overlap_count=overlap_count,
        placement_efficiency=placement_efficiency,
        bounding_box=(x_min, y_min, x_max, y_max),
    )

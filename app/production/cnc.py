# app/production/cnc.py
# Phase 15 Autonomous Manufacturing & Deployment: CNC G-code generation.
#
# Generates ISO 6983 (RS-274) G-code text. Output is a program file only; it is
# not transmitted to any machine controller.

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from .models import GCodeProgram

logger = logging.getLogger("engine.production.cnc")


def _fmt(value: float) -> str:
    """Format a coordinate with 3 decimals, trimming trailing zeros."""
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _header(program: GCodeProgram, safe_z: float) -> None:
    program.lines.append(f"; {program.operation} - {program.name}")
    program.lines.append("G21 ; units in millimetres")
    program.lines.append("G90 ; absolute positioning")
    program.lines.append("G17 ; XY plane")
    program.lines.append(f"T{program.tool} M06 ; tool change")
    program.lines.append(f"S{int(program.spindle_rpm)} M03 ; spindle on, clockwise")
    program.lines.append("G54 ; work coordinate system")
    program.lines.append(f"G00 Z{_fmt(safe_z)} ; rapid to safe height")


def _footer(program: GCodeProgram, safe_z: float) -> None:
    program.lines.append(f"G00 Z{_fmt(safe_z)} ; retract")
    program.lines.append("M05 ; spindle off")
    program.lines.append("M30 ; program end")


def generate_drilling_program(
    holes: List[Tuple[float, float]],
    depth_mm: float,
    spindle_rpm: float = 1200.0,
    feed_mm_min: float = 150.0,
    safe_z: float = 5.0,
    retract_z: float = 2.0,
    tool: int = 1,
    name: str = "drill",
) -> GCodeProgram:
    """Generate a drilling program using the G81 canned cycle.

    ``holes`` is a list of (x, y) centres. Drills each to ``depth_mm`` below
    Z0 (the part top), retracting to ``retract_z`` between holes.
    """
    program = GCodeProgram(
        name=name, tool=tool, spindle_rpm=spindle_rpm,
        feed_mm_min=feed_mm_min, operation="drilling",
    )
    if not holes:
        program.lines.append("; no holes supplied")
        return program

    _header(program, safe_z)
    program.lines.append(
        f"G98 ; return to initial Z after each hole"
    )
    for i, (x, y) in enumerate(holes):
        if i == 0:
            program.lines.append(
                f"G81 X{_fmt(x)} Y{_fmt(y)} Z{_fmt(-abs(depth_mm))} "
                f"R{_fmt(retract_z)} F{_fmt(feed_mm_min)} ; drill hole {i + 1}"
            )
        else:
            program.lines.append(f"X{_fmt(x)} Y{_fmt(y)} ; drill hole {i + 1}")
    program.lines.append("G80 ; cancel canned cycle")
    _footer(program, safe_z)
    logger.info("Generated drilling program '%s' for %d holes", name, len(holes))
    return program


def generate_profile_program(
    points: List[Tuple[float, float]],
    cut_depth_mm: float,
    depth_per_pass_mm: float = 2.0,
    spindle_rpm: float = 2000.0,
    feed_mm_min: float = 600.0,
    safe_z: float = 5.0,
    tool: int = 1,
    name: str = "profile",
    closed: bool = True,
) -> GCodeProgram:
    """Generate a 2.5D contour-cut program for a closed/open polyline.

    Cuts the profile in multiple passes of ``depth_per_pass_mm`` until
    ``cut_depth_mm`` is reached. The first point is the lead-in position.
    """
    program = GCodeProgram(
        name=name, tool=tool, spindle_rpm=spindle_rpm,
        feed_mm_min=feed_mm_min, operation="profile_cut",
    )
    if len(points) < 2:
        program.lines.append("; need at least 2 points for a profile")
        return program

    _header(program, safe_z)

    passes = max(1, int(-(-abs(cut_depth_mm) // depth_per_pass_mm)))  # ceil
    x0, y0 = points[0]
    program.lines.append(f"G00 X{_fmt(x0)} Y{_fmt(y0)} ; rapid to start")

    z = 0.0
    for p in range(passes):
        z = max(-abs(cut_depth_mm), z - depth_per_pass_mm)
        program.lines.append(f"G01 Z{_fmt(z)} F{_fmt(feed_mm_min / 2)} ; plunge pass {p + 1}")
        path = points[1:] + ([points[0]] if closed else [])
        for (x, y) in path:
            program.lines.append(f"G01 X{_fmt(x)} Y{_fmt(y)} F{_fmt(feed_mm_min)}")

    _footer(program, safe_z)
    logger.info("Generated profile program '%s': %d passes, %d points",
                name, passes, len(points))
    return program


def rectangle_points(
    length_mm: float, width_mm: float, origin: Tuple[float, float] = (0.0, 0.0)
) -> List[Tuple[float, float]]:
    """Corner points of an axis-aligned rectangle (for profile cutting)."""
    ox, oy = origin
    return [
        (ox, oy),
        (ox + length_mm, oy),
        (ox + length_mm, oy + width_mm),
        (ox, oy + width_mm),
    ]

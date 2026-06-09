# app/manufacturing/assembly.py
# Assembly sequence generation: step ordering, dependencies, time estimation

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

logger = logging.getLogger("engine.manufacturing.assembly")


class AssemblyMethod(str, Enum):
    """Primary assembly method for a step."""
    BOLT = "bolt"
    WELD = "weld"
    PRESS_FIT = "press_fit"
    SLIP_FIT = "slip_fit"
    ADHESIVE = "adhesive"
    RIVET = "rivet"
    INTERFERENCE = "interference"
    POSITION = "position"  # place component without fastening


@dataclass
class AssemblyStep:
    """A single step in the assembly sequence."""
    step_id: str
    description: str = ""
    component_ids: List[str] = field(default_factory=list)
    method: AssemblyMethod = AssemblyMethod.BOLT
    estimated_time_minutes: float = 5.0
    dependencies: List[str] = field(default_factory=list)
    station: str = "main"
    required_tools: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class AssemblySequence:
    """Generated assembly sequence."""
    steps: List[AssemblyStep] = field(default_factory=list)
    total_steps: int = 0
    total_time_minutes: float = 0.0
    total_time_hours: float = 0.0
    parallel_stations: int = 1
    critical_path_minutes: float = 0.0
    notes: List[str] = field(default_factory=list)
    passed: bool = True


class AssemblyAnalyzer:
    """Generates and validates assembly sequences."""

    def __init__(self, parallel_stations: int = 1):
        self.parallel_stations = parallel_stations

    def generate_sequence(
        self, steps: List[AssemblyStep]
    ) -> AssemblySequence:
        logger.info(
            "Generating assembly sequence for %d steps",
            len(steps),
        )

        if not steps:
            return AssemblySequence(
                notes=["No assembly steps provided"],
                passed=False,
            )

        validated = self._validate_dependencies(steps)

        sorted_steps = self._topological_sort(validated, steps)

        total_time = sum(s.estimated_time_minutes for s in sorted_steps)

        critical_time = self._estimate_critical_path(sorted_steps)

        station_load = total_time / self.parallel_stations

        notes = []
        if sorted_steps != validated:
            notes.append("Assembly sequence reordered to satisfy dependencies")

        if critical_time > 480:
            notes.append(
                f"Critical path ({critical_time:.1f} min) exceeds single shift"
            )

        if len(sorted_steps) < len(steps):
            notes.append(
                f"{len(steps) - len(sorted_steps)} steps excluded due to circular dependencies"
            )

        passed = len(sorted_steps) > 0

        logger.info(
            "Assembly sequence: %d steps, %.1f min total, %.1f min critical path",
            len(sorted_steps),
            total_time,
            critical_time,
        )

        return AssemblySequence(
            steps=sorted_steps,
            total_steps=len(sorted_steps),
            total_time_minutes=total_time,
            total_time_hours=total_time / 60.0,
            parallel_stations=self.parallel_stations,
            critical_path_minutes=critical_time,
            notes=notes,
            passed=passed,
        )

    def _validate_dependencies(
        self, steps: List[AssemblyStep]
    ) -> List[str]:
        """Validate that all dependencies reference existing steps."""
        step_ids = {s.step_id for s in steps}
        valid = []
        for s in steps:
            bad_deps = [d for d in s.dependencies if d not in step_ids]
            if bad_deps:
                logger.warning(
                    "Step %s has unresolved dependencies: %s",
                    s.step_id,
                    bad_deps,
                )
            else:
                valid.append(s.step_id)
        return valid

    def _topological_sort(
        self, valid_ids: List[str], all_steps: List[AssemblyStep]
    ) -> List[AssemblyStep]:
        """Simple topological sort based on dependencies."""
        step_map = {s.step_id: s for s in all_steps}
        visited: Set[str] = set()
        sorted_ids: List[str] = []

        def visit(node_id: str, path: Set[str]) -> None:
            if node_id in visited:
                return
            if node_id in path:
                logger.warning("Circular dependency detected involving %s", node_id)
                return
            step = step_map.get(node_id)
            if not step:
                return
            path.add(node_id)
            for dep_id in step.dependencies:
                if dep_id in step_map:
                    visit(dep_id, path)
            path.remove(node_id)
            visited.add(node_id)
            sorted_ids.append(node_id)

        for sid in valid_ids:
            visit(sid, set())

        return [step_map[sid] for sid in sorted_ids if sid in step_map]

    def _estimate_critical_path(self, steps: List[AssemblyStep]) -> float:
        """Estimate critical path duration using simple dependency chaining."""
        duration: Dict[str, float] = {}
        for s in steps:
            if not s.dependencies:
                duration[s.step_id] = s.estimated_time_minutes
            else:
                max_dep = max(
                    (duration.get(d, 0.0) for d in s.dependencies),
                    default=0.0,
                )
                duration[s.step_id] = max_dep + s.estimated_time_minutes
        return max(duration.values()) if duration else 0.0


def generate_assembly_sequence(
    steps: List[AssemblyStep],
    parallel_stations: int = 1,
) -> AssemblySequence:
    analyzer = AssemblyAnalyzer(parallel_stations=parallel_stations)
    return analyzer.generate_sequence(steps)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    sample_steps = [
        AssemblyStep(
            step_id="base_frame",
            description="Bolt base frame assembly to foundation",
            component_ids=["base_rail_l", "base_rail_r", "cross_member_1", "cross_member_2"],
            method=AssemblyMethod.BOLT,
            estimated_time_minutes=20.0,
        ),
        AssemblyStep(
            step_id="mount_bearings",
            description="Install bearing housings on base frame",
            component_ids=["bearing_l", "bearing_r"],
            method=AssemblyMethod.BOLT,
            estimated_time_minutes=15.0,
            dependencies=["base_frame"],
        ),
        AssemblyStep(
            step_id="install_rollers",
            description="Install compression rollers into bearings",
            component_ids=["roller_front", "roller_rear"],
            method=AssemblyMethod.SLIP_FIT,
            estimated_time_minutes=10.0,
            dependencies=["mount_bearings"],
        ),
        AssemblyStep(
            step_id="install_drive",
            description="Install drive motor and chain drive",
            component_ids=["motor", "chain", "sprockets"],
            method=AssemblyMethod.BOLT,
            estimated_time_minutes=25.0,
            dependencies=["base_frame"],
        ),
        AssemblyStep(
            step_id="wire_control",
            description="Wire control panel and sensors",
            component_ids=["control_panel", "sensors"],
            method=AssemblyMethod.BOLT,
            estimated_time_minutes=30.0,
            dependencies=["install_drive", "install_rollers"],
        ),
        AssemblyStep(
            step_id="safety_guards",
            description="Install safety guards and covers",
            component_ids=["guard_front", "guard_rear", "guard_side"],
            method=AssemblyMethod.BOLT,
            estimated_time_minutes=20.0,
            dependencies=["wire_control"],
        ),
    ]

    result = generate_assembly_sequence(sample_steps)

    print("=" * 60)
    print("Assembly Sequence Results")
    print("=" * 60)
    print(f"  Steps:                     {result.total_steps}")
    print(f"  Total Time:                {result.total_time_minutes:.1f} min ({result.total_time_hours:.2f} hrs)")
    print(f"  Critical Path:             {result.critical_path_minutes:.1f} min")
    print(f"  Parallel Stations:         {result.parallel_stations}")
    print(f"  Passed:                    {result.passed}")
    if result.notes:
        print(f"  Notes:                     {'; '.join(result.notes)}")

    print(f"\n  Assembly Sequence Order:")
    for i, step in enumerate(result.steps, 1):
        deps = f" (after: {', '.join(step.dependencies)})" if step.dependencies else ""
        print(f"    {i}. [{step.step_id}] {step.description}{deps}")

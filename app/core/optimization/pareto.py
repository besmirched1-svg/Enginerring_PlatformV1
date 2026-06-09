# app/core/optimization/pareto.py
# Pareto front analysis utilities: dominance checks, hypervolume, knee selection

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from .multi_objective_optimizer import Individual

logger = logging.getLogger("engine.core.optimization.pareto")


def check_dominance(
    objectives_a: List[float],
    objectives_b: List[float],
    minimize_flags: Optional[List[bool]] = None,
) -> int:
    """
    Check dominance relationship between two objective vectors.

    Args:
        objectives_a: Objective values for individual A.
        objectives_b: Objective values for individual B.
        minimize_flags: True=minimize, False=maximize per objective.
            Defaults to all minimize.

    Returns:
        1 if A dominates B, -1 if B dominates A, 0 if non-dominated.
    """
    if len(objectives_a) != len(objectives_b):
        raise ValueError("Objective vectors must have same length")

    n = len(objectives_a)
    if minimize_flags is None:
        minimize_flags = [True] * n

    a_better = False
    b_better = False

    for i in range(n):
        a = objectives_a[i]
        b = objectives_b[i]

        if minimize_flags[i]:
            a_wins = a < b
            b_wins = b < a
        else:
            a_wins = a > b
            b_wins = b > a

        if a_wins:
            a_better = True
        if b_wins:
            b_better = True

    if a_better and not b_better:
        return 1
    if b_better and not a_better:
        return -1
    return 0


def dominates(
    objectives_a: List[float],
    objectives_b: List[float],
    minimize_flags: Optional[List[bool]] = None,
) -> bool:
    """Returns True if A dominates B."""
    return check_dominance(objectives_a, objectives_b, minimize_flags) == 1


def compute_ideal_point(
    population: List[Individual],
    minimize_flags: Optional[List[bool]] = None,
) -> List[float]:
    """Compute the ideal point (best value for each objective) across a population."""
    if not population or not population[0].objectives:
        return []

    n = len(population[0].objectives)
    if minimize_flags is None:
        minimize_flags = [True] * n

    ideal = list(population[0].objectives)
    for ind in population[1:]:
        for i in range(n):
            if minimize_flags[i]:
                ideal[i] = min(ideal[i], ind.objectives[i])
            else:
                ideal[i] = max(ideal[i], ind.objectives[i])
    return ideal


def compute_nadir_point(
    population: List[Individual],
    minimize_flags: Optional[List[bool]] = None,
) -> List[float]:
    """Compute the nadir point (worst value for each objective) across a population."""
    if not population or not population[0].objectives:
        return []

    n = len(population[0].objectives)
    if minimize_flags is None:
        minimize_flags = [True] * n

    nadir = list(population[0].objectives)
    for ind in population[1:]:
        for i in range(n):
            if minimize_flags[i]:
                nadir[i] = max(nadir[i], ind.objectives[i])
            else:
                nadir[i] = min(nadir[i], ind.objectives[i])
    return nadir


def normalize_objectives(
    population: List[Individual],
    ideal: Optional[List[float]] = None,
    nadir: Optional[List[float]] = None,
) -> None:
    """Normalize objectives of all individuals to [0, 1] range in-place."""
    if not population:
        return

    if ideal is None:
        ideal = compute_ideal_point(population)
    if nadir is None:
        nadir = compute_nadir_point(population)

    n = len(ideal)
    for ind in population:
        for i in range(n):
            rng = nadir[i] - ideal[i]
            if rng > 0:
                ind.objectives[i] = (ind.objectives[i] - ideal[i]) / rng
            else:
                ind.objectives[i] = 0.5


def hypervolume(
    population: List[Individual],
    reference_point: Optional[List[float]] = None,
    minimize_flags: Optional[List[bool]] = None,
) -> float:
    """
    Approximate hypervolume indicator (hypervolume area) for a population.

    Uses a simple Monte Carlo approximation for >2 objectives, exact for 2D.

    Args:
        population: List of individuals.
        reference_point: Reference point for hypervolume calculation.
            If None, uses nadir point + 10%.
        minimize_flags: Per-objective minimize flags.

    Returns:
        Hypervolume indicator value.
    """
    if not population:
        return 0.0

    n = len(population[0].objectives)
    if minimize_flags is None:
        minimize_flags = [True] * n

    if reference_point is None:
        nadir = compute_nadir_point(population, minimize_flags)
        reference_point = [v * 1.1 + 1e-6 for v in nadir]

    obj_values = [list(ind.objectives) for ind in population]

    if n == 1:
        vals = [v[0] for v in obj_values]
        return max(vals) - min(vals) if vals else 0.0

    if n == 2:
        return _hypervolume_2d(obj_values, reference_point, minimize_flags)

    return _hypervolume_mc(obj_values, reference_point, minimize_flags, samples=10000)


def _hypervolume_2d(
    points: List[List[float]],
    reference: List[float],
    minimize_flags: List[bool],
) -> float:
    """Exact hypervolume for 2 objectives."""
    flipped = []
    for p in points:
        fp = []
        for i in range(2):
            if minimize_flags[i]:
                fp.append(reference[i] - p[i])
            else:
                fp.append(p[i] - reference[i])
        flipped.append(fp)

    flipped.sort(key=lambda x: x[0])

    area = 0.0
    prev_y = 0.0
    for x, y in flipped:
        if y > prev_y:
            area += (x - 0.0 if not prev_y else 0.0) * (y - prev_y)
            prev_y = y
    return area


def _hypervolume_mc(
    points: List[List[float]],
    reference: List[float],
    minimize_flags: List[bool],
    samples: int = 10000,
) -> float:
    """Monte Carlo hypervolume approximation for >2 objectives."""
    import random

    n = len(points[0])

    lows = []
    highs = []
    for i in range(n):
        vals = [p[i] for p in points]
        lows.append(min(vals))
        highs.append(max(vals))

    count = 0
    for _ in range(samples):
        pt = [random.uniform(lows[i], highs[i]) for i in range(n)]

        dominated = False
        for p in points:
            all_better = True
            for i in range(n):
                if minimize_flags[i]:
                    better = p[i] <= pt[i]
                else:
                    better = p[i] >= pt[i]
                if not better:
                    all_better = False
                    break
            if all_better:
                dominated = True
                break
        if dominated:
            count += 1

    vol = 1.0
    for i in range(n):
        vol *= highs[i] - lows[i]

    return vol * count / samples


def knee_selection(
    population: List[Individual],
    minimize_flags: Optional[List[bool]] = None,
) -> Tuple[int, Individual]:
    """
    Select the knee point from a Pareto front using the angle-based method.

    The knee point is the solution with the maximum convex angle to its
    neighbours on the Pareto front, representing the best trade-off.

    Args:
        population: List of Pareto-optimal individuals.
        minimize_flags: Per-objective minimize flags.

    Returns:
        Tuple of (index, individual) for the knee point.
    """
    if not population:
        raise ValueError("Empty population")

    n = len(population)
    if n == 1:
        return 0, population[0]

    if minimize_flags is None:
        minimize_flags = [True] * len(population[0].objectives)

    ideal = compute_ideal_point(population, minimize_flags)
    nadir = compute_nadir_point(population, minimize_flags)

    sorted_pop = sorted(population, key=lambda ind: ind.objectives[0])

    sorted_points = []
    for ind in sorted_pop:
        pt = []
        for i in range(len(ind.objectives)):
            rng = nadir[i] - ideal[i]
            if rng > 0:
                pt.append((ind.objectives[i] - ideal[i]) / rng)
            else:
                pt.append(0.5)
        sorted_points.append(pt)

    best_angle = -1.0
    best_idx = 0

    for i in range(n):
        if i == 0:
            v_prev = [sorted_points[i][j] - 0.0 for j in range(len(sorted_points[i]))]
        else:
            v_prev = [
                sorted_points[i - 1][j] - sorted_points[i][j]
                for j in range(len(sorted_points[i]))
            ]

        if i == n - 1:
            v_next = [1.0 - sorted_points[i][j] for j in range(len(sorted_points[i]))]
        else:
            v_next = [
                sorted_points[i + 1][j] - sorted_points[i][j]
                for j in range(len(sorted_points[i]))
            ]

        dot = sum(v_prev[j] * v_next[j] for j in range(len(v_prev)))
        mag_prev = math.sqrt(sum(v ** 2 for v in v_prev))
        mag_next = math.sqrt(sum(v ** 2 for v in v_next))

        if mag_prev > 0 and mag_next > 0:
            cos_angle = dot / (mag_prev * mag_next)
            cos_angle = max(-1.0, min(1.0, cos_angle))
            angle = math.acos(cos_angle)
        else:
            angle = 0.0

        if angle > best_angle:
            best_angle = angle
            best_idx = i

    original_idx = population.index(sorted_pop[best_idx])
    return original_idx, population[original_idx]


def pareto_ranking(population: List[Individual],
                   minimize_flags: Optional[List[bool]] = None) -> Dict[str, Any]:
    """
    Full Pareto ranking analysis for a population.

    Returns a dict with:
    - front_count: number of dominance fronts
    - front_sizes: list of sizes per front
    - ideal_point: best values for each objective
    - nadir_point: worst values for each objective
    - pareto_count: number of non-dominated solutions
    - pareto_fraction: fraction of population on Pareto front
    """
    from .multi_objective_optimizer import fast_nondominated_sort

    fronts = fast_nondominated_sort(population, minimize_flags=minimize_flags)
    ideal = compute_ideal_point(population, minimize_flags)
    nadir = compute_nadir_point(population, minimize_flags)

    pareto_count = len(fronts[0]) if fronts else 0

    return {
        "front_count": len(fronts),
        "front_sizes": [len(f) for f in fronts],
        "ideal_point": ideal,
        "nadir_point": nadir,
        "pareto_count": pareto_count,
        "pareto_fraction": pareto_count / len(population) if population else 0.0,
    }

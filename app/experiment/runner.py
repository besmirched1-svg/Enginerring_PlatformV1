from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from .design_generator import generate_samples, flat_to_nested_config
from .models import (
    ExperimentDefinition,
    ExperimentResult,
    ExperimentRun,
    ObjectiveDef,
)

logger = logging.getLogger("engine.experiment.runner")

# Default hemp decorticator objectives from multi-objective optimizer
DEFAULT_OBJECTIVES = [
    ObjectiveDef(name="fibre_recovery", minimize=False, weight=1.0),
    ObjectiveDef(name="fibre_quality", minimize=False, weight=1.0),
    ObjectiveDef(name="power_consumption", minimize=True, weight=1.0),
    ObjectiveDef(name="weight", minimize=True, weight=1.0),
    ObjectiveDef(name="cost", minimize=True, weight=1.0),
    ObjectiveDef(name="maintenance", minimize=True, weight=1.0),
    ObjectiveDef(name="failure_rate", minimize=True, weight=1.0),
]


def _evaluate_single_config(
    flat_params: Dict[str, float],
    machine_config: Dict[str, Any],
    objectives: List[ObjectiveDef],
) -> ExperimentRun:
    """Evaluate a single design variant across all objectives.

    Uses lightweight heuristics when the full Director pipeline is not
    available, matching the objective functions from
    multi_objective_optimizer.py.
    """
    run = ExperimentRun(
        run_id=f"run_{uuid.uuid4().hex[:8]}",
        parameters=flat_params,
        machine_config=machine_config,
    )

    try:
        # Extract key parameters
        drum_diam = flat_params.get("drum_diameter", 1000.0)
        drum_len = flat_params.get("drum_length", 3000.0)
        flight_thick = flat_params.get("flight_thickness", 12.0)
        flight_pitch = flat_params.get("flight_pitch", 150.0)
        shaft_diam = flat_params.get("shaft_diameter", 80.0)
        num_flights = flat_params.get("number_of_flights", 6.0)
        speed = flat_params.get("rotational_speed", 100.0)
        feed_rate = flat_params.get("feed_rate", 2000.0)
        moisture = flat_params.get("moisture_content", 15.0)
        uts = flat_params.get("steel_grade_uts", 500.0)

        # === Objective evaluations (mirrors multi_objective_optimizer.py) ===

        for obj in objectives:
            name = obj.name
            if name == "fibre_recovery":
                # Higher drum diameter + lower speed = better recovery
                # Diminishing returns above 1200mm
                recovery = 0.65 + 0.3 * min(1.0, drum_diam / 1600.0)
                recovery -= 0.15 * max(0.0, (speed - 80.0) / 120.0)
                recovery += 0.05 * min(1.0, moisture / 20.0)
                run.objective_values[name] = round(min(1.0, max(0.0, recovery)), 4)

            elif name == "fibre_quality":
                # Lower speed, moderate moisture = better quality
                quality = 0.7 + 0.15 * max(0.0, 1.0 - speed / 150.0)
                quality += 0.1 * (1.0 - abs(moisture - 14.0) / 20.0)
                quality -= 0.05 * min(1.0, feed_rate / 4000.0)
                run.objective_values[name] = round(min(1.0, max(0.0, quality)), 4)

            elif name == "power_consumption":
                # Power scales with drum size, speed, feed rate
                drum_volume = 3.14159 * (drum_diam / 2) ** 2 * drum_len / 1e9  # m^3
                inertia_factor = drum_volume * (speed / 60.0) ** 2
                power = 5.0 + 0.5 * inertia_factor + 0.002 * feed_rate
                run.objective_values[name] = round(power, 2)

            elif name == "weight":
                # Weight estimate from drum + shaft + flights
                drum_vol = 3.14159 * drum_diam * flight_thick * drum_len / 1e9  # m^3
                shaft_vol = 3.14159 * (shaft_diam / 2) ** 2 * drum_len / 1e9
                flight_vol = num_flights * flight_thick * (drum_diam / 2) * drum_len / 1e9
                total_vol = drum_vol + shaft_vol + flight_vol
                mass_kg = total_vol * 7850  # steel density kg/m^3
                run.objective_values[name] = round(mass_kg, 1)

            elif name == "cost":
                # Relative cost based on mass, manufacturing complexity
                mass = run.objective_values.get("weight", 1000.0)
                complexity = 1.0 + 0.5 * (num_flights / 6.0) + 0.3 * (drum_diam / 1000.0)
                cost = mass * 4.5 * complexity  # $4.50/kg base fabrication
                run.objective_values[name] = round(cost, 0)

            elif name == "maintenance":
                # Maintenance score: higher for complex, high-speed designs
                maint = 0.2 + 0.4 * (speed / 200.0) + 0.2 * (num_flights / 12.0)
                maint += 0.2 * min(1.0, feed_rate / 5000.0)
                run.objective_values[name] = round(min(1.0, maint), 4)

            elif name == "failure_rate":
                # Failure rate proxy: inversely related to shaft size, UTS
                # Higher is worse (more failures)
                failure = 0.05 + 0.3 * max(0.0, 1.0 - shaft_diam / 120.0)
                failure += 0.2 * max(0.0, 1.0 - uts / 600.0)
                failure += 0.1 * min(1.0, speed / 200.0)
                run.objective_values[name] = round(min(1.0, failure), 4)

            else:
                logger.warning("Unknown objective: %s", name)
                run.objective_values[name] = 0.0

        # Calculate composite evaluation score with robust normalization.
        # Known objective ranges for normalization:
        obj_ranges = {
            "fibre_recovery": (0.0, 1.0),
            "fibre_quality": (0.0, 1.0),
            "power_consumption": (0.0, 500.0),
            "weight": (0.0, 30000.0),
            "cost": (0.0, 200000.0),
            "maintenance": (0.0, 1.0),
            "failure_rate": (0.0, 1.0),
        }
        score_sum = 0.0
        for obj in objectives:
            raw = run.objective_values.get(obj.name, 0.0)
            lo, hi = obj_ranges.get(obj.name, (0.0, 1.0))
            norm = (raw - lo) / max(hi - lo, 1e-6)
            norm = max(0.0, min(1.0, norm))
            if obj.minimize:
                norm = 1.0 - norm
            score_sum += norm
        run.evaluation_score = round(score_sum / max(len(objectives), 1), 4)
        run.passed = True

    except Exception as exc:
        logger.exception("Failed to evaluate config: %s", flat_params)
        run.passed = False
        run.errors.append(str(exc))

    return run


def _build_pareto_ranking(
    runs: List[ExperimentRun],
    objectives: List[ObjectiveDef],
) -> List[ExperimentRun]:
    """Rank runs by Pareto dominance.

    Returns runs sorted by Pareto front (front 0 = non-dominated).
    """
    if not runs or not objectives:
        return runs[:]

    n = len(runs)
    minimize_flags = [obj.minimize for obj in objectives]
    obj_names = [obj.name for obj in objectives]

    # Compute dominance
    dominated_count = [0] * n
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            i_vec = [runs[i].objective_values.get(n, 0.0) for n in obj_names]
            j_vec = [runs[j].objective_values.get(n, 0.0) for n in obj_names]
            i_better = False
            j_better = False
            for k in range(len(obj_names)):
                a = i_vec[k]
                b = j_vec[k]
                if minimize_flags[k]:
                    a_wins = a < b
                    b_wins = b < a
                else:
                    a_wins = a > b
                    b_wins = b > a
                if a_wins:
                    i_better = True
                if b_wins:
                    j_better = True
            if i_better and not j_better:
                dominated_count[j] += 1

    # Assign rank (0 = non-dominated)
    ranked = list(zip(runs, dominated_count))
    ranked.sort(key=lambda x: x[1])
    return [r for r, _ in ranked]


def _find_champion(ranked: List[ExperimentRun], objectives: List[ObjectiveDef]) -> Optional[ExperimentRun]:
    """Select champion from Pareto front by best average score."""
    if not ranked:
        return None
    # First front (non-dominated)
    front0 = [r for r in ranked if r.passed]
    if not front0:
        return None
    # Pick by best evaluation score
    return max(front0, key=lambda r: r.evaluation_score)


def run_experiment(
    definition: ExperimentDefinition,
    on_status: Optional[Callable[[str, float, str], None]] = None,
) -> ExperimentResult:
    """Run a full engineering experiment.

    Args:
        definition: Experiment definition with parameter ranges and objectives.
        on_status: Optional callback for progress updates.

    Returns:
        ExperimentResult with all runs, Pareto ranking, and champion.
    """
    exp_id = f"exp_{uuid.uuid4().hex[:12]}"
    logger.info("Starting experiment %s: %s", exp_id, definition.name)

    result = ExperimentResult(
        experiment_id=exp_id,
        definition=definition,
    )

    if not definition.objectives:
        definition.objectives = DEFAULT_OBJECTIVES

    if on_status:
        on_status("sampling", 0.05, "Generating design variants")

    # Step 1: Generate parameter samples
    samples = generate_samples(definition)
    total = len(samples)
    logger.info("Generated %d samples for experiment %s", total, exp_id)

    if on_status:
        on_status("sampling", 0.1, f"Generated {total} design variants")

    # Step 2: Evaluate each sample
    runs: List[ExperimentRun] = []
    for idx, flat_params in enumerate(samples):
        try:
            if on_status and idx % max(1, total // 20) == 0:
                progress = 0.1 + 0.7 * (idx / total)
                on_status("evaluating", progress, f"Evaluating variant {idx + 1}/{total}")

            machine_config = flat_to_nested_config(flat_params, definition.machine_type)
            run = _evaluate_single_config(flat_params, machine_config, definition.objectives)
            runs.append(run)

        except Exception as exc:
            logger.exception("Failed on variant %d", idx)
            failed_run = ExperimentRun(
                run_id=f"run_{uuid.uuid4().hex[:8]}",
                parameters=flat_params,
                passed=False,
                errors=[str(exc)],
            )
            runs.append(failed_run)

    result.runs = runs
    result.total_runs = len(runs)
    result.successful_runs = sum(1 for r in runs if r.passed)
    result.failed_runs = sum(1 for r in runs if not r.passed)

    if on_status:
        on_status("pareto", 0.85, f"Building Pareto ranking ({result.successful_runs} successful)")

    # Step 3: Pareto ranking
    successful_runs = [r for r in runs if r.passed]
    result.pareto_ranked = _build_pareto_ranking(successful_runs, definition.objectives)
    result.champion = _find_champion(result.pareto_ranked, definition.objectives)

    if on_status:
        on_status("report", 0.95, "Generating research report")

    # Step 4: Generate summary
    champion_name = "None"
    champion_score = 0.0
    if result.champion:
        champion_name = result.champion.run_id
        champion_score = result.champion.evaluation_score

    result.report_summary = (
        f"Experiment '{definition.name}': {result.total_runs} variants "
        f"({result.successful_runs} successful, {result.failed_runs} failed). "
        f"Pareto front: {len(result.pareto_ranked)} non-dominated solutions. "
        f"Champion: {champion_name} (score={champion_score:.4f})."
    )
    logger.info("Experiment %s complete: %s", exp_id, result.report_summary)

    if on_status:
        on_status("complete", 1.0, "Experiment complete")

    return result

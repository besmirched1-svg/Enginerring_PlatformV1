from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("engine.evolution.nsga2")

# ---------------------------------------------------------------------------
# Parameter bounds for hemp decorticator design space
# ---------------------------------------------------------------------------

PARAM_BOUNDS: Dict[str, Tuple[float, float]] = {
    "drum_diameter":     (800.0, 2000.0),
    "drum_length":       (1000.0, 5000.0),
    "flight_thickness":  (8.0, 25.0),
    "flight_pitch":      (50.0, 300.0),
    "shaft_diameter":    (30.0, 150.0),
    "number_of_flights": (2.0, 12.0),
    "rotational_speed":  (20.0, 200.0),
    "feed_rate":         (500.0, 5000.0),
    "moisture_content":  (5.0, 30.0),
    "steel_grade_uts":   (300.0, 800.0),
    "steel_grade_ys":    (200.0, 500.0),
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Individual:
    design_vector: Dict[str, float] = field(default_factory=dict)
    objective_values: List[float] = field(default_factory=list)
    objective_names: List[str] = field(default_factory=list)
    rank: int = -1
    crowding_distance: float = 0.0
    run_id: str = ""


@dataclass
class EvoParams:
    population_size: int = 50
    generations: int = 20
    crossover_prob: float = 0.9
    mutation_prob: float = 0.1
    eta_c: float = 15.0
    eta_m: float = 20.0


@dataclass
class ParetoFrontInfo:
    front_index: int = 0
    individuals: List[Individual] = field(default_factory=list)
    objective_names: List[str] = field(default_factory=list)


def create_default_evolution_params() -> EvoParams:
    return EvoParams()


def nsga2_individual_to_dict(ind: Individual) -> Dict[str, Any]:
    obj_names = ind.objective_names or [f"obj_{i}" for i in range(len(ind.objective_values))]
    cd = ind.crowding_distance
    if cd == float("inf") or cd == float("-inf"):
        cd = None
    else:
        cd = round(cd, 6)
    return {
        "run_id": ind.run_id,
        "rank": ind.rank,
        "crowding_distance": cd,
        "design_vector": {k: round(v, 2) for k, v in ind.design_vector.items()},
        "objectives": {
            name: round(val, 4)
            for name, val in zip(obj_names, ind.objective_values)
        },
    }


# ---------------------------------------------------------------------------
# Fast non-dominated sort  (O(M N^2))
# ---------------------------------------------------------------------------

def fast_non_dominated_sort(
    individuals: List[Individual],
    minimize_flags: List[bool],
) -> List[List[int]]:
    n = len(individuals)
    if n == 0:
        return []

    domination_set: List[List[int]] = [[] for _ in range(n)]
    dominated_count = [0] * n

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            i_wins = True
            j_wins = True
            for k, minimize in enumerate(minimize_flags):
                a = individuals[i].objective_values[k]
                b = individuals[j].objective_values[k]
                if minimize:
                    if a > b:
                        i_wins = False
                    if b > a:
                        j_wins = False
                else:
                    if a < b:
                        i_wins = False
                    if b < a:
                        j_wins = False
            if i_wins and not j_wins:
                domination_set[i].append(j)
            elif j_wins and not i_wins:
                dominated_count[i] += 1

    fronts: List[List[int]] = []
    current = [i for i in range(n) if dominated_count[i] == 0]

    while current:
        fronts.append(current)
        next_front: List[int] = []
        for i in current:
            for j in domination_set[i]:
                dominated_count[j] -= 1
                if dominated_count[j] == 0:
                    next_front.append(j)
        current = next_front

    return fronts


# ---------------------------------------------------------------------------
# Crowding distance
# ---------------------------------------------------------------------------

def crowding_distance(
    individuals: List[Individual],
    front_indices: List[int],
    minimize_flags: List[bool],
) -> List[float]:
    m = len(minimize_flags)
    distances = {idx: 0.0 for idx in front_indices}

    for k in range(m):
        sorted_idx = sorted(front_indices, key=lambda idx: individuals[idx].objective_values[k])
        lo = individuals[sorted_idx[0]].objective_values[k]
        hi = individuals[sorted_idx[-1]].objective_values[k]
        rng = hi - lo
        if rng < 1e-12:
            continue
        distances[sorted_idx[0]] = float("inf")
        distances[sorted_idx[-1]] = float("inf")
        for i in range(1, len(sorted_idx) - 1):
            prev_val = individuals[sorted_idx[i - 1]].objective_values[k]
            next_val = individuals[sorted_idx[i + 1]].objective_values[k]
            distances[sorted_idx[i]] += (next_val - prev_val) / rng

    return [distances[i] for i in front_indices]


# ---------------------------------------------------------------------------
# Tournament selection  (binary, by rank then crowding distance)
# ---------------------------------------------------------------------------

def tournament_select(
    individuals: List[Individual],
    tournament_size: int = 2,
) -> int:
    n = len(individuals)
    best = random.randrange(n)
    for _ in range(tournament_size - 1):
        contender = random.randrange(n)
        if individuals[contender].rank < individuals[best].rank:
            best = contender
        elif (individuals[contender].rank == individuals[best].rank
              and individuals[contender].crowding_distance > individuals[best].crowding_distance):
            best = contender
    return best


# ---------------------------------------------------------------------------
# SBX crossover
# ---------------------------------------------------------------------------

def sbx_crossover(
    p1_vec: Dict[str, float],
    p2_vec: Dict[str, float],
    bounds: Dict[str, Tuple[float, float]],
    eta_c: float = 15.0,
    crossover_prob: float = 0.9,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    c1: Dict[str, float] = {}
    c2: Dict[str, float] = {}
    for param, (lo, hi) in bounds.items():
        x1 = p1_vec.get(param, (lo + hi) / 2)
        x2 = p2_vec.get(param, (lo + hi) / 2)
        if random.random() <= crossover_prob and abs(x1 - x2) > 1e-10:
            if x1 > x2:
                x1, x2 = x2, x1
            beta = 1.0 + 2.0 * (x1 - lo) / max(x2 - x1, 1e-10)
            alpha = 2.0 - beta ** (-(eta_c + 1.0))
            u = random.random()
            if u <= 1.0 / alpha:
                beta_q = (u * alpha) ** (1.0 / (eta_c + 1.0))
            else:
                beta_q = (1.0 / (2.0 - u * alpha)) ** (1.0 / (eta_c + 1.0))
            c1v = 0.5 * ((x1 + x2) - beta_q * (x2 - x1))
            beta = 1.0 + 2.0 * (hi - x2) / max(x2 - x1, 1e-10)
            alpha = 2.0 - beta ** (-(eta_c + 1.0))
            u = random.random()
            if u <= 1.0 / alpha:
                beta_q = (u * alpha) ** (1.0 / (eta_c + 1.0))
            else:
                beta_q = (1.0 / (2.0 - u * alpha)) ** (1.0 / (eta_c + 1.0))
            c2v = 0.5 * ((x1 + x2) + beta_q * (x2 - x1))
            c1[param] = max(lo, min(hi, c1v))
            c2[param] = max(lo, min(hi, c2v))
        else:
            c1[param] = x1
            c2[param] = x2
    return c1, c2


# ---------------------------------------------------------------------------
# Polynomial mutation
# ---------------------------------------------------------------------------

def polynomial_mutation(
    vec: Dict[str, float],
    bounds: Dict[str, Tuple[float, float]],
    eta_m: float = 20.0,
    mutation_prob: float = 0.1,
) -> Dict[str, float]:
    mutated = dict(vec)
    for param, (lo, hi) in bounds.items():
        if random.random() >= mutation_prob:
            continue
        y = mutated.get(param, (lo + hi) / 2)
        delta1 = (y - lo) / max(hi - lo, 1e-10)
        delta2 = (hi - y) / max(hi - lo, 1e-10)
        u = random.random()
        if u <= 0.5:
            xy = 1.0 - delta1
            val = 2.0 * u + (1.0 - 2.0 * u) * (xy ** (eta_m + 1.0))
            deltaq = val ** (1.0 / (eta_m + 1.0)) - 1.0
        else:
            xy = 1.0 - delta2
            val = 2.0 * (1.0 - u) + 2.0 * (u - 0.5) * (xy ** (eta_m + 1.0))
            deltaq = 1.0 - val ** (1.0 / (eta_m + 1.0))
        y_new = y + deltaq * (hi - lo)
        mutated[param] = max(lo, min(hi, y_new))
    return mutated


# ---------------------------------------------------------------------------
# 10-objective evaluation for hemp decorticator
# ---------------------------------------------------------------------------

OBJECTIVE_NAMES_10 = [
    "fibre_recovery",
    "fibre_quality",
    "throughput",
    "power_consumption",
    "weight",
    "capital_cost",
    "operating_cost",
    "maintenance",
    "reliability",
    "mtbf",
]

MINIMIZE_FLAGS_10 = [
    False,  # fibre_recovery (maximize)
    False,  # fibre_quality (maximize)
    False,  # throughput (maximize)
    True,   # power_consumption (minimize)
    True,   # weight (minimize)
    True,   # capital_cost (minimize)
    True,   # operating_cost (minimize)
    True,   # maintenance (minimize)
    False,  # reliability (maximize)
    False,  # mtbf (maximize)
]


def evaluate_10_objectives(params: Dict[str, float]) -> List[float]:
    dd = params.get("drum_diameter", 1200.0)
    dl = params.get("drum_length", 3000.0)
    ft = params.get("flight_thickness", 12.0)
    fp = params.get("flight_pitch", 150.0)
    sd = params.get("shaft_diameter", 80.0)
    nf = params.get("number_of_flights", 6.0)
    sp = params.get("rotational_speed", 100.0)
    fr = params.get("feed_rate", 2000.0)
    mc = params.get("moisture_content", 15.0)
    uts = params.get("steel_grade_uts", 500.0)

    # ---- fibre_recovery (0-1, higher is better) ----
    recovery = 0.65 + 0.3 * min(1.0, dd / 1600.0)
    recovery -= 0.15 * max(0.0, (sp - 80.0) / 120.0)
    recovery += 0.05 * min(1.0, mc / 20.0)
    fibre_recovery = max(0.0, min(1.0, recovery))

    # ---- fibre_quality (0-1, higher is better) ----
    quality = 0.7 + 0.15 * max(0.0, 1.0 - sp / 150.0)
    quality += 0.1 * (1.0 - abs(mc - 14.0) / 20.0)
    quality -= 0.05 * min(1.0, fr / 4000.0)
    fibre_quality = max(0.0, min(1.0, quality))

    # ---- throughput (kg/hr, higher is better) ----
    drum_vol_m3 = math.pi * (dd / 2000.0) ** 2 * (dl / 1000.0)
    residence_time = dl / max(1.0, math.pi * dd * sp / 60000.0) / 1000.0
    fill_efficiency = 0.3 + 0.4 * min(1.0, dd / 1600.0)
    throughput = fr * fill_efficiency * (1.0 - 0.1 * max(0.0, 1.0 - mc / 10.0))
    # Cap throughput based on drum volume
    max_throughput = drum_vol_m3 * 7850.0 * 0.5
    throughput = min(throughput, max_throughput)

    # ---- power_consumption (kW, lower is better) ----
    inertia = drum_vol_m3 * 7850.0 * (dd / 2000.0) ** 2 * 0.5
    omega = sp * math.pi / 30.0
    power_kw = (inertia * omega / 10.0 + fr * 0.01) / 1000.0 + 5.0
    power_consumption = max(0.1, power_kw)

    # ---- weight (kg, lower is better) ----
    drum_vol = math.pi * dd * ft * dl / 1e9
    shaft_vol = math.pi * (sd / 2.0) ** 2 * dl / 1e9
    flight_vol = nf * ft * (dd / 2.0) * dl / 1e9
    total_vol = drum_vol + shaft_vol + flight_vol
    weight = total_vol * 7850.0

    # ---- capital_cost ($, lower is better) ----
    complexity = 1.0 + 0.5 * (nf / 6.0) + 0.3 * (dd / 1000.0)
    capital_cost = weight * 4.5 * complexity

    # ---- operating_cost ($/hr, lower is better) ----
    energy_cost = power_consumption * 0.15
    maintenance_labor = 2.0 + 0.5 * (sp / 100.0) + 0.3 * (nf / 6.0)
    operating_cost = energy_cost + maintenance_labor

    # ---- maintenance (0-1 score, lower is better) ----
    maint = 0.2 + 0.4 * (sp / 200.0) + 0.2 * (nf / 12.0) + 0.2 * min(1.0, fr / 5000.0)
    maintenance = min(1.0, maint)

    # ---- reliability (0-1, higher is better) ----
    stress_ratio = 0.3 + 0.4 * max(0.0, 1.0 - sd / 120.0)
    stress_ratio += 0.3 * max(0.0, 1.0 - uts / 600.0)
    reliability = max(0.0, min(1.0, 1.0 - stress_ratio))

    # ---- mtbf (hours, higher is better) ----
    base_mtbf = 5000.0 * (sd / 80.0) * (uts / 500.0)
    speed_factor = max(0.3, 1.0 - (sp - 60.0) / 200.0)
    mtbf = base_mtbf * speed_factor
    mtbf = max(500.0, mtbf)

    return [
        fibre_recovery,
        fibre_quality,
        throughput,
        power_consumption,
        weight,
        capital_cost,
        operating_cost,
        maintenance,
        reliability,
        mtbf,
    ]


# ---------------------------------------------------------------------------
# Main NSGA-II loop
# ---------------------------------------------------------------------------

def _initialize_population(
    pop_size: int,
    bounds: Dict[str, Tuple[float, float]],
    seed: Optional[int] = None,
) -> List[Dict[str, float]]:
    rng = random.Random(seed) if seed is not None else random
    population = []
    for _ in range(pop_size):
        vec = {}
        for param, (lo, hi) in bounds.items():
            vec[param] = round(lo + rng.random() * (hi - lo), 2)
        population.append(vec)
    return population


def run_nsga2(
    evaluate_func: Callable[[Dict[str, float]], List[float]],
    objective_names: List[str],
    minimize_flags: List[bool],
    bounds: Dict[str, Tuple[float, float]],
    params: EvoParams = EvoParams(),
    seed: Optional[int] = None,
    callback: Optional[Callable[[int, List[Individual]], None]] = None,
) -> Tuple[List[Individual], List[List[Individual]]]:
    """Run the NSGA-II algorithm.

    Args:
        evaluate_func: Function that takes a design vector and returns objective values.
        objective_names: Names of objectives.
        minimize_flags: True = minimize, False = maximize.
        bounds: Parameter bounds {name: (lo, hi)}.
        params: Evolution parameters.
        seed: Random seed (optional).
        callback: Called each generation with (gen, population).

    Returns:
        (pareto_front, all_generations)
    """
    pop_size = params.population_size
    n_gen = params.generations

    # Step 1: Initialize population
    design_vectors = _initialize_population(pop_size, bounds, seed=seed)

    # Create individuals and evaluate
    population: List[Individual] = []
    for dv in design_vectors:
        ind = Individual(design_vector=dv, objective_names=objective_names)
        ind.objective_values = evaluate_func(dv)
        population.append(ind)

    all_generations: List[List[Individual]] = [list(population)]

    for gen in range(n_gen):
        # Non-dominated sort
        fronts = fast_non_dominated_sort(population, minimize_flags)

        # Assign ranks
        for fi, front in enumerate(fronts):
            for idx in front:
                population[idx].rank = fi

        # Crowding distance for each front
        for front in fronts:
            distances = crowding_distance(population, front, minimize_flags)
            for idx, dist in zip(front, distances):
                population[idx].crowding_distance = dist

        # Tournament selection -> mating pool (indices)
        mating_pool = [
            tournament_select(population)
            for _ in range(pop_size)
        ]

        # Crossover + mutation -> offspring
        offspring: List[Individual] = []
        for i in range(0, pop_size, 2):
            if i + 1 >= pop_size:
                break
            p1_idx = mating_pool[i]
            p2_idx = mating_pool[i + 1]
            c1_vec, c2_vec = sbx_crossover(
                population[p1_idx].design_vector,
                population[p2_idx].design_vector,
                bounds,
                eta_c=params.eta_c,
                crossover_prob=params.crossover_prob,
            )
            c1_vec = polynomial_mutation(c1_vec, bounds, eta_m=params.eta_m, mutation_prob=params.mutation_prob)
            c2_vec = polynomial_mutation(c2_vec, bounds, eta_m=params.eta_m, mutation_prob=params.mutation_prob)
            c1 = Individual(design_vector=c1_vec, objective_names=objective_names)
            c1.objective_values = evaluate_func(c1_vec)
            c2 = Individual(design_vector=c2_vec, objective_names=objective_names)
            c2.objective_values = evaluate_func(c2_vec)
            offspring.extend([c1, c2])

        # Combine parent + offspring (2N)
        combined = population + offspring

        # Non-dominated sort on combined
        combined_fronts = fast_non_dominated_sort(combined, minimize_flags)

        # Build next population by selecting best N from combined
        next_pop: List[Individual] = []
        for front in combined_fronts:
            front_inds = [combined[i] for i in front]
            if len(next_pop) + len(front_inds) <= pop_size:
                for fi_idx in front:
                    combined[fi_idx].rank = len(combined_fronts) - combined_fronts.index(front)
                front_distances = crowding_distance(combined, front, minimize_flags)
                for fi_idx, dist in zip(front, front_distances):
                    combined[fi_idx].crowding_distance = dist
                next_pop.extend(front_inds)
            else:
                remaining = pop_size - len(next_pop)
                if remaining > 0:
                    front_distances = crowding_distance(combined, front, minimize_flags)
                    for fi_idx, dist in zip(front, front_distances):
                        combined[fi_idx].crowding_distance = dist
                    front_sorted = sorted(
                        zip(front, front_inds),
                        key=lambda x: combined[x[0]].crowding_distance,
                        reverse=True,
                    )
                    for _, ind in front_sorted[:remaining]:
                        next_pop.append(ind)
                break

        population = next_pop
        all_generations.append([Individual(
            design_vector=dict(ind.design_vector),
            objective_values=list(ind.objective_values),
            objective_names=list(ind.objective_names),
            rank=ind.rank,
            crowding_distance=ind.crowding_distance,
        ) for ind in population])

        if callback:
            callback(gen, population)

    # Final non-dominated sort to get Pareto front
    final_fronts = fast_non_dominated_sort(population, minimize_flags)
    if final_fronts:
        pareto_front = [population[i] for i in final_fronts[0]]
    else:
        pareto_front = []

    logger.info(
        "NSGA-II complete: %d generations, Pareto front size %d",
        n_gen, len(pareto_front),
    )

    return pareto_front, all_generations


# ---------------------------------------------------------------------------
# Knee analysis
# ---------------------------------------------------------------------------

def knee_analysis(
    pareto_front: List[Individual],
    minimize_flags: List[bool],
) -> Dict[str, Any]:
    if not pareto_front:
        return {"knee_index": -1, "knee": None, "ideal": [], "nadir": []}

    n = len(minimize_flags)
    m = len(pareto_front)

    # Ideal and nadir points
    vals_by_obj = [[ind.objective_values[i] for ind in pareto_front] for i in range(n)]
    ideal = []
    nadir = []
    for i in range(n):
        if minimize_flags[i]:
            ideal.append(min(vals_by_obj[i]))
            nadir.append(max(vals_by_obj[i]))
        else:
            ideal.append(max(vals_by_obj[i]))
            nadir.append(min(vals_by_obj[i]))

    # Normalize to [0,1] where 0 = ideal, 1 = nadir
    norm_values: List[List[float]] = []
    for ind in pareto_front:
        norm = []
        for i in range(n):
            rng = nadir[i] - ideal[i]
            if abs(rng) < 1e-12:
                norm.append(0.5)
            else:
                if minimize_flags[i]:
                    norm.append((ind.objective_values[i] - ideal[i]) / rng)
                else:
                    norm.append((nadir[i] - ind.objective_values[i]) / rng)
        norm_values.append(norm)

    # Knee = point with minimum distance to ideal in normalized space
    best_dist = float("inf")
    best_idx = 0
    for i in range(m):
        dist = sum(v ** 2 for v in norm_values[i]) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best_idx = i

    def _safe_round(v: float) -> float:
        if v == float("inf") or v == float("-inf"):
            return 0.0
        return round(v, 4)

    return {
        "knee_index": best_idx,
        "knee": nsga2_individual_to_dict(pareto_front[best_idx]),
        "ideal": [_safe_round(v) for v in ideal],
        "nadir": [_safe_round(v) for v in nadir],
    }


# ---------------------------------------------------------------------------
# Pareto front data for visualization
# ---------------------------------------------------------------------------

def pareto_front_data(
    pareto_front: List[Individual],
    objective_names: List[str],
    minimize_flags: List[bool],
) -> Dict[str, Any]:
    knee_info = knee_analysis(pareto_front, minimize_flags)
    return {
        "front_size": len(pareto_front),
        "objective_names": objective_names,
        "minimize_flags": minimize_flags,
        "ideal_point": knee_info["ideal"],
        "nadir_point": knee_info["nadir"],
        "knee": knee_info["knee"],
        "knee_index": knee_info["knee_index"],
        "solutions": [nsga2_individual_to_dict(ind) for ind in pareto_front],
    }


# ---------------------------------------------------------------------------
# Convenience: run NSGA-II with default hemp decorticator objectives
# ---------------------------------------------------------------------------

def run_hemp_evolution(
    population_size: int = 50,
    generations: int = 20,
    seed: Optional[int] = None,
) -> Tuple[List[Individual], Dict[str, Any]]:
    params = EvoParams(population_size=population_size, generations=generations)
    pareto_front, all_generations = run_nsga2(
        evaluate_func=evaluate_10_objectives,
        objective_names=OBJECTIVE_NAMES_10,
        minimize_flags=MINIMIZE_FLAGS_10,
        bounds=PARAM_BOUNDS,
        params=params,
        seed=seed,
    )
    front_data = pareto_front_data(pareto_front, OBJECTIVE_NAMES_10, MINIMIZE_FLAGS_10)
    return pareto_front, front_data


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Running NSGA-II on hemp decorticator (10 objectives)...")
    front, data = run_hemp_evolution(population_size=30, generations=5, seed=42)
    print(f"Pareto front size: {len(front)}")
    print(f"Knee index: {data['knee_index']}")
    if data["knee"]:
        print(f"Knee objectives: {data['knee']['objectives']}")
    print("Done.")

from __future__ import annotations

import copy
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .bottleneck import analyze_bottleneck
from .energy_balance import solve_energy_balance
from .layout import auto_layout
from .mass_balance import solve_mass_balance
from .models import FactoryProcessGraph, ProcessStream, ProcessUnit, ProcessUnitType, StreamType
from .validation import clamp_factory_input, validate_factory_graph

logger = logging.getLogger("engine.factory.optimization")

UnitMutator = Callable[[ProcessUnit], ProcessUnit]


@dataclass
class FactoryIndividual:
    graph: FactoryProcessGraph
    fitness: Dict[str, float] = field(default_factory=dict)
    constraints_ok: bool = True
    constraint_violations: List[str] = field(default_factory=list)
    rank: int = 0
    crowding_distance: float = 0.0

    def copy(self) -> FactoryIndividual:
        g = FactoryProcessGraph(
            graph_id=self.graph.graph_id,
            name=self.graph.name,
            units={k: ProcessUnit(**{**v.__dict__, "unit_type": v.unit_type}) for k, v in self.graph.units.items()},
            streams={k: ProcessStream(**{**v.__dict__, "stream_type": v.stream_type}) for k, v in self.graph.streams.items()},
            feed_streams=list(self.graph.feed_streams),
            product_streams=list(self.graph.product_streams),
            waste_streams=list(self.graph.waste_streams),
            metadata=dict(self.graph.metadata),
        )
        return FactoryIndividual(
            graph=g,
            fitness=dict(self.fitness),
            constraints_ok=self.constraints_ok,
            constraint_violations=list(self.constraint_violations),
        )


_FACTORY_OBJECTIVES = [
    "throughput_kg_hr",
    "yield_pct",
    "energy_kwh_per_kg",
    "utilization_pct",
    "oee_score",
    "layout_efficiency",
    "capital_cost",
    "bottleneck_slack",
]


def default_mutators() -> Dict[str, UnitMutator]:
    def _mutate_efficiency(unit: ProcessUnit) -> ProcessUnit:
        unit.efficiency = max(0.5, min(1.0, unit.efficiency + random.gauss(0, 0.03)))
        return unit

    def _mutate_power(unit: ProcessUnit) -> ProcessUnit:
        unit.power_kw = max(0, unit.power_kw * random.uniform(0.85, 1.15))
        return unit

    def _mutate_capacity(unit: ProcessUnit) -> ProcessUnit:
        unit.max_capacity_kg_hr = max(10, unit.max_capacity_kg_hr * random.uniform(0.8, 1.2))
        return unit

    return {
        "efficiency": _mutate_efficiency,
        "power": _mutate_power,
        "capacity": _mutate_capacity,
    }


def evaluate_factory(
    individual: FactoryIndividual,
    feed_rate_kg_hr: float = 1000.0,
    mass_balance_fn: Optional[Callable] = None,
    energy_balance_fn: Optional[Callable] = None,
    bottleneck_fn: Optional[Callable] = None,
    layout_fn: Optional[Callable] = None,
) -> FactoryIndividual:
    if mass_balance_fn is None:
        mass_balance_fn = solve_mass_balance
    if energy_balance_fn is None:
        energy_balance_fn = solve_energy_balance
    if bottleneck_fn is None:
        bottleneck_fn = analyze_bottleneck
    if layout_fn is None:
        layout_fn = auto_layout

    mb = mass_balance_fn(individual.graph, feed_rate_kg_hr)
    eb = energy_balance_fn(individual.graph, mb.product_rate_kg_hr)
    bn = bottleneck_fn(individual.graph, feed_rate_kg_hr)
    lo = layout_fn(individual.graph)

    througput = mb.product_rate_kg_hr
    energy_per_kg = eb.specific_energy_kwh_kg if mb.product_rate_kg_hr > 0 else 99.9
    utilization_avg = sum(u.utilization_pct for u in mb.units.values()) / max(len(mb.units), 1)
    cap_cost = sum(u.capital_cost for u in individual.graph.units.values())

    individual.fitness["throughput_kg_hr"] = througput
    individual.fitness["yield_pct"] = mb.system_yield * 100.0
    individual.fitness["energy_kwh_per_kg"] = -energy_per_kg
    individual.fitness["utilization_pct"] = utilization_avg
    individual.fitness["oee_score"] = bn.overall_equipment_effectiveness * 100.0
    individual.fitness["layout_efficiency"] = lo.placement_efficiency * 100.0
    individual.fitness["capital_cost"] = -cap_cost
    # Phase 16.1: if the bottleneck is reported but not in the per-step
    # breakdown (e.g. a graph with only buffer/splitter units), the slack
    # is 0 and we record the anomaly on the individual rather than just
    # dropping it. Constraint checking later flags it.
    if bn.bottleneck_unit_id and bn.bottleneck_unit_id in bn.steps:
        individual.fitness["bottleneck_slack"] = bn.steps[bn.bottleneck_unit_id].slack_kg_hr
    else:
        individual.fitness["bottleneck_slack"] = 0.0
        if bn.bottleneck_unit_id:
            individual.constraint_violations = list(individual.constraint_violations) + [
                f"Bottleneck {bn.bottleneck_unit_id} not present in per-step breakdown"
            ]

    violations = []
    for ub in mb.units.values():
        if ub.utilization_pct > 100:
            violations.append(f"Unit {ub.unit_id} overcapacity ({ub.utilization_pct:.0f}%)")
    for step in bn.steps.values():
        if step.is_bottleneck and step.utilization_pct > 95:
            violations.append(f"Bottleneck {step.unit_id} near saturation ({step.utilization_pct:.0f}%)")

    if lo.overlap_count > 0:
        violations.append(f"Layout has {lo.overlap_count} overlaps")

    individual.constraints_ok = len(violations) == 0
    individual.constraint_violations = violations

    return individual


def fast_nondominated_sort(population: List[FactoryIndividual]) -> List[List[FactoryIndividual]]:
    fronts: List[List[FactoryIndividual]] = []
    domination_counts = {}
    dominated_sets = {}

    for i, p in enumerate(population):
        dominated_sets[i] = set()
        domination_counts[i] = 0
        for j, q in enumerate(population):
            if p == q:
                continue
            p_dominates = all(
                p.fitness.get(obj, 0) >= q.fitness.get(obj, 0)
                for obj in _FACTORY_OBJECTIVES
            ) and any(
                p.fitness.get(obj, 0) > q.fitness.get(obj, 0)
                for obj in _FACTORY_OBJECTIVES
            )
            q_dominates = all(
                q.fitness.get(obj, 0) >= p.fitness.get(obj, 0)
                for obj in _FACTORY_OBJECTIVES
            ) and any(
                q.fitness.get(obj, 0) > p.fitness.get(obj, 0)
                for obj in _FACTORY_OBJECTIVES
            )
            if p_dominates:
                dominated_sets[i].add(j)
            elif q_dominates:
                domination_counts[i] += 1

    current_front = [i for i in range(len(population)) if domination_counts[i] == 0]
    rank = 0
    while current_front:
        next_front = []
        for i in current_front:
            population[i].rank = rank
            for j in dominated_sets[i]:
                domination_counts[j] -= 1
                if domination_counts[j] == 0:
                    next_front.append(j)
        fronts.append([population[i] for i in current_front])
        current_front = next_front
        rank += 1

    return fronts


def crowding_distance(front: List[FactoryIndividual]) -> None:
    n = len(front)
    if n <= 2:
        for ind in front:
            ind.crowding_distance = float("inf")
        return

    for ind in front:
        ind.crowding_distance = 0.0

    for obj in _FACTORY_OBJECTIVES:
        front.sort(key=lambda x: x.fitness.get(obj, 0))
        obj_min = front[0].fitness.get(obj, 0)
        obj_max = front[-1].fitness.get(obj, 0)
        obj_range = obj_max - obj_min
        if obj_range == 0:
            continue
        front[0].crowding_distance = float("inf")
        front[-1].crowding_distance = float("inf")
        for i in range(1, n - 1):
            front[i].crowding_distance += (front[i + 1].fitness.get(obj, 0) - front[i - 1].fitness.get(obj, 0)) / obj_range


def tournament_selection(population: List[FactoryIndividual], tournament_size: int = 2) -> FactoryIndividual:
    # Phase 16.1: defensive clamp on tournament_size. A 0 or 1 tournament
    # silently degenerates the selection operator; a > population_size
    # tournament is just wasteful.
    ts = int(
        clamp_factory_input(
            "tournament_size",
            tournament_size,
            default=2,
        )
    )
    candidates = random.sample(population, min(ts, len(population)))
    best = candidates[0]
    for c in candidates[1:]:
        if c.rank < best.rank or (c.rank == best.rank and c.crowding_distance > best.crowding_distance):
            best = c
    return best


def crossover(graph_a: FactoryProcessGraph, graph_b: FactoryProcessGraph) -> Tuple[FactoryProcessGraph, FactoryProcessGraph]:
    child_a = copy.deepcopy(graph_a)
    child_b = copy.deepcopy(graph_b)

    common_ids = set(graph_a.units.keys()) & set(graph_b.units.keys())
    if not common_ids:
        return child_a, child_b

    split_point = random.choice(list(common_ids))
    crossover_units_a = {}
    crossover_units_b = {}

    for uid, unit in child_a.units.items():
        if uid in common_ids and random.random() < 0.5:
            crossover_units_a[uid] = copy.deepcopy(graph_b.units[uid])
        else:
            crossover_units_a[uid] = unit

    for uid, unit in child_b.units.items():
        if uid in common_ids and random.random() < 0.5:
            crossover_units_b[uid] = copy.deepcopy(graph_a.units[uid])
        else:
            crossover_units_b[uid] = unit

    child_a.units = crossover_units_a
    child_b.units = crossover_units_b

    return child_a, child_b


def mutate(
    graph: FactoryProcessGraph,
    mutators: Optional[Dict[str, UnitMutator]] = None,
    mutation_rate: float = 0.2,
) -> FactoryProcessGraph:
    if mutators is None:
        mutators = default_mutators()

    # Phase 16.1: clamp mutation_rate to [0, 1] for the same reasons as
    # the optimizer below: a negative rate would skip every mutation, a
    # rate > 1 is meaningless (no second draw per gene).
    mutation_rate = clamp_factory_input("mutation_rate", mutation_rate, default=0.2)

    mutated = copy.deepcopy(graph)
    for unit in mutated.units.values():
        if random.random() < mutation_rate:
            mutator_name = random.choice(list(mutators.keys()))
            unit = mutators[mutator_name](unit)
    return mutated


def optimize_factory(
    base_graph: FactoryProcessGraph,
    feed_rate_kg_hr: float = 1000.0,
    population_size: int = 50,
    generations: int = 20,
    mutation_rate: float = 0.2,
    crossover_rate: float = 0.8,
    seed: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Tuple[List[FactoryIndividual], List[Dict[str, Any]]]:
    if seed is not None:
        random.seed(seed)

    # Phase 16.1: defensive clamps on the optimizer inputs. A negative
    # population size would infinite-loop the offspring builder; a
    # mutation rate > 1 or < 0 corrupts the search; a 0-generation run is
    # valid (just a random population) but is logged so the user notices.
    warnings: List[str] = []
    validate_factory_graph(base_graph, warnings)
    feed_rate_kg_hr = clamp_factory_input(
        "feed_rate_kg_hr", feed_rate_kg_hr, default=1000.0, warnings=warnings
    )
    population_size = int(
        clamp_factory_input(
            "population_size", population_size, default=50, warnings=warnings
        )
    )
    generations = int(
        clamp_factory_input(
            "generations", generations, default=20, warnings=warnings
        )
    )
    mutation_rate = clamp_factory_input(
        "mutation_rate", mutation_rate, default=0.2, warnings=warnings
    )
    crossover_rate = clamp_factory_input(
        "crossover_rate", crossover_rate, default=0.8, warnings=warnings
    )

    history: List[Dict[str, Any]] = []
    for w in warnings:
        history.append({"generation": -1, "warning": w})

    population: List[FactoryIndividual] = []
    for _ in range(population_size):
        ind = FactoryIndividual(graph=copy.deepcopy(base_graph))
        for unit in ind.graph.units.values():
            unit.efficiency = min(1.0, max(0.5, unit.efficiency + random.gauss(0, 0.05)))
            unit.max_capacity_kg_hr = max(10, unit.max_capacity_kg_hr * random.uniform(0.7, 1.3))
        ind = evaluate_factory(ind, feed_rate_kg_hr)
        population.append(ind)

    for gen in range(generations):
        if progress_callback:
            progress_callback(gen, generations)

        fronts = fast_nondominated_sort(population)
        for front in fronts:
            crowding_distance(front)

        offspring: List[FactoryIndividual] = []
        while len(offspring) < population_size:
            parent_a = tournament_selection(population)
            parent_b = tournament_selection(population)
            if random.random() < crossover_rate:
                child_graph_a, child_graph_b = crossover(parent_a.graph, parent_b.graph)
            else:
                child_graph_a = copy.deepcopy(parent_a.graph)
                child_graph_b = copy.deepcopy(parent_b.graph)

            child_graph_a = mutate(child_graph_a, mutation_rate=mutation_rate)
            child_graph_b = mutate(child_graph_b, mutation_rate=mutation_rate)

            child_a = FactoryIndividual(graph=child_graph_a)
            child_b = FactoryIndividual(graph=child_graph_b)
            child_a = evaluate_factory(child_a, feed_rate_kg_hr)
            child_b = evaluate_factory(child_b, feed_rate_kg_hr)
            offspring.append(child_a)
            if len(offspring) < population_size:
                offspring.append(child_b)

        combined = population + offspring
        combined_fronts = fast_nondominated_sort(combined)
        for front in combined_fronts:
            crowding_distance(front)

        new_population: List[FactoryIndividual] = []
        for front in combined_fronts:
            if len(new_population) + len(front) <= population_size:
                new_population.extend(front)
            else:
                front.sort(key=lambda x: x.crowding_distance, reverse=True)
                remaining = population_size - len(new_population)
                new_population.extend(front[:remaining])
                break

        population = new_population

        best = max(population, key=lambda x: x.fitness.get("throughput_kg_hr", 0))
        history.append({
            "generation": gen,
            "best_throughput": round(best.fitness.get("throughput_kg_hr", 0), 1),
            "best_yield": round(best.fitness.get("yield_pct", 0), 1),
            "best_energy": round(-best.fitness.get("energy_kwh_per_kg", 0), 3),
            "pareto_front_size": len(fast_nondominated_sort(population)[0]),
        })

    population.sort(key=lambda x: x.fitness.get("throughput_kg_hr", 0), reverse=True)
    return population, history

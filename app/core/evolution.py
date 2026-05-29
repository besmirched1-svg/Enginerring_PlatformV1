import random
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.scoring import DesignScoringEngine

ParameterVector = Dict[str, float]
EvaluationRecord = Dict[str, Any]


class ReinforcementOptimizer:
    """Score-driven evolutionary optimizer for mechanical design candidates."""

    def __init__(self, design_builder: Callable[[int, ParameterVector], str], seed: Optional[int] = None):
        self.design_builder = design_builder
        self.random = random.Random(seed)

    def _evaluate_candidate(self, generation: int, params: ParameterVector) -> EvaluationRecord:
        scad_content = self.design_builder(generation, params)
        feedback = DesignScoringEngine.evaluate_build(scad_content, params)
        score = float(feedback.composite_score)
        return {
            "generation": generation,
            "params": params.copy(),
            "score": score,
            "valid": feedback.is_valid,
            "signals": list(feedback.failure_signals),
            "feedback": feedback,
        }

    def _mutate(self, params: ParameterVector, signals: List[str], score: float, best_score: float) -> ParameterVector:
        next_params = params.copy()
        wall = float(params.get("wall_thickness", 3.0))
        clearance = float(params.get("bore_clearance", 1.6))
        radius = float(params.get("roller_radius", 30.0))

        score_gap = max(0.0, (best_score - score) / max(1.0, best_score)) if best_score > 0 else 1.0
        adaptive_step = 0.9 * (0.5 + score_gap)

        if any(signal.startswith("CRITICAL_WALL_THINNING") for signal in signals):
            next_params["wall_thickness"] = round(min(14.0, wall + self.random.uniform(0.7, 1.5) * adaptive_step), 2)
        elif any(signal.startswith("MASS_INEFFICIENCY") for signal in signals):
            next_params["wall_thickness"] = round(max(1.5, wall - self.random.uniform(0.3, 0.9) * adaptive_step), 2)
            next_params["roller_radius"] = round(max(10.0, radius - self.random.uniform(0.5, 1.4) * adaptive_step), 2)
        elif any(signal.startswith("TIGHT_CLEARANCE") for signal in signals):
            next_params["bore_clearance"] = round(min(4.0, clearance + self.random.uniform(0.15, 0.45) * adaptive_step), 3)
        else:
            next_params["wall_thickness"] = round(max(1.5, wall + self.random.uniform(-0.8, 0.8) * adaptive_step), 2)
            next_params["roller_radius"] = round(max(10.0, radius + self.random.uniform(-1.2, 1.2) * adaptive_step), 2)
            next_params["bore_clearance"] = round(max(0.2, clearance + self.random.uniform(-0.15, 0.15) * adaptive_step), 3)

        next_params["wall_thickness"] = max(1.5, min(15.0, float(next_params["wall_thickness"])))
        next_params["roller_radius"] = max(10.0, min(100.0, float(next_params["roller_radius"])))
        next_params["bore_clearance"] = max(0.1, min(4.0, float(next_params["bore_clearance"])))

        return next_params

    def _seed_population(self, base_params: ParameterVector, population_size: int) -> List[ParameterVector]:
        population = []
        for _ in range(population_size):
            candidate = {
                "wall_thickness": round(max(1.5, min(15.0, base_params.get("wall_thickness", 4.5) + self.random.uniform(-1.0, 1.0))), 2),
                "bore_clearance": round(max(0.1, min(4.0, base_params.get("bore_clearance", 0.6) + self.random.uniform(-0.2, 0.2))), 3),
                "roller_radius": round(max(10.0, min(100.0, base_params.get("roller_radius", 32.0) + self.random.uniform(-3.0, 3.0))), 2),
            }
            population.append(candidate)
        return population

    def seed_population(self, base_params: ParameterVector, population_size: int) -> List[ParameterVector]:
        return self._seed_population(base_params, population_size)

    def mutate(self, params: ParameterVector, signals: List[str], score: float, best_score: float) -> ParameterVector:
        return self._mutate(params, signals, score, best_score)

    def optimize(
        self,
        base_params: ParameterVector,
        max_generations: int = 5,
        population_size: int = 6,
        elite_fraction: float = 0.33,
        callback: Optional[Callable[[int, EvaluationRecord, List[EvaluationRecord]], None]] = None,
    ) -> Dict[str, Any]:
        population = self._seed_population(base_params, population_size)
        history: List[EvaluationRecord] = []
        champion: Optional[EvaluationRecord] = None

        elite_count = max(1, int(population_size * elite_fraction))

        for generation in range(1, max_generations + 1):
            scored = [self._evaluate_candidate(generation, candidate) for candidate in population]
            scored.sort(key=lambda item: item["score"], reverse=True)
            generation_best = scored[0]

            if champion is None or generation_best["score"] > champion["score"]:
                champion = generation_best

            history.extend(scored)

            if callback:
                callback(generation, generation_best, scored)

            if generation == max_generations:
                break

            elites = [entry["params"] for entry in scored[:elite_count]]
            next_population = [params.copy() for params in elites]

            while len(next_population) < population_size:
                parent = self.random.choice(scored[:elite_count])
                child_params = self._mutate(parent["params"], parent["signals"], parent["score"], champion["score"])
                next_population.append(child_params)

            population = next_population

        return {
            "champion": champion,
            "history": history,
            "generations": max_generations,
            "population_size": population_size,
        }

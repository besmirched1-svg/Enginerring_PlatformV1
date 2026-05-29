import os
import uuid
import logging
import random
from typing import Any, Dict, List, Optional

from app.core.events import get_event_bus
from app.core.planner import AIReasoningPlanner
from app.core.scoring import DesignScoringEngine, EvaluationFeedback
from app.core.evolution import ReinforcementOptimizer

logger = logging.getLogger("app.core.swarm")

Candidate = Dict[str, Any]


class SwarmAgent:
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role

    def __repr__(self) -> str:
        return f"<{self.role}:{self.name}>"


class DesignAgent(SwarmAgent):
    def __init__(self):
        super().__init__("DesignAgent", "designer")

    def generate(self, generation: int, params: Dict[str, float]) -> Candidate:
        candidate_id = f"cand_{uuid.uuid4().hex[:8]}"
        scad_content = f"""
        wall_thickness = {params.get('wall_thickness', 4.5)};
        bore_clearance = {params.get('bore_clearance', 0.6)};
        roller_radius = {params.get('roller_radius', 32.0)};

        module roller() {{
            difference() {{
                cylinder(h=100, r=roller_radius, $fn=60);
                translate([0,0,-5])
                    cylinder(h=110, r=bore_clearance + 2, $fn=40);
            }}
        }}
        roller();
        """
        return {
            "id": candidate_id,
            "generation": generation,
            "params": params.copy(),
            "scad": scad_content,
            "artifact_dir": None,
        }


class ValidationAgent(SwarmAgent):
    def __init__(self):
        super().__init__("ValidationAgent", "validator")

    def evaluate(self, candidate: Candidate) -> Candidate:
        try:
            feedback: EvaluationFeedback = DesignScoringEngine.evaluate_build(candidate["scad"], candidate["params"])
            candidate["score"] = float(feedback.composite_score)
            candidate["valid"] = feedback.is_valid
            candidate["signals"] = list(feedback.failure_signals)
            candidate["feedback"] = feedback
        except Exception as exc:
            logger.warning("Validation failure for candidate %s: %s", candidate.get("id"), exc)
            candidate["score"] = 0.0
            candidate["valid"] = False
            candidate["signals"] = ["VALIDATION_ERROR"]
            candidate["feedback"] = None
        return candidate


class OptimizationAgent(SwarmAgent):
    def __init__(self, seed: Optional[int] = None):
        super().__init__("OptimizationAgent", "optimizer")
        self.optimizer = ReinforcementOptimizer(self._dummy_scad_builder, seed=seed)

    def _dummy_scad_builder(self, generation: int, params: Dict[str, float]) -> str:
        return ""  # Not used for mutation calculation.

    def propose(self, candidate: Candidate, best_score: float) -> Dict[str, float]:
        return self.optimizer.mutate(
            candidate["params"],
            candidate.get("signals", []),
            candidate.get("score", 0.0),
            best_score,
        )


class MultiAgentSwarm:
    def __init__(self, session_id: str, output_dir: str = "./output"):
        self.session_id = session_id
        self.event_bus = get_event_bus()
        self.output_dir = output_dir
        self.design_agent = DesignAgent()
        self.validation_agent = ValidationAgent()
        self.optimization_agent = OptimizationAgent(seed=abs(hash(session_id)) % (2**32))
        self.random = random.Random(abs(hash(session_id)) % (2**32))
        os.makedirs(self.output_dir, exist_ok=True)

    def _broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        try:
            envelope = {"type": event_type, "payload": payload}
            if hasattr(self.event_bus, "publish"):
                self.event_bus.publish(event_type, payload)
            elif hasattr(self.event_bus, "broadcast"):
                self.event_bus.broadcast(event_type, payload)
            elif hasattr(self.event_bus, "emit"):
                self.event_bus.emit(event_type, payload)
        except Exception as exc:
            logger.error("Failed to broadcast swarm event %s: %s", event_type, exc)

    def _seed_population(self, base_params: Dict[str, float], size: int) -> List[Candidate]:
        population: List[Candidate] = []
        for _ in range(size):
            params = {
                "wall_thickness": round(max(1.5, min(15.0, base_params.get("wall_thickness", 4.5) + self.random.uniform(-1.0, 1.0))), 2),
                "bore_clearance": round(max(0.1, min(4.0, base_params.get("bore_clearance", 0.6) + self.random.uniform(-0.2, 0.2))), 3),
                "roller_radius": round(max(10.0, min(100.0, base_params.get("roller_radius", 32.0) + self.random.uniform(-3.0, 3.0))), 2),
            }
            population.append(self.design_agent.generate(1, params))
        return population

    def _render_and_validate(self, generation: int, candidate: Candidate) -> Candidate:
        self._broadcast("scad_generated", {
            "id": candidate["id"],
            "generation": generation,
            "params": candidate["params"],
        })
        candidate["generation"] = generation
        validated = self.validation_agent.evaluate(candidate)
        self._broadcast("evaluation_complete", {
            "id": validated["id"],
            "generation": generation,
            "score": validated["score"],
            "valid": validated["valid"],
            "signals": validated["signals"],
            "params": validated["params"],
        })
        return validated

    def _promote(self, generation: int, candidate: Candidate) -> None:
        self._broadcast("revision_promoted", {
            "generation": generation,
            "id": candidate["id"],
            "score": candidate["score"],
            "params": candidate["params"],
        })

    def run(self, prompt: str, max_generations: Optional[int] = None, population_size: int = 5) -> Dict[str, Any]:
        plan = AIReasoningPlanner.interpret_intent(prompt)
        if max_generations is None:
            max_generations = plan.generation_limit

        population = self._seed_population(plan.target_parameters, population_size)
        champion: Optional[Candidate] = None
        history: List[Candidate] = []

        self._broadcast("build_started", {
            "prompt": prompt,
            "strategy": plan.design_strategy,
            "intent_analysis": plan.intent_analysis,
            "initial_parameters": plan.target_parameters.copy(),
            "population_size": population_size,
            "generations": max_generations,
        })

        for generation in range(1, max_generations + 1):
            evaluated: List[Candidate] = []
            for candidate in population:
                candidate = self._render_and_validate(generation, candidate)
                evaluated.append(candidate)

            evaluated.sort(key=lambda c: c.get("score", 0.0), reverse=True)
            current_best = evaluated[0]
            if champion is None or current_best["score"] > champion["score"]:
                champion = current_best.copy()
                self._promote(generation, champion)

            history.extend(evaluated)

            if generation == max_generations:
                break

            next_population: List[Candidate] = []
            elites = evaluated[: max(1, population_size // 2)]
            for elite in elites:
                next_population.append(elite.copy())

            while len(next_population) < population_size:
                parent = self.random.choice(elites)
                new_params = self.optimization_agent.propose(parent, champion["score"] if champion else 0.0)
                next_population.append(self.design_agent.generate(generation + 1, new_params))

            population = next_population
            self._broadcast("improvement_suggested", {
                "generation": generation,
                "best_score": champion["score"] if champion else 0.0,
                "next_population_size": len(population),
                "elite_count": len(elites),
            })

        champion_result = champion.copy() if champion else {}
        if champion_result:
            champion_result["parameters"] = champion_result.get("params", {}).copy()

        final_result = {
            "status": "success",
            "prompt": prompt,
            "strategy": plan.design_strategy,
            "champion": champion_result,
            "optimized_score": champion["score"] if champion else 0.0,
            "history": history,
            "generations": max_generations,
        }
        self._broadcast("build_complete", final_result)
        return final_result

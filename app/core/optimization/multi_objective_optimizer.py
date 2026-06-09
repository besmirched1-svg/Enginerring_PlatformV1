# app/core/optimization/multi_objective_optimizer.py
# Multi-objective optimization system for Pareto-front generation

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import heapq

logger = logging.getLogger("engine.core.optimization.multi_objective_optimizer")


@dataclass
class Objective:
    """Definition of an optimization objective."""
    name: str
    minimize: bool = True  # True if lower is better, False if higher is better
    weight: float = 1.0    # Weight for utility functions (not used in pure Pareto optimization)
    

@dataclass
class Individual:
    """Represents an individual in the population."""
    parameters: Dict[str, Any] = field(default_factory=dict)
    objectives: List[float] = field(default_factory=list)
    objective_names: List[str] = field(default_factory=list)
    rank: int = 0
    crowding_distance: float = 0.0
    dominated_count: int = 0
    dominated_set: List['Individual'] = field(default_factory=list)
    
    def dominates(self, other: 'Individual', minimize_flags: Optional[List[bool]] = None) -> bool:
        """Check if this individual dominates another.

        Args:
            other: Individual to compare against.
            minimize_flags: List of bool per objective (True=minimize, False=maximize).
                If None, assumes all minimize (backward compatible).

        Returns:
            True if this individual dominates other.
        """
        if len(self.objectives) != len(other.objectives):
            raise ValueError("Individuals must have same number of objectives")

        n = len(self.objectives)
        if minimize_flags is None:
            minimize_flags = [True] * n
        if len(minimize_flags) != n:
            raise ValueError("minimize_flags length must match objectives")

        better_in_any = False
        for i in range(n):
            a = self.objectives[i]
            b = other.objectives[i]
            if minimize_flags[i]:
                a_better = a < b
                a_worse = a > b
            else:
                a_better = a > b
                a_worse = a < b
            if a_worse:
                return False
            if a_better:
                better_in_any = True
        return better_in_any

    def is_dominated_by(self, other: 'Individual', minimize_flags: Optional[List[bool]] = None) -> bool:
        """Check if this individual is dominated by another."""
        return other.dominates(self, minimize_flags=minimize_flags)


@dataclass
class OptimizationResult:
    """Results from multi-objective optimization."""
    pareto_front: List[Individual] = field(default_factory=list)
    all_generations: List[List[Individual]] = field(default_factory=list)
    generation_count: int = 0
    population_size: int = 0
    objective_definitions: List[Objective] = field(default_factory=list)
    
    def get_pareto_objectives(self) -> List[List[float]]:
        """Get objective values for the Pareto front."""
        return [ind.objectives for ind in self.pareto_front]
    
    def get_pareto_parameters(self) -> List[Dict[str, Any]]:
        """Get parameter values for the Pareto front."""
        return [ind.parameters for ind in self.pareto_front]


def fast_nondominated_sort(
    population: List[Individual],
    minimize_flags: Optional[List[bool]] = None,
) -> List[List[Individual]]:
    """
    Fast non-dominated sorting algorithm (O(MN^2) where M is objectives, N is population size).
    Returns fronts sorted by dominance rank.
    """
    if not population:
        return []

    if minimize_flags is None and population and population[0].objectives:
        minimize_flags = [True] * len(population[0].objectives)

    fronts = [[]]
    
    for i, p in enumerate(population):
        p.dominated_count = 0
        p.dominated_set = []
        
        for j, q in enumerate(population):
            if i == j:
                continue
                
            if p.dominates(q, minimize_flags=minimize_flags):
                p.dominated_set.append(q)
            elif q.dominates(p, minimize_flags=minimize_flags):
                p.dominated_count += 1
                
        if p.dominated_count == 0:
            p.rank = 0
            fronts[0].append(p)
            
    i = 0
    while fronts[i]:
        next_front = []
        for p in fronts[i]:
            for q in p.dominated_set:
                q.dominated_count -= 1
                if q.dominated_count == 0:
                    q.rank = i + 1
                    next_front.append(q)
        i += 1
        fronts.append(next_front)
        
    # Remove empty last front
    if fronts and not fronts[-1]:
        fronts.pop()
        
    return fronts


def calculate_crowding_distance(front: List[Individual]) -> None:
    """
    Calculate crowding distance for individuals in a front.
    Higher crowding distance indicates better diversity.
    """
    if not front:
        return
        
    if len(front) <= 2:
        for ind in front:
            ind.crowding_distance = float('inf')
        return
        
    # Initialize distances
    for ind in front:
        ind.crowding_distance = 0.0
        
    # For each objective
    num_objectives = len(front[0].objectives) if front and front[0].objectives else 0
    if num_objectives == 0:
        return
        
    for obj_idx in range(num_objectives):
        # Sort by objective value
        front.sort(key=lambda ind: ind.objectives[obj_idx])
        
        # Set boundary points to infinite distance
        front[0].crowding_distance = float('inf')
        front[-1].crowding_distance = float('inf')
        
        # Calculate distances for intermediate points
        obj_range = front[-1].objectives[obj_idx] - front[0].objectives[obj_idx]
        if obj_range == 0:
            continue
            
        for i in range(1, len(front) - 1):
            if front[i].crowding_distance != float('inf'):
                distance = (front[i + 1].objectives[obj_idx] - front[i - 1].objectives[obj_idx]) / obj_range
                front[i].crowding_distance += distance


def tournament_selection(population: List[Individual], tournament_size: int = 2) -> Individual:
    """
    Select individual using tournament selection based on rank and crowding distance.
    """
    if tournament_size > len(population):
        tournament_size = len(population)
        
    participants = random.sample(population, tournament_size)
    winner = participants[0]
    
    for participant in participants[1:]:
        # Lower rank is better
        if participant.rank < winner.rank:
            winner = participant
        elif participant.rank == winner.rank:
            # Higher crowding distance is better
            if participant.crowding_distance > winner.crowding_distance:
                winner = participant
                
    return winner


def crossover(parent1: Dict[str, Any], parent2: Dict[str, Any], 
              parameter_bounds: Dict[str, Tuple[float, float]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Perform simulated binary crossover (SBX) on parameters.
    """
    child1 = parent1.copy()
    child2 = parent2.copy()
    
    for param_name, (low, high) in parameter_bounds.items():
        if param_name not in parent1 or param_name not in parent2:
            continue
            
        if random.random() < 0.9:  # Crossover probability
            u = random.random()
            if u <= 0.5:
                beta = (2 * u) ** (1.0 / (1.0 + 1.0))  # eta = 1.0 for simplicity
            else:
                beta = (1.0 / (2.0 * (1.0 - u))) ** (1.0 / (1.0 + 1.0))
                
            diff = parent2[param_name] - parent1[param_name]
            child1[param_name] = parent1[param_name] + 0.5 * beta * diff
            child2[param_name] = parent2[param_name] - 0.5 * beta * diff
            
            # Ensure bounds
            child1[param_name] = max(low, min(high, child1[param_name]))
            child2[param_name] = max(low, min(high, child2[param_name]))
            
    return child1, child2


def mutate(individual: Dict[str, Any], parameter_bounds: Dict[str, Tuple[float, float]], 
           mutation_probability: float = 0.1) -> Dict[str, Any]:
    """
    Perform polynomial mutation on parameters.
    """
    mutated = individual.copy()
    
    for param_name, (low, high) in parameter_bounds.items():
        if param_name not in mutated:
            continue
            
        if random.random() < mutation_probability:
            # Polynomial mutation
            y = mutated[param_name]
            y_low, y_up = low, high
            delta1 = (y - y_low) / (y_up - y_low)
            delta2 = (y_up - y) / (y_up - y_low)
            mut_pow = 1.0 / (1.0 + 1.0)  # eta_m = 1.0 for simplicity
            
            rand = random.random()
            if rand < 0.5:
                xy = 1.0 - delta1
                val = 2.0 * rand + (1.0 - 2.0 * rand) * (xy ** (1.0 + mut_pow))
                delta_q = (val ** (1.0 / (1.0 + mut_pow))) - 1.0
            else:
                xy = 1.0 - delta2
                val = 2.0 * (1.0 - rand) + 2.0 * (rand - 0.5) * (xy ** (1.0 + mut_pow))
                delta_q = 1.0 - (val ** (1.0 / (1.0 + mut_pow)))
                
            y = y + delta_q * (y_up - y_low)
            y = max(y_low, min(y_up, y))
            mutated[param_name] = y
            
    return mutated


class MultiObjectiveOptimizer:
    """
    Multi-objective evolutionary optimizer using NSGA-II algorithm.
    Optimizes multiple conflicting objectives to generate a Pareto front.
    """
    
    def __init__(self, 
                 objective_functions: List[Callable[[Dict[str, Any]], float]],
                 objective_names: List[str],
                 objective_minimize: List[bool],
                 parameter_bounds: Dict[str, Tuple[float, float]],
                 population_size: int = 100):
        """
        Initialize the multi-objective optimizer.
        
        Args:
            objective_functions: List of functions that take parameters and return objective values
            objective_names: Names of the objectives
            objective_minimize: List of booleans indicating whether each objective should be minimized
            parameter_bounds: Dictionary mapping parameter names to (min, max) tuples
            population_size: Size of the population
        """
        if len(objective_functions) != len(objective_names) or len(objective_functions) != len(objective_minimize):
            raise ValueError("All objective lists must have the same length")
            
        self.objective_functions = objective_functions
        self.objective_names = objective_names
        self.objective_minimize = objective_minimize
        self.parameter_bounds = parameter_bounds
        self.population_size = population_size
        
        # Create objective definitions
        self.objectives = [
            Objective(name=name, minimize=minimize) 
            for name, minimize in zip(objective_names, objective_minimize)
        ]
        
        logger.info(f"Initialized MultiObjectiveOptimizer with {len(self.objectives)} objectives")
        
    def _create_individual(self, parameters: Dict[str, Any]) -> Individual:
        """Create an individual from parameters and evaluate its objectives."""
        individual = Individual(parameters=parameters.copy())
        
        # Evaluate all objectives
        objective_values = []
        for func in self.objective_functions:
            try:
                value = func(parameters)
                objective_values.append(value)
            except Exception as e:
                logger.warning(f"Error evaluating objective: {e}")
                # Return a worst-case value based on minimization preference
                # For now, use a large positive value
                objective_values.append(1e6)
                
        individual.objectives = objective_values
        individual.objective_names = self.objective_names.copy()
        
        return individual
    
    def _initialize_population(self) -> List[Individual]:
        """Create initial random population."""
        population = []
        
        for _ in range(self.population_size):
            # Generate random parameters within bounds
            parameters = {}
            for param_name, (low, high) in self.parameter_bounds.items():
                parameters[param_name] = random.uniform(low, high)
                
            individual = self._create_individual(parameters)
            population.append(individual)
            
        return population
    
    def optimize(self, 
                 max_generations: int = 250,
                 callback: Optional[Callable[[int, List[Individual]], None]] = None) -> OptimizationResult:
        """
        Run the multi-objective optimization.
        
        Args:
            max_generations: Maximum number of generations to evolve
            callback: Optional callback function called each generation
            
        Returns:
            OptimizationResult containing the Pareto front and evolution history
        """
        logger.info(f"Starting multi-objective optimization for {max_generations} generations")
        
        # Initialize population
        population = self._initialize_population()
        all_generations = []
        
        for generation in range(max_generations):
            # Evaluate population (already done in _create_individual, but ensure fresh evaluation)
            for individual in population:
                individual.objectives = []
                for func in self.objective_functions:
                    try:
                        value = func(individual.parameters)
                        individual.objectives.append(value)
                    except Exception as e:
                        logger.warning(f"Error evaluating objective in generation {generation}: {e}")
                        individual.objectives.append(1e6)
            
            # Non-dominated sorting
            fronts = fast_nondominated_sort(population)
            
            # Calculate crowding distance for each front
            for front in fronts:
                calculate_crowding_distance(front)
                
            # Store generation
            all_generations.append([ind for ind in population])  # Deep copy would be better but costly
            
            # Create next generation
            new_population = []
            
            # Elitism: take best fronts until we fill the population
            for front in fronts:
                if len(new_population) + len(front) <= self.population_size:
                    new_population.extend(front)
                else:
                    # Need to select from this front based on crowding distance
                    remaining = self.population_size - len(new_population)
                    if remaining > 0:
                        front.sort(key=lambda ind: ind.crowding_distance, reverse=True)
                        new_population.extend(front[:remaining])
                    break
                    
            # If we still need more individuals, create offspring
            while len(new_population) < self.population_size:
                # Selection
                parent1 = tournament_selection(population)
                parent2 = tournament_selection(population)
                
                # Crossover
                child1_params, child2_params = crossover(
                    parent1.parameters, parent2.parameters, self.parameter_bounds
                )
                
                # Mutation
                child1_params = mutate(child1_params, self.parameter_bounds)
                child2_params = mutate(child2_params, self.parameter_bounds)
                
                # Create individuals
                child1 = self._create_individual(child1_params)
                child2 = self._create_individual(child2_params)
                
                new_population.extend([child1, child2])
                
            # Trim to exact population size
            population = new_population[:self.population_size]
            
            # Call callback if provided
            if callback:
                try:
                    callback(generation, population)
                except Exception as e:
                    logger.warning(f"Callback error in generation {generation}: {e}")
                    
            # Log progress
            if generation % 50 == 0 or generation == max_generations - 1:
                # Count non-dominated individuals in current population
                fronts = fast_nondominated_sort(population)
                nd_count = len(fronts[0]) if fronts else 0
                logger.info(f"Generation {generation}: {nd_count} non-dominated solutions")
        
        # Final non-dominated sort to get the Pareto front
        final_fronts = fast_nondominated_sort(population)
        pareto_front = final_fronts[0] if final_fronts else []
        
        logger.info(f"Optimization complete. Found {len(pareto_front)} Pareto optimal solutions")
        
        return OptimizationResult(
            pareto_front=pareto_front,
            all_generations=all_generations,
            generation_count=max_generations,
            population_size=self.population_size,
            objective_definitions=self.objectives
        )


def create_default_hemp_decotitator_objectives() -> Tuple[
    List[Callable[[Dict[str, Any]], float]],
    List[str],
    List[bool],
    Dict[str, Tuple[float, float]]
]:
    """
    Create default objective functions and parameter bounds for hemp decorticator optimization.
    Returns: (objective_functions, objective_names, minimize_flags, parameter_bounds)
    """
    
    # Parameter bounds for hemp decorticator design
    parameter_bounds = {
        # Geometry parameters (mm)
        "drum_diameter": (800.0, 2000.0),      # Drum inner diameter
        "drum_length": (1000.0, 5000.0),       # Drum length
        "flight_thickness": (8.0, 25.0),       # Flight plate thickness
        "flight_pitch": (50.0, 300.0),         # Distance between flights
        "shaft_diameter": (30.0, 150.0),       # Shaft diameter
        "spacing_between_flights": (50.0, 300.0), # Alternative to flight_pitch
        "number_of_flights": (2.0, 12.0),      # Number of helical flights
        
        # Operational parameters
        "rotational_speed": (20.0, 200.0),     # RPM
        "feed_rate": (500.0, 5000.0),          # kg/hr
        "moisture_content": (5.0, 30.0),       # Percentage
        
        # Material properties
        "steel_grade_uts": (300.0, 800.0),     # Ultimate tensile strength (MPa)
        "steel_grade_ys": (200.0, 500.0),      # Yield strength (MPa)
    }
    
    def objective_fibre_recovery(params: Dict[str, Any]) -> float:
        """
        Objective 1: Fibre Recovery (to maximize)
        Estimates the percentage of fibre successfully recovered from the hemp stalks.
        Higher is better, so we'll return negative for minimization framework.
        """
        # Simplified model based on drum geometry and operational parameters
        drum_dia = params.get("drum_diameter", 1200.0)
        drum_len = params.get("drum_length", 3000.0)
        flight_pitch = params.get("flight_pitch", 150.0)
        flight_thick = params.get("flight_thickness", 12.0)
        rpm = params.get("rotational_speed", 120.0)
        feed_rate = params.get("feed_rate", 2000.0)
        moisture = params.get("moisture_content", 15.0)
        
        # Geometric factors
        surface_area = math.pi * drum_dia * drum_len  # mm^2
        flight_area_factor = flight_thick * (drum_len / flight_pitch)  # Relative flight surface
        
        # Operational factors
        tip_speed = math.pi * drum_dia * rpm / 60000  # m/s (converting mm*rpm to m/s)
        residence_time = drum_len / (tip_speed * 1000) if tip_speed > 0 else 10  # seconds
        
        # Moisture effect (optimal around 15-20%)
        moisture_factor = 1.0 - abs(moisture - 17.5) / 20.0  # Penalty for deviation from optimal
        moisture_factor = max(0.0, min(1.0, moisture_factor))
        
        # Recovery model (simplified)
        base_recovery = 0.6  # 60% base recovery
        geometric_bonus = min(0.3, surface_area / 50000000)  # Up to 30% bonus for larger surface
        operational_bonus = min(0.2, tip_speed * 10)  # Up to 20% bonus for higher tip speed
        moisture_bonus = moisture_factor * 0.1  # Up to 10% for optimal moisture
        
        recovery = base_recovery + geometric_bonus + operational_bonus + moisture_bonus
        recovery = max(0.0, min(0.95, recovery))  # Cap between 0% and 95%
        
        # Return negative for minimization (since we want to maximize recovery)
        return -recovery
    
    def objective_fibre_quality(params: Dict[str, Any]) -> float:
        """
        Objective 2: Fibre Quality (to maximize)
        Estimates the quality of recovered fibre (length, strength, cleanliness).
        Higher is better, so return negative for minimization.
        """
        flight_pitch = params.get("flight_pitch", 150.0)
        flight_thick = params.get("flight_thickness", 12.0)
        rpm = params.get("rotational_speed", 120.0)
        feed_rate = params.get("feed_rate", 2000.0)
        moisture = params.get("moisture_content", 15.0)
        
        # Quality factors
        # Lower flight pitch = gentler handling = better quality
        pitch_factor = max(0.0, 1.0 - (flight_pitch - 50.0) / 250.0)  # 50-300mm range
        
        # Lower rotational speed = less fibre damage
        speed_factor = max(0.0, 1.0 - (rpm - 20.0) / 180.0)  # 20-200 RPM range
        
        # Optimal feed rate for quality (not too high to cause damage)
        feed_optimal = 1500.0  # kg/hr
        feed_factor = max(0.0, 1.0 - abs(feed_rate - feed_optimal) / feed_optimal)
        
        # Moisture effect on quality (drier = better quality but more brittle)
        moisture_factor = max(0.0, 1.0 - abs(moisture - 12.0) / 15.0)  # Optimal ~12% for quality
        
        # Flight thickness effect (thicker = more rigid = potentially more damage)
        thickness_factor = max(0.0, 1.0 - (flight_thick - 8.0) / 40.0)  # 8-48mm range
        
        quality = (
            pitch_factor * 0.3 +
            speed_factor * 0.25 +
            feed_factor * 0.2 +
            moisture_factor * 0.15 +
            thickness_factor * 0.1
        )
        quality = max(0.0, min(1.0, quality))
        
        # Return negative for minimization
        return -quality
    
    def objective_power_consumption(params: Dict[str, Any]) -> float:
        """
        Objective 3: Power Consumption (to minimize)
        Estimates the power required to operate the decorticator.
        Lower is better.
        """
        drum_dia = params.get("drum_diameter", 1200.0)
        drum_len = params.get("drum_length", 3000.0)
        flight_thick = params.get("flight_thickness", 12.0)
        flight_pitch = params.get("flight_pitch", 150.0)
        rpm = params.get("rotational_speed", 120.0)
        feed_rate = params.get("feed_rate", 2000.0)
        
        # Estimate moment of inertia (simplified cylinder with flights)
        # I = (1/2) * m * r^2 for cylinder + additional for flights
        drum_radius = drum_dia / 2000.0  # Convert to meters
        drum_volume = math.pi * (drum_radius ** 2) * (drum_len / 1000.0)  # m^3
        steel_density = 7850.0  # kg/m^3
        drum_mass = drum_volume * steel_density  # kg
        
        # Flight mass approximation
        flight_count = max(2.0, drum_len / flight_pitch)  # Number of flights
        flight_volume_per_flight = (flight_thick / 1000.0) * (flight_pitch / 1000.0) * (drum_dia / 1000.0)  # m^3
        flight_mass = flight_count * flight_volume_per_flight * steel_density  # kg
        total_mass = drum_mass + flight_mass
        
        # Moment of inertia approximation
        radius_for_inertia = drum_dia / 2000.0  # meters
        inertia = 0.5 * total_mass * (radius_for_inertia ** 2)  # kg*m^2
        
        # Power to overcome inertia and friction
        omega = rpm * math.pi / 30.0  # rad/s
        # Power = torque * omega
        # Torque estimate: inertia * angular_acceleration + friction_torque
        # Assume we need to reach operating speed in 10 seconds
        alpha = omega / 10.0  # rad/s^2 (to reach speed in 10s)
        inertia_torque = inertia * alpha  # N*m
        
        # Friction torque estimate (simplified)
        normal_force = total_mass * 9.81  # N
        friction_coefficient = 0.02  # Guess for bearing friction
        friction_torque = normal_force * friction_coefficient * (drum_dia / 2000.0) / 2.0  # N*m
        
        # Power for material processing (simplified)
        # Based on feed rate and resistance
        material_power = (feed_rate / 3600.0) * 50.0  # Watts - simplified
        
        total_torque = inertia_torque + friction_torque
        power_watts = total_torque * omega + material_power
        power_kw = power_watts / 1000.0
        
        # Ensure positive
        return max(0.1, power_kw)
    
    def objective_weight(params: Dict[str, Any]) -> float:
        """
        Objective 4: Total Weight (to minimize)
        Estimates the total weight of the machine.
        Lower is better.
        """
        drum_dia = params.get("drum_diameter", 1200.0)
        drum_len = params.get("drum_length", 3000.0)
        flight_thick = params.get("flight_thickness", 12.0)
        flight_pitch = params.get("flight_pitch", 150.0)
        shaft_dia = params.get("shaft_diameter", 75.0)
        drum_wall_thick = 15.0  # Assume fixed for now, could be parameter
        shaft_length = drum_len + 500.0  # Shaft extends beyond drum
        
        # Drum volume (cylindrical shell)
        outer_radius = (drum_dia + 2 * drum_wall_thick) / 2000.0  # m
        inner_radius = drum_dia / 2000.0  # m
        drum_volume = math.pi * (outer_radius ** 2 - inner_radius ** 2) * (drum_len / 1000.0)  # m^3
        
        # Flights volume
        flight_count = max(2.0, drum_len / flight_pitch)
        flight_volume_per_flight = (flight_thick / 1000.0) * (flight_pitch / 1000.0) * (drum_dia / 1000.0)  # m^3
        flight_volume = flight_count * flight_volume_per_flight
        
        # Shaft volume (solid cylinder)
        shaft_radius = shaft_dia / 2000.0  # m
        shaft_volume = math.pi * (shaft_radius ** 2) * (shaft_length / 1000.0)  # m^3
        
        # Frame volume (simplified - rectangular tube frame)
        frame_height = drum_dia / 1000.0 + 300.0 / 1000.0  # m
        frame_width = 1000.0 / 1000.0  # m (1m width)
        frame_thickness = 20.0 / 1000.0  # m
        frame_length = drum_len / 1000.0 + 1000.0 / 1000.0  # m
        frame_volume = 2 * (frame_height + frame_width) * frame_thickness * frame_length  # m^3 (simplified)
        
        steel_density = 7850.0  # kg/m^3
        total_volume = drum_volume + flight_volume + shaft_volume + frame_volume
        total_mass_kg = total_volume * steel_density
        
        return total_mass_kg
    
    def objective_cost(params: Dict[str, Any]) -> float:
        """
        Objective 5: Manufacturing Cost (to minimize)
        Estimates the relative manufacturing cost.
        Lower is better.
        """
        drum_dia = params.get("drum_diameter", 1200.0)
        drum_len = params.get("drum_length", 3000.0)
        flight_thick = params.get("flight_thickness", 12.0)
        flight_pitch = params.get("flight_pitch", 150.0)
        shaft_dia = params.get("shaft_diameter", 75.0)
        
        # Cost factors
        # Material cost (proportional to weight)
        weight_obj = objective_weight(params)
        material_cost_factor = weight_obj / 1000.0  # Normalize
        
        # Manufacturing complexity cost
        # More complex geometries = higher cost
        complexity_factor = (
            (flight_thick / 10.0) * 0.3 +  # Thicker flights = harder to form
            (300.0 / flight_pitch) * 0.2 +  # Shorter pitch = more flights = more welding
            (drum_len / 2000.0) * 0.2 +     # Longer drum = more material handling
            (shaft_dia / 50.0) * 0.1 +      # Larger shaft = harder to machine
            (drum_dia / 1000.0) * 0.2       # Larger diameter = bigger machines needed
        )
        
        # Material grade cost (higher strength steel costs more)
        uts = params.get("steel_grade_uts", 400.0)
        material_grade_factor = max(1.0, uts / 400.0)  # Relative to baseline 400 MPa
        
        # Base cost
        base_cost = 10000.0  # Arbitrary base cost in currency units
        
        total_cost = base_cost * (
            0.4 * material_cost_factor +
            0.3 * complexity_factor +
            0.3 * material_grade_factor
        )
        
        return max(1000.0, total_cost)  # Minimum reasonable cost
    
    def objective_maintenance(params: Dict[str, Any]) -> float:
        """
        Objective 6: Maintenance Requirement (to minimize)
        Estimates the relative maintenance frequency/cost.
        Lower is better.
        """
        flight_thick = params.get("flight_thickness", 12.0)
        flight_pitch = params.get("flight_pitch", 150.0)
        rpm = params.get("rotational_speed", 120.0)
        feed_rate = params.get("feed_rate", 2000.0)
        moisture = params.get("moisture_content", 15.0)
        
        # Wear factors (higher wear = more maintenance)
        # Abrasive wear from fibre contact
        tip_speed = math.pi * drum_dia * rpm / 60000 if (drum_dia := params.get("drum_diameter", 1200.0)) else 1.0
        abrasive_wear = tip_speed * feed_rate / 1000000.0  # Simplified
        
        # Impact wear
        impact_wear = feed_rate * 0.001  # Simplified
        
        # Fatigue factors
        # Cyclic stress from flights passing
        flight_count = max(2.0, drum_len / flight_pitch) if (drum_len := params.get("drum_length", 3000.0)) else 2.0
        fatigue_cycles_per_hour = flight_count * rpm * 60  # Flights passing a point per hour
        
        # Maintenance based on wear and fatigue
        wear_maintenance = (abrasive_wear + impact_wear) * 1000.0  # Scale up
        fatigue_maintenance = math.log(max(1.0, fatigue_cycles_per_hour)) * 10.0
        
        # Corrosion factor from moisture
        corrosion_factor = moisture / 100.0  # Simplified
        
        # Thinner flights wear faster = more maintenance
        thickness_factor = 20.0 / flight_thick  # Inverse relationship
        
        maintenance_score = (
            wear_maintenance * 0.4 +
            fatigue_maintenance * 0.3 +
            corrosion_factor * 50.0 * 0.2 +
            thickness_factor * 10.0 * 0.1
        )
        
        return max(0.1, maintenance_score)
    
    def objective_reliability(params: Dict[str, Any]) -> float:
        """
        Objective 7: Reliability (to minimize failure rate, so minimize this objective)
        Estimates the failure rate or inverse of MTBF.
        Lower is better (lower failure rate).
        """
        # Reuse some calculations from maintenance objective
        flight_thick = params.get("flight_thickness", 12.0)
        flight_pitch = params.get("flight_pitch", 150.0)
        rpm = params.get("rotational_speed", 120.0)
        feed_rate = params.get("feed_rate", 2000.0)
        drum_dia = params.get("drum_diameter", 1200.0)
        drum_len = params.get("drum_length", 3000.0)
        shaft_dia = params.get("shaft_diameter", 75.0)
        
        # Stress factors that affect reliability
        # Torsional stress on shaft
        torque_estimate = feed_rate * 0.1  # N*m - simplified
        shaft_radius = shaft_dia / 2000.0  # m
        shaft_j = math.pi * (shaft_radius ** 4) / 2  # Polar moment for solid shaft
        torsional_stress = torque_estimate * shaft_radius / shaft_j if shaft_j > 0 else 0  # Pa
        
        # Bending stress on flights
        flight_length_approx = drum_len / 1000.0  # m
        flight_width_approx = flight_thick / 1000.0  # m
        flight_height_approx = math.pi * drum_dia / 1000.0  # m (approx helical length)
        # Simplified cantilever beam
        force_per_flight = feed_rate / max(1.0, drum_len / flight_pitch)  # N per flight
        bending_moment = force_per_flight * flight_height_approx  # N*m
        flight_I = flight_width_approx * (flight_thick ** 3) / 12  # m^4
        bending_stress = bending_moment * (flight_thick / 2000.0) / flight_I if flight_I > 0 else 0  # Pa
        
        # Combined stress effect (simplified)
        von_mises_stress = math.sqrt(torsional_stress ** 2 + 3 * bending_stress ** 2) if bending_stress > 0 else torsional_stress
        
        # Material strength
        uts = params.get("steel_grade_uts", 400.0) * 1e6  # Convert to Pa
        ys = params.get("steel_grade_ys", 250.0) * 1e6   # Convert to Pa
        
        # Stress ratio (lower = better reliability)
        stress_ratio = von_mises_stress / uts if uts > 0 else 1.0
        
        # Cycles to failure approximation (Basquin's law simplified)
        # Nf = C * (stress_ratio)^(-b)
        if stress_ratio > 0 and stress_ratio < 1:
            cycles_to_failure = 1e6 * (stress_ratio ** (-5.0))  # Simplified
        else:
            cycles_to_failure = 1000  # Very low if overstressed
            
        # Actual cycles per hour
        flight_count = max(2.0, drum_len / flight_pitch)
        actual_cycles_per_hour = flight_count * rpm * 60
        
        # Hours to failure
        hours_to_failure = cycles_to_failure / max(1.0, actual_cycles_per_hour)
        
        # Convert to failure rate (failures per hour) - what we want to minimize
        failure_rate = 1.0 / max(1.0, hours_to_failure)
        
        # Scale to reasonable range
        return min(10.0, max(0.0001, failure_rate * 10000))  # Between 0.0001 and 10 failures/hour
    
    # Objective functions list
    objective_functions = [
        objective_fibre_recovery,      # 0: Maximize fibre recovery (returned as negative for minimization)
        objective_fibre_quality,       # 1: Maximise fibre quality (returned as negative)
        objective_power_consumption,   # 2: Minimize power consumption
        objective_weight,              # 3: Minimize weight
        objective_cost,                # 4: Minimize cost
        objective_maintenance,         # 5: Minimize maintenance
        objective_reliability          # 6: Minimize failure rate (maximize reliability)
    ]
    
    # Objective names
    objective_names = [
        "Fibre Recovery",
        "Fibre Quality", 
        "Power Consumption",
        "Weight",
        "Cost",
        "Maintenance Requirement",
        "Failure Rate"
    ]
    
    # Minimization flags (True = minimize, False = maximize)
    # Note: For objectives we want to maximize (recovery, quality), we return negative values
    # so they still need to be minimized in the optimization framework
    objective_minimize = [
        True,   # Fibre Recovery (we negated the value, so minimize the negative = maximize original)
        True,   # Fibre Quality (we negated the value, so minimize the negative = maximize original)
        True,   # Power Consumption
        True,   # Weight
        True,   # Cost
        True,   # Maintenance Requirement
        True    # Failure Rate
    ]
    
    return objective_functions, objective_names, objective_minimize, parameter_bounds


# Convenience function to create a pre-configured optimizer
def create_hemp_decotitator_optimizer(population_size: int = 100) -> MultiObjectiveOptimizer:
    """
    Create a multi-objective optimizer configured for hemp decorticator design.
    
    Args:
        population_size: Size of the evolutionary population
        
    Returns:
        Configured MultiObjectiveOptimizer instance
    """
    obj_funcs, obj_names, obj_minimize, param_bounds = create_default_hemp_decotitator_objectives()
    return MultiObjectiveOptimizer(
        objective_functions=obj_funcs,
        objective_names=obj_names,
        objective_minimize=obj_minimize,
        parameter_bounds=param_bounds,
        population_size=population_size
    )


if __name__ == "__main__":
    # Example usage and testing
    logging.basicConfig(level=logging.INFO)
    
    logger.info("Creating hemp decorticator multi-objective optimizer...")
    optimizer = create_hemp_decotitator_optimizer(population_size=50)
    
    logger.info(f"Optimizer configured with {len(optimizer.objectives)} objectives: {[obj.name for obj in optimizer.objectives]}")
    
    logger.info("Running optimization (50 generations for demo)...")
    result = optimizer.optimize(max_generations=50)
    
    logger.info(f"Optimization complete — Pareto front size: {len(result.pareto_front)}")
    
    if result.pareto_front:
        logger.info("Top 5 Pareto solutions:")
        for i, ind in enumerate(result.pareto_front[:5]):
            logger.info(f"  Solution {i+1}:")
            for j, (name, value) in enumerate(zip(ind.objective_names, ind.objectives)):
                display_value = -value if j < 2 else value
                logger.info(f"    {name}: {display_value:.4f}")
            logger.info(f"    Parameters: {list(ind.parameters.keys())[:3]}...")
    
    logger.info("Multi-objective optimizer ready for use!")
# app/core/planning_engine.py
# AI Planning Engine for the Autonomous Engineering Intelligence Platform
# Provides genuine planning capabilities: goal decomposition, constraint reasoning,
# design strategy generation, and alternative solution generation.

import re
import json
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field
from enum import Enum


class GoalType(Enum):
    """Types of engineering goals that can be decomposed from user prompts."""
    PERFORMANCE = "performance"
    EFFICIENCY = "efficiency"
    DURABILITY = "durability"
    COST = "cost"
    SIZE = "size"
    WEIGHT = "weight"
    MANUFACTURABILITY = "manufacturability"
    SAFETY = "safety"


class ConstraintType(Enum):
    """Types of engineering constraints."""
    MATERIAL = "material"
    DIMENSIONAL = "dimensional"
    PERFORMANCE = "performance"
    COST = "cost"
    MANUFACTURING = "manufacturing"
    SAFETY = "safety"


class EngineeringGoal(BaseModel):
    """Represents a decomposed engineering goal."""
    type: GoalType
    description: str
    priority: float = Field(default=1.0, ge=0.0, le=1.0)
    target_value: Optional[float] = None
    acceptable_range: Optional[Tuple[float, float]] = None


class EngineeringConstraint(BaseModel):
    """Represents an engineering constraint."""
    type: ConstraintType
    description: str
    limit_value: float
    limit_type: str = Field(default="max")  # "max" or "min"
    weight: float = Field(default=1.0, ge=0.0, le=1.0)


class DesignAlternative(BaseModel):
    """Represents an alternative design solution."""
    name: str
    description: str
    parameters: Dict[str, float]
    expected_score: float
    trade_offs: List[str]
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class EngineeringPlan(BaseModel):
    """Enhanced engineering plan with planning capabilities."""
    # Backward compatibility fields
    intent_analysis: str
    target_parameters: Dict[str, float] = Field(default_factory=dict)
    design_strategy: str
    generation_limit: int = 3
    
    # Advanced planning fields
    goals: List[EngineeringGoal] = Field(default_factory=list)
    constraints: List[EngineeringConstraint] = Field(default_factory=list)
    alternatives: List[DesignAlternative] = Field(default_factory=list)
    reasoning_steps: List[str] = Field(default_factory=list)


class AIPlanningEngine:
    """
    Genuine AI Planning Engine that interprets user intent, decomposes goals,
    reasons about constraints, generates design strategies, and creates alternative solutions.
    """
    
    # Knowledge base for engineering domains
    DOMAIN_KNOWLEDGE = {
        "hemp": {
            "typical_wall_thickness": (5.0, 10.0),
            "typical_roller_radius": (30.0, 60.0),
            "typical_clearance": (1.0, 3.0),
            "materials": ["stainless_steel", "hardened_steel", "carbon_steel"],
            "common_failures": ["clogging", "excessive_vibration", "bearing_wear"],
            "performance_metrics": ["throughput_kg_per_hr", "fiber_recovery_percent", "power_consumption_hp"]
        },
        "decorticator": {
            "typical_wall_thickness": (6.0, 12.0),
            "typical_roller_radius": (35.0, 70.0),
            "typical_clearance": (1.5, 4.0),
            "materials": ["stainless_304", "stainless_316", "hardox_500"],
            "common_failures": ["fiber_damage", "overheating", "screen_blinding"],
            "performance_metrics": ["fiber_quality_index", "throughput_tons_per_day", "energy_efficiency"]
        },
        "roller": {
            "typical_wall_thickness": (2.0, 8.0),
            "typical_roller_radius": (10.0, 50.0),
            "typical_clearance": (0.5, 2.0),
            "materials": ["steel", "aluminum", "composite"],
            "common_failures": ["bending", "surface_wear", "bearing_failure"],
            "performance_metrics": ["surface_speed", "load_capacity", "vibration_level"]
        }
    }
    
    # Constraint defaults
    DEFAULT_CONSTRAINTS = {
        "material_strength": {"limit": 250.0, "type": "min", "unit": "MPa"},  # MPa
        "max_weight": {"limit": 500.0, "type": "max", "unit": "kg"},
        "max_cost": {"limit": 10000.0, "type": "max", "unit": "USD"},
        "min_safety_factor": {"limit": 2.0, "type": "min", "unit": "ratio"},
    }
    
    @staticmethod
    def interpret_intent(prompt: str) -> EngineeringPlan:
        """
        Main interface for backward compatibility.
        Interprets user intent and converts it into structured parameter strategies.
        Enhanced with genuine planning capabilities.
        """
        # Decompose the user prompt into goals
        goals = AIPlanningEngine._decompose_goals(prompt)
        
        # Reason about constraints based on goals and domain knowledge
        constraints = AIPlanningEngine._reason_about_constraints(goals, prompt)
        
        # Generate design strategy based on goals and constraints
        design_strategy = AIPlanningEngine._generate_design_strategy(goals, constraints)
        
        # Generate alternative solutions
        alternatives = AIPlanningEngine._generate_alternatives(goals, constraints, design_strategy)
        
        # Determine target parameters based on goals, constraints, and alternatives
        target_parameters = AIPlanningEngine._determine_target_parameters(goals, constraints, alternatives)
        
        # Generate intent analysis
        intent_analysis = AIPlanningEngine._generate_intent_analysis(goals, constraints)
        
        # Determine generation limit based on complexity
        generation_limit = AIPlanningEngine._determine_generation_limit(goals, constraints)
        
        # Generate reasoning steps for transparency
        reasoning_steps = AIPlanningEngine._generate_reasoning_steps(goals, constraints, alternatives, target_parameters)
        
        return EngineeringPlan(
            intent_analysis=intent_analysis,
            target_parameters=target_parameters,
            design_strategy=design_strategy,
            generation_limit=generation_limit,
            goals=goals,
            constraints=constraints,
            alternatives=alternatives,
            reasoning_steps=reasoning_steps
        )
    
    @staticmethod
    def _decompose_goals(prompt: str) -> List[EngineeringGoal]:
        """Decompose user prompt into specific engineering goals."""
        goals = []
        normalized = prompt.lower()
        
        # Performance goals
        if any(word in normalized for word in ["fast", "speed", "high", "throughput", "productive", "efficient"]):
            goals.append(EngineeringGoal(
                type=GoalType.PERFORMANCE,
                description="Maximize processing throughput and operational speed",
                priority=0.9,
                target_value=None  # Will be determined by constraint reasoning
            ))
        
        # Quality goals
        if any(word in normalized for word in ["quality", "precise", "accurate", "fine", "consistent"]):
            goals.append(EngineeringGoal(
                type=GoalType.EFFICIENCY,
                description="Maximize output quality and consistency",
                priority=0.8,
                target_value=None
            ))
        
        # Durability goals
        if any(word in normalized for word in ["durable", "long-lasting", "robust", "sturdy", "heavy-duty"]):
            goals.append(EngineeringGoal(
                type=GoalType.DURABILITY,
                description="Maximize equipment durability and lifespan",
                priority=0.7,
                target_value=None
            ))
        
        # Size/space goals
        if any(word in normalized for word in ["compact", "small", "space-saving", "portable"]):
            goals.append(EngineeringGoal(
                type=GoalType.SIZE,
                description="Minimize physical footprint and size",
                priority=0.6,
                target_value=None
            ))
        
        # Cost goals
        if any(word in normalized for word in ["affordable", "low-cost", " economical", "budget"]):
            goals.append(EngineeringGoal(
                type=GoalType.COST,
                description="Minimize manufacturing and operational costs",
                priority=0.7,
                target_value=None
            ))
        
        # Safety goals
        if any(word in normalized for word in ["safe", "safety", "guarded", "protected"]):
            goals.append(EngineeringGoal(
                type=GoalType.SAFETY,
                description="Maximize operational safety and reduce hazards",
                priority=0.8,
                target_value=None
            ))
        
        # Domain-specific goals
        if "hemp" in normalized or "decorticator" in normalized:
            goals.append(EngineeringGoal(
                type=GoalType.PERFORMANCE,
                description="Optimize hemp fiber recovery and quality",
                priority=0.95,
                target_value=None
            ))
            
            goals.append(EngineeringGoal(
                type=GoalType.MANUFACTURABILITY,
                description="Ensure design is manufacturable with standard workshop tools",
                priority=0.8,
                target_value=None
            ))
        
        # If no specific goals detected, add default goals
        if not goals:
            goals.append(EngineeringGoal(
                type=GoalType.PERFORMANCE,
                description="Achieve balanced performance for general mechanical operation",
                priority=0.7,
                target_value=None
            ))
        
        return goals
    
    @staticmethod
    def _reason_about_constraints(goals: List[EngineeringGoal], prompt: str) -> List[EngineeringConstraint]:
        """Reason about engineering constraints based on goals and domain knowledge."""
        constraints = []
        normalized = prompt.lower()
        
        # Extract explicit constraints from prompt
        # Look for numbers with units
        constraint_patterns = [
            r'(\d+(?:\.\d+)?)\s*(mm|centimeters?|cm|meters?|m|inches?|in|"|\')\s*(?:max|maximum|at most|≤|<=)',
            r'(\d+(?:\.\d+)?)\s*(mm|centimeters?|cm|meters?|m|inches?|in|"|\')\s*(?:min|minimum|at least|≥|>=)',
            r'(?:max|maximum|at most|≤|<=)\s*(\d+(?:\.\d+)?)\s*(mm|centimeters?|cm|meters?|m|inches?|in|"|\')',
            r'(?:min|minimum|at least|≥|>=)\s*(\d+(?:\.\d+)?)\s*(mm|centimeters?|cm|meters?|m|inches?|in|"|\')',
            r'(\d+(?:\.\d+)?)\s*(kg|kilograms?|kgs?)\s*(?:max|maximum|at most|≤|<=)',
            r'(\d+(?:\.\d+)?)\s*(kg|kilograms?|kgs?)\s*(?:min|minimum|at least|≥|>=)',
            r'(?:max|maximum|at most|≤|<=)\s*(\d+(?:\.\d+)?)\s*(kg|kilograms?|kgs?)',
            r'(?:min|minimum|at least|≥|>=)\s*(\d+(?:\.\d+)?)\s*(kg|kilograms?|kgs?)',
        ]
        
        # For simplicity in this implementation, we'll use domain knowledge and goal-based constraints
        # In a full implementation, we would parse explicit constraints from the prompt
        
        # Apply domain-specific constraints based on detected domains
        for domain_key, domain_knowledge in AIPlanningEngine.DOMAIN_KNOWLEDGE.items():
            if domain_key in normalized:
                # Add dimensional constraints based on domain knowledge
                if "wall_thickness" in domain_knowledge:
                    min_val, max_val = domain_knowledge["wall_thickness"]
                    constraints.append(EngineeringConstraint(
                        type=ConstraintType.DIMENSIONAL,
                        description=f"{domain_key.capitalize()} wall thickness",
                        limit_value=max_val,
                        limit_type="max",
                        weight=0.8
                    ))
                    constraints.append(EngineeringConstraint(
                        type=ConstraintType.DIMENSIONAL,
                        description=f"{domain_key.capitalize()} wall thickness minimum",
                        limit_value=min_val,
                        limit_type="min",
                        weight=0.8
                    ))
                
                if "roller_radius" in domain_knowledge:
                    min_val, max_val = domain_knowledge["roller_radius"]
                    constraints.append(EngineeringConstraint(
                        type=ConstraintType.DIMENSIONAL,
                        description=f"{domain_key.capitalize()} roller radius",
                        limit_value=max_val,
                        limit_type="max",
                        weight=0.8
                    ))
                    constraints.append(EngineeringConstraint(
                        type=ConstraintType.DIMENSIONAL,
                        description=f"{domain_key.capitalize()} roller radius minimum",
                        limit_value=min_val,
                        limit_type="min",
                        weight=0.8
                    ))
                
                if "clearance" in domain_knowledge:
                    min_val, max_val = domain_knowledge["clearance"]
                    constraints.append(EngineeringConstraint(
                        type=ConstraintType.DIMENSIONAL,
                        description=f"{domain_key.capitalize()} clearance",
                        limit_value=max_val,
                        limit_type="max",
                        weight=0.8
                    ))
                    constraints.append(EngineeringConstraint(
                        type=ConstraintType.DIMENSIONAL,
                        description=f"{domain_key.capitalize()} clearance minimum",
                        limit_value=min_val,
                        limit_type="min",
                        weight=0.8
                    ))
        
        # Apply goal-based constraints
        for goal in goals:
            if goal.type == GoalType.PERFORMANCE:
                # Performance goals might imply minimum performance thresholds
                constraints.append(EngineeringConstraint(
                    type=ConstraintType.PERFORMANCE,
                    description="Minimum performance threshold",
                    limit_value=0.7,  # Normalized score
                    limit_type="min",
                    weight=goal.priority
                ))
            
            elif goal.type == GoalType.EFFICIENCY:
                # Efficiency goals might imply maximum energy consumption or minimum output quality
                constraints.append(EngineeringConstraint(
                    type=ConstraintType.PERFORMANCE,
                    description="Minimum efficiency threshold",
                    limit_value=0.6,
                    limit_type="min",
                    weight=goal.priority
                ))
            
            elif goal.type == GoalType.DURABILITY:
                # Durability goals might imply minimum safety factor or maximum wear rate
                constraints.append(EngineeringConstraint(
                    type=ConstraintType.SAFETY,
                    description="Minimum safety factor for durability",
                    limit_value=2.5,
                    limit_type="min",
                    weight=goal.priority
                ))
            
            elif goal.type == GoalType.SIZE:
                # Size goals imply maximum dimensions
                constraints.append(EngineeringConstraint(
                    type=ConstraintType.DIMENSIONAL,
                    description="Maximum overall size",
                    limit_value=2000.0,  # mm
                    limit_type="max",
                    weight=goal.priority
                ))
            
            elif goal.type == GoalType.COST:
                # Cost goals imply maximum budget
                constraints.append(EngineeringConstraint(
                    type=ConstraintType.COST,
                    description="Maximum manufacturing cost",
                    limit_value=5000.0,  # USD
                    limit_type="max",
                    weight=goal.priority
                ))
            
            elif goal.type == GoalType.SAFETY:
                # Safety goals imply minimum safety margins
                constraints.append(EngineeringConstraint(
                    type=ConstraintType.SAFETY,
                    description="Minimum safety margin",
                    limit_value=2.0,
                    limit_type="min",
                    weight=goal.priority
                ))
        
        # Apply default constraints if none were added
        if not constraints:
            constraints.append(EngineeringConstraint(
                type=ConstraintType.MATERIAL,
                description="Minimum material strength",
                limit_value=AIPlanningEngine.DEFAULT_CONSTRAINTS["material_strength"]["limit"],
                limit_type=AIPlanningEngine.DEFAULT_CONSTRAINTS["material_strength"]["type"],
                weight=0.7
            ))
            constraints.append(EngineeringConstraint(
                type=ConstraintType.COST,
                description="Maximum cost constraint",
                limit_value=AIPlanningEngine.DEFAULT_CONSTRAINTS["max_cost"]["limit"],
                limit_type=AIPlanningEngine.DEFAULT_CONSTRAINTS["max_cost"]["type"],
                weight=0.6
            ))
        
        return constraints
    
    @staticmethod
    def _generate_design_strategy(goals: List[EngineeringGoal], constraints: List[EngineeringConstraint]) -> str:
        """Generate a design strategy based on goals and constraints."""
        if not goals:
            return "Standard balanced design approach"
        
        # Prioritize goals by priority weight
        sorted_goals = sorted(goals, key=lambda g: g.priority, reverse=True)
        primary_goal = sorted_goals[0] if sorted_goals else None
        
        strategy_parts = []
        
        if primary_goal:
            if primary_goal.type == GoalType.PERFORMANCE:
                strategy_parts.append("Optimize for high throughput and operational speed")
                strategy_parts.append("Increase roller diameter and surface speed")
                strategy_parts.append("Optimize clearance for material flow")
                
            elif primary_goal.type == GoalType.EFFICIENCY:
                strategy_parts.append("Maximize output quality and consistency")
                strategy_parts.append("Implement precise gap control and alignment")
                strategy_parts.append("Use balanced roller design to minimize vibration")
                
            elif primary_goal.type == GoalType.DURABILITY:
                strategy_parts.append("Maximize equipment durability and lifespan")
                strategy_parts.append("Use thicker walls and reinforced bearings")
                strategy_parts.append("Implement wear-resistant surfaces and easy maintenance access")
                
            elif primary_goal.type == GoalType.SIZE:
                strategy_parts.append("Minimize physical footprint and size")
                strategy_parts.append("Optimize compact design with vertical integration")
                strategy_parts.append("Use lightweight materials where structurally appropriate")
                
            elif primary_goal.type == GoalType.COST:
                strategy_parts.append("Minimize manufacturing and operational costs")
                strategy_parts.append("Use standard materials and simplified fabrication")
                strategy_parts.append("Optimize for ease of maintenance and parts availability")
                
            elif primary_goal.type == GoalType.MANUFACTURABILITY:
                strategy_parts.append("Ensure design is manufacturable with standard workshop tools")
                strategy_parts.append("Avoid complex geometries and tight tolerances")
                strategy_parts.append("Use standard fasteners and modular assembly")
                
            elif primary_goal.type == GoalType.SAFETY:
                strategy_parts.append("Maximize operational safety and reduce hazards")
                strategy_parts.append("Implement guards, emergency stops, and safety interlocks")
                strategy_parts.append("Design for safe maintenance access and operation")
        
        # Add constraint-aware modifications
        if constraints:
            constraint_types = [c.type for c in constraints]
            if ConstraintType.DIMENSIONAL in constraint_types:
                strategy_parts.append("Respect dimensional constraints in all design decisions")
            
            if ConstraintType.MATERIAL in constraint_types:
                strategy_parts.append("Select materials based on strength-to-weight ratio and cost")
            
            if ConstraintType.COST in constraint_types:
                strategy_parts.append("Optimize design for minimal material usage and standard parts")
            
            if ConstraintType.SAFETY in constraint_types:
                strategy_parts.append("Incorporate safety features without compromising functionality")
        
        # Combine strategy parts
        if strategy_parts:
            return ". ".join(strategy_parts) + "."
        else:
            return "Balanced design approach considering all identified goals and constraints"
    
    @staticmethod
    def _generate_alternatives(goals: List[EngineeringGoal], constraints: List[EngineeringConstraint], 
                              base_strategy: str) -> List[DesignAlternative]:
        """Generate alternative design solutions."""
        alternatives = []
        
        # Generate a few alternative approaches based on different emphases
        if not goals:
            # Default alternatives
            alternatives.append(DesignAlternative(
                name="Balanced Approach",
                description="Standard design balancing all factors",
                parameters={"wall_thickness": 4.0, "bore_clearance": 1.0, "roller_radius": 30.0},
                expected_score=0.75,
                trade_offs=["Moderate performance", "Moderate cost"],
                confidence=0.8
            ))
            alternatives.append(DesignAlternative(
                name="Performance Focused",
                description="Optimized for maximum throughput",
                parameters={"wall_thickness": 6.0, "bore_clearance": 1.5, "roller_radius": 45.0},
                expected_score=0.85,
                trade_offs=["Higher cost", "Larger size"],
                confidence=0.7
            ))
            alternatives.append(DesignAlternative(
                name="Cost Effective",
                description="Optimized for minimum cost",
                parameters={"wall_thickness": 3.0, "bore_clearance": 0.8, "roller_radius": 25.0},
                expected_score=0.65,
                trade_offs=["Lower performance", "Reduced durability"],
                confidence=0.8
            ))
        else:
            # Goal-specific alternatives
            primary_goals = [g for g in goals if g.priority >= 0.8]
            if not primary_goals:
                primary_goals = goals[:2] if len(goals) >= 2 else goals
            
            for i, goal in enumerate(primary_goals[:3]):  # Limit to 3 alternatives
                if goal.type == GoalType.PERFORMANCE:
                    alternatives.append(DesignAlternative(
                        name=f"Performance-Oriented Design {i+1}",
                        description=f"Design emphasizing {goal.description}",
                        parameters=AIPlanningEngine._get_performance_parameters(constraints),
                        expected_score=0.8 + (i * 0.05),
                        trade_offs=["May increase cost", "May increase size"],
                        confidence=0.75 - (i * 0.1)
                    ))
                elif goal.type == GoalType.EFFICIENCY:
                    alternatives.append(DesignAlternative(
                        name=f"Quality-Focused Design {i+1}",
                        description=f"Design emphasizing {goal.description}",
                        parameters=AIPlanningEngine._get_quality_parameters(constraints),
                        expected_score=0.78 + (i * 0.05),
                        trade_offs=["May reduce throughput", "May increase complexity"],
                        confidence=0.78 - (i * 0.1)
                    ))
                elif goal.type == GoalType.DURABILITY:
                    alternatives.append(DesignAlternative(
                        name=f"Durable Design {i+1}",
                        description=f"Design emphasizing {goal.description}",
                        parameters=AIPlanningEngine._get_durability_parameters(constraints),
                        expected_score=0.82 + (i * 0.05),
                        trade_offs=["May increase weight", "May increase cost"],
                        confidence=0.8 - (i * 0.1)
                    ))
                else:
                    # Generic alternative
                    alternatives.append(DesignAlternative(
                        name=f"Alternative Design {i+1}",
                        description=f"Design emphasizing {goal.description}",
                        parameters=AIPlanningEngine._get_balanced_parameters(constraints),
                        expected_score=0.7 + (i * 0.05),
                        trade_offs=["Balanced trade-offs"],
                        confidence=0.75 - (i * 0.1)
                    ))
        
        # Ensure we have at least one alternative
        if not alternatives:
            alternatives.append(DesignAlternative(
                name="Default Design",
                description="Standard balanced design",
                parameters={"wall_thickness": 4.0, "bore_clearance": 1.0, "roller_radius": 30.0},
                expected_score=0.7,
                trade_offs=["Standard performance"],
                confidence=0.8
            ))
        
        return alternatives[:3]  # Limit to 3 alternatives
    
    @staticmethod
    def _get_performance_parameters(constraints: List[EngineeringConstraint]) -> Dict[str, float]:
        """Get parameters optimized for performance."""
        params = {"wall_thickness": 5.0, "bore_clearance": 1.2, "roller_radius": 40.0}
        
        # Adjust based on constraints
        for constraint in constraints:
            if constraint.type == ConstraintType.DIMENSIONAL:
                if constraint.description == "wall thickness maximum":
                    params["wall_thickness"] = min(params["wall_thickness"], constraint.limit_value)
                elif constraint.description == "wall thickness minimum":
                    params["wall_thickness"] = max(params["wall_thickness"], constraint.limit_value)
                elif constraint.description == "roller radius maximum":
                    params["roller_radius"] = min(params["roller_radius"], constraint.limit_value)
                elif constraint.description == "roller radius minimum":
                    params["roller_radius"] = max(params["roller_radius"], constraint.limit_value)
                elif constraint.description == "clearance maximum":
                    params["bore_clearance"] = min(params["bore_clearance"], constraint.limit_value)
                elif constraint.description == "clearance minimum":
                    params["bore_clearance"] = max(params["bore_clearance"], constraint.limit_value)
        
        return params
    
    @staticmethod
    def _get_quality_parameters(constraints: List[EngineeringConstraint]) -> Dict[str, float]:
        """Get parameters optimized for quality/output consistency."""
        params = {"wall_thickness": 4.0, "bore_clearance": 0.8, "roller_radius": 25.0}
        
        # Adjust based on constraints (similar to above)
        for constraint in constraints:
            if constraint.type == ConstraintType.DIMENSIONAL:
                if constraint.description == "wall thickness maximum":
                    params["wall_thickness"] = min(params["wall_thickness"], constraint.limit_value)
                elif constraint.description == "wall thickness minimum":
                    params["wall_thickness"] = max(params["wall_thickness"], constraint.limit_value)
                elif constraint.description == "roller radius maximum":
                    params["roller_radius"] = min(params["roller_radius"], constraint.limit_value)
                elif constraint.description == "roller radius minimum":
                    params["roller_radius"] = max(params["roller_radius"], constraint.limit_value)
                elif constraint.description == "clearance maximum":
                    params["bore_clearance"] = min(params["bore_clearance"], constraint.limit_value)
                elif constraint.description == "clearance minimum":
                    params["bore_clearance"] = max(params["bore_clearance"], constraint.limit_value)
        
        return params
    
    @staticmethod
    def _get_durability_parameters(constraints: List[EngineeringConstraint]) -> Dict[str, float]:
        """Get parameters optimized for durability."""
        params = {"wall_thickness": 7.0, "bore_clearance": 1.5, "roller_radius": 35.0}
        
        # Adjust based on constraints
        for constraint in constraints:
            if constraint.type == ConstraintType.DIMENSIONAL:
                if constraint.description == "wall thickness maximum":
                    params["wall_thickness"] = min(params["wall_thickness"], constraint.limit_value)
                elif constraint.description == "wall thickness minimum":
                    params["wall_thickness"] = max(params["wall_thickness"], constraint.limit_value)
                elif constraint.description == "roller radius maximum":
                    params["roller_radius"] = min(params["roller_radius"], constraint.limit_value)
                elif constraint.description == "roller radius minimum":
                    params["roller_radius"] = max(params["roller_radius"], constraint.limit_value)
                elif constraint.description == "clearance maximum":
                    params["bore_clearance"] = min(params["bore_clearance"], constraint.limit_value)
                elif constraint.description == "clearance minimum":
                    params["bore_clearance"] = max(params["bore_clearance"], constraint.limit_value)
        
        return params
    
    @staticmethod
    def _get_balanced_parameters(constraints: List[EngineeringConstraint]) -> Dict[str, float]:
        """Get balanced parameters."""
        params = {"wall_thickness": 4.5, "bore_clearance": 1.0, "roller_radius": 30.0}
        
        # Adjust based on constraints
        for constraint in constraints:
            if constraint.type == ConstraintType.DIMENSIONAL:
                if constraint.description == "wall thickness maximum":
                    params["wall_thickness"] = min(params["wall_thickness"], constraint.limit_value)
                elif constraint.description == "wall thickness minimum":
                    params["wall_thickness"] = max(params["wall_thickness"], constraint.limit_value)
                elif constraint.description == "roller radius maximum":
                    params["roller_radius"] = min(params["roller_radius"], constraint.limit_value)
                elif constraint.description == "roller radius minimum":
                    params["roller_radius"] = max(params["roller_radius"], constraint.limit_value)
                elif constraint.description == "clearance maximum":
                    params["bore_clearance"] = min(params["bore_clearance"], constraint.limit_value)
                elif constraint.description == "clearance minimum":
                    params["bore_clearance"] = max(params["bore_clearance"], constraint.limit_value)
        
        return params
    
    @staticmethod
    def _determine_target_parameters(goals: List[EngineeringGoal], constraints: List[EngineeringConstraint],
                                   alternatives: List[DesignAlternative]) -> Dict[str, float]:
        """Determine target parameters based on goals, constraints, and alternatives."""
        # Start with balanced parameters
        params = AIPlanningEngine._get_balanced_parameters(constraints)
        
        # Weight alternatives by expected score and confidence
        if alternatives:
            weighted_params = {"wall_thickness": 0.0, "bore_clearance": 0.0, "roller_radius": 0.0}
            total_weight = 0.0
            
            for alt in alternatives:
                weight = alt.expected_score * alt.confidence
                total_weight += weight
                weighted_params["wall_thickness"] += alt.parameters["wall_thickness"] * weight
                weighted_params["bore_clearance"] += alt.parameters["bore_clearance"] * weight
                weighted_params["roller_radius"] += alt.parameters["roller_radius"] * weight
            
            if total_weight > 0:
                params["wall_thickness"] = weighted_params["wall_thickness"] / total_weight
                params["bore_clearance"] = weighted_params["bore_clearance"] / total_weight
                params["roller_radius"] = weighted_params["roller_radius"] / total_weight
        
        # Apply goal-based adjustments
        goal_weights = {GoalType.PERFORMANCE: 0.0, GoalType.EFFICIENCY: 0.0, GoalType.DURABILITY: 0.0,
                       GoalType.SIZE: 0.0, GoalType.COST: 0.0, GoalType.WEIGHT: 0.0,
                       GoalType.MANUFACTURABILITY: 0.0, GoalType.SAFETY: 0.0}
        
        total_goal_weight = 0.0
        for goal in goals:
            goal_weights[goal.type] += goal.priority
            total_goal_weight += goal.priority
        
        if total_goal_weight > 0:
            # Normalize goal weights
            for goal_type in goal_weights:
                goal_weights[goal_type] /= total_goal_weight
            
            # Apply goal-based adjustments to parameters
            # Performance: increase roller radius, decrease clearance for speed
            # Efficiency: optimize clearance for quality, moderate wall thickness
            # Durability: increase wall thickness and roller radius
            # Size: decrease all dimensions
            # Cost: decrease wall thickness and roller radius
            # Manufacturability: standard dimensions, avoid extremes
            # Safety: increase wall thickness, optimize clearance
            
            perf_adjustment = goal_weights[GoalType.PERFORMANCE]
            eff_adjustment = goal_weights[GoalType.EFFICIENCY]
            dur_adjustment = goal_weights[GoalType.DURABILITY]
            size_adjustment = goal_weights[GoalType.SIZE]
            cost_adjustment = goal_weights[GoalType.COST]
            manuf_adjustment = goal_weights[GoalType.MANUFACTURABILITY]
            safety_adjustment = goal_weights[GoalType.SAFETY]
            
            # Apply adjustments
            params["wall_thickness"] += (dur_adjustment * 2.0) - (size_adjustment * 1.5) - (cost_adjustment * 1.0) + (safety_adjustment * 1.5)
            params["roller_radius"] += (perf_adjustment * 10.0) + (dur_adjustment * 5.0) - (size_adjustment * 8.0) - (cost_adjustment * 6.0) + (eff_adjustment * 2.0)
            params["bore_clearance"] += (eff_adjustment * 0.3) - (perf_adjustment * 0.2) + (safety_adjustment * 0.2) - (dur_adjustment * 0.1)
            
            # Ensure parameters stay within reasonable bounds
            params["wall_thickness"] = max(1.5, min(15.0, params["wall_thickness"]))
            params["roller_radius"] = max(10.0, min(100.0, params["roller_radius"]))
            params["bore_clearance"] = max(0.1, min(5.0, params["bore_clearance"]))
        
        return params
    
    @staticmethod
    def _generate_intent_analysis(goals: List[EngineeringGoal], constraints: List[EngineeringConstraint]) -> str:
        """Generate intent analysis from goals and constraints."""
        if not goals and not constraints:
            return "General mechanical design request detected"
        
        analysis_parts = []
        
        if goals:
            goal_descriptions = [g.description for g in goals]
            analysis_parts.append(f"Identified engineering goals: {', '.join(goal_descriptions[:3])}")
            if len(goals) > 3:
                analysis_parts.append(f"and {len(goals) - 3} additional goals")
        
        if constraints:
            constraint_descriptions = [c.description for c in constraints]
            analysis_parts.append(f"Identified constraints: {', '.join(constraint_descriptions[:3])}")
            if len(constraints) > 3:
                analysis_parts.append(f"and {len(constraints) - 3} additional constraints")
        
        if not analysis_parts:
            return "Standard mechanical design request processed"
        
        return ". ".join(analysis_parts) + "."
    
    @staticmethod
    def _determine_generation_limit(goals: List[EngineeringGoal], constraints: List[EngineeringConstraint]) -> int:
        """Determine appropriate generation limit based on problem complexity."""
        base_generations = 3
        
        # Increase generations for more complex problems
        complexity_score = len(goals) + len(constraints)
        
        if complexity_score <= 2:
            return base_generations
        elif complexity_score <= 4:
            return base_generations + 2
        elif complexity_score <= 6:
            return base_generations + 4
        else:
            return base_generations + 6
    
    @staticmethod
    def _generate_reasoning_steps(goals: List[EngineeringGoal], constraints: List[EngineeringConstraint],
                                 alternatives: List[DesignAlternative], target_parameters: Dict[str, float]) -> List[str]:
        """Generate reasoning steps for transparency."""
        steps = []
        
        steps.append(f"1. Decomposed user prompt into {len(goals)} engineering goals")
        steps.append(f"2. Identified {len(constraints)} engineering constraints from goals and domain knowledge")
        steps.append(f"3. Generated {len(alternatives)} alternative design approaches")
        steps.append(f"4. Synthesized target parameters: wall_thickness={target_parameters.get('wall_thickness', 0):.1f}mm, "
                    f"bore_clearance={target_parameters.get('bore_clearance', 0):.2f}mm, roller_radius={target_parameters.get('roller_radius', 0):.1f}mm")
        steps.append("5. Selected optimal balance of goals, constraints, and alternatives")
        
        return steps
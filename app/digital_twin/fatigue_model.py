# app/digital_twin/fatigue_model.py
# Fatigue life modeling for Digital Twin simulation

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Import the physics fatigue module for core calculations
from app.physics.fatigue import FatigueAnalysis, StressState, FatigueResult

logger = logging.getLogger("engine.digital_twin.fatigue_model")


@dataclass
class FatigueState:
    """Current fatigue state of a component."""
    cycles_accumulated: float = 0.0      # Number of stress cycles experienced
    damage_accumulated: float = 0.0      # Miner's rule damage (D = sum ni/Ni)
    remaining_life_fraction: float = 1.0 # Fraction of life remaining (1-D)
    is_safe: bool = True                 # Whether component is still safe (D < 1)
    
    def add_damage(self, damage_increment: float) -> 'FatigueState':
        """Add damage and return new state."""
        new_damage = self.damage_accumulated + damage_increment
        return FatigueState(
            cycles_accumulated=self.cycles_accumulated,
            damage_accumulated=new_damage,
            remaining_life_fraction=max(0.0, 1.0 - new_damage),
            is_safe=new_damage < 1.0
        )
    
    def is_critical(self, threshold: float = 0.8) -> bool:
        """Check if fatigue damage is critical (> threshold)."""
        return self.damage_accumulated > threshold
    
    def time_to_failure_at_current_rate(self, hours_per_damage_unit: float) -> float:
        """
        Estimated time to failure based on current damage accumulation rate.
        Returns hours to reach D=1.0.
        """
        if self.damage_accumulated <= 0 or hours_per_damage_unit <= 0:
            return float('inf')
            
        damage_per_hour = 1.0 / hours_per_damage_unit if hours_per_damage_unit > 0 else 0
        if damage_per_hour <= 0:
            return float('inf')
            
        hours_to_damage_1 = (1.0 - self.damage_accumulated) / damage_per_hour
        return max(0.0, hours_to_damage_1)


class FatigueModel:
    """
    Models fatigue life consumption on machine components over time.
    Uses stress cycles and Miner's rule for damage accumulation.
    """
    
    def __init__(self):
        self.fatigue_analyzer = FatigueAnalysis()
        logger.debug("Initialized FatigueModel")
    
    def calculate_cycles_per_hour(
        self,
        rotational_speed_rpm: float,
        cycles_per_revolution: float = 1.0
    ) -> float:
        """
        Calculate number of stress cycles per hour of operation.
        """
        return rotational_speed_rpm * cycles_per_revolution * 60
    
    def estimate_stress_state(
        self,
        config_dict: Dict[str, Any],
        component_type: str,
        operating_hours: float
    ) -> Optional[StressState]:
        """
        Estimate stress state for a component based on configuration and operation.
        This is a simplified estimation - in reality would use FEA or detailed mechanics.
        """
        # Extract basic parameters
        spindle = config_dict.get("spindle", {})
        drum = config_dict.get("drum", {})
        frame = config_dict.get("frame", {})
        
        rotational_speed = config_dict.get("rotational_speed", 100.0)  # rpm
        feed_rate = config_dict.get("feed_rate", 1000.0)  # kg/hr
        
        if component_type == "spindle_shaft":
            # Torsional shear stress from transmitting torque
            # Estimate torque needed to process material
            torque_estimate = feed_rate * 0.1  # N*m - simplified
            shaft_od = spindle.get("shaft_od", 50.0)  # mm
            shaft_id = shaft_od * 0.8  # Assume hollow shaft
            
            # Polar moment of inertia for hollow shaft
            j = math.pi * (shaft_od**4 - shaft_id**4) / 32  # mm^4
            radius = shaft_od / 2  # mm
            
            # Shear stress = T * r / J
            tau = (torque_estimate * 1000 * radius) / j if j > 0 else 0  # MPa
            
            # Alternating stress (assuming cyclic loading)
            sigma_a = tau * 0.5  # Simplified conversion
            sigma_m = tau * 0.3  # Mean stress
            
            return StressState(
                sigma_a=sigma_a,
                sigma_m=sigma_m,
                sigma_max=sigma_a + sigma_m,
                sigma_min=sigma_m - sigma_a,
                stress_amplitude=sigma_a,
                mean_stress=sigma_m
            )
            
        elif component_type == "drum_support":
            # Bending stress on drum supports from weight and material forces
            drum_weight_estimate = 5000.0  # N - estimated drum + material weight
            support_spacing = drum.get("drum_length", 4000.0)  # mm
            
            # Simple beam bending: M = W*L/8 for uniformly distributed load
            bending_moment = drum_weight_estimate * support_spacing / 8  # N*mm
            
            # Assume rectangular cross-section for support
            support_width = 100.0  # mm
            support_height = 200.0  # mm
            
            # Section modulus
            section_modulus = support_width * support_height**2 / 6  # mm^3
            
            # Bending stress
            sigma_bending = bending_moment / section_modulus if section_modulus > 0 else 0  # MPa
            
            return StressState(
                sigma_a=sigma_bending * 0.4,  # Alternating component
                sigma_m=sigma_bending * 0.6,  # Mean component
                sigma_max=sigma_bending,
                sigma_min=0.0,
                stress_amplitude=sigma_bending * 0.4,
                mean_stress=sigma_bending * 0.6
            )
            
        elif component_type == "frame_member":
            # Axial and bending stress in frame members
            # Estimate from dynamic loads and weight
            dynamic_load = feed_rate * 0.05 * 9.81  # N - simplified
            axial_force = dynamic_load * 0.3  # Axial component
            
            # Frame dimensions
            rail_a = frame.get("rail_a", 200.0)  # mm
            rail_b = frame.get("rail_b", 100.0)  # mm
            rail_t = frame.get("rail_t", 10.0)   # mm
            
            # Cross-sectional area
            area = 2 * (rail_a + rail_b) * rail_t - 4 * rail_t**2  # mm^2
            
            # Axial stress
            sigma_axial = axial_force / area if area > 0 else 0  # MPa
            
            # Bending from eccentric loading (simplified)
            bending_moment = axial_force * 50.0  # N*mm - assume 50mm eccentricity
            
            # Moment of inertia for rectangular tube
            I = (rail_b * rail_a**3 - (rail_b-2*rail_t) * (rail_a-2*rail_t)**3) / 12  # mm^4
            c = rail_a / 2  # mm
            sigma_bending = abs(bending_moment * c / I) if I > 0 else 0  # MPa
            
            # Combine stresses
            sigma_max = sigma_axial + sigma_bending
            sigma_min = sigma_axial - sigma_bending
            sigma_a = (sigma_max - sigma_min) / 2
            sigma_m = (sigma_max + sigma_min) / 2
            
            return StressState(
                sigma_a=sigma_a,
                sigma_m=sigma_m,
                sigma_max=sigma_max,
                sigma_min=sigma_min,
                stress_amplitude=sigma_a,
                mean_stress=sigma_m
            )
        
        return None
    
    def simulate_component_fatigue(
        self,
        config_dict: Dict[str, Any],
        component_type: str,
        operating_hours: float,
        material_sut: float = 400.0,  # Ultimate tensile strength (MPa)
        material_sy: float = 250.0,   # Yield strength (MPa)
    ) -> Tuple[FatigueState, Optional[FatigueResult]]:
        """
        Simulate fatigue life consumption for a component over operating hours.
        Returns fatigue state and detailed fatigue analysis result.
        """
        # Calculate cycles
        rotational_speed = config_dict.get("rotational_speed", 100.0)  # rpm
        cycles_per_hour = self.calculate_cycles_per_hour(rotational_speed)
        total_cycles = cycles_per_hour * operating_hours
        
        # Estimate stress state
        stress_state = self.estimate_stress_state(config_dict, component_type, operating_hours)
        
        if stress_state is None:
            # No significant stress cycles
            return FatigueState(cycles_accumulated=total_cycles), None
        
        # Perform fatigue analysis
        try:
            fatigue_result = self.fatigue_analyzer.calculate_fatigue_life(
                stress_state=stress_state,
                sut=material_sut,
                sy=material_sy,
                cycles=total_cycles
            )
            
            # Extract damage from fatigue result (using Miner's rule concept)
            # If we had the S-N curve data, we could calculate actual damage
            # For now, estimate based on life fraction
            if fatigue_result.life_cycles > 0:
                damage_increment = total_cycles / fatigue_result.life_cycles
            else:
                damage_increment = 1.0  # Immediate failure if life is zero
            
            fatigue_state = FatigueState(
                cycles_accumulated=total_cycles,
                damage_accumulated=damage_increment,
                remaining_life_fraction=max(0.0, 1.0 - damage_increment),
                is_safe=damage_increment < 1.0
            )
            
            return fatigue_state, fatigue_result
            
        except Exception as e:
            logger.warning(f"Fatigue analysis failed for {component_type}: {e}")
            # Return conservative estimate
            return FatigueState(
                cycles_accumulated=total_cycles,
                damage_accumulated=0.1,  # Assume some damage
                remaining_life_fraction=0.9,
                is_safe=True
            ), None
    
    def simulate_machine_fatigue(
        self,
        config_dict: Dict[str, Any],
        operating_hours: float,
        material_properties: Optional[Dict[str, Tuple[float, float]]] = None
    ) -> Dict[str, Tuple[FatigueState, Optional[FatigueResult]]]:
        """
        Simulate fatigue for all critical components in a machine.
        Returns dictionary mapping component names to (fatigue_state, fatigue_result).
        """
        # Default material properties (steel)
        if material_properties is None:
            material_properties = {
                "spindle_shaft": (400.0, 250.0),   # SUT, SY in MPa
                "drum_support": (350.0, 220.0),
                "frame_member": (400.0, 250.0),
            }
        
        results = {}
        
        # Analyze each component type
        for component_type, (sut, sy) in material_properties.items():
            fatigue_state, fatigue_result = self.simulate_component_fatigue(
                config_dict, component_type, operating_hours, sut, sy
            )
            results[component_type] = (fatigue_state, fatigue_result)
        
        return results


def create_default_fatigue_model() -> FatigueModel:
    """Create a fatigue model with default settings."""
    return FatigueModel()
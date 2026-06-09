# app/digital_twin/wear_model.py
# Wear modeling for Digital Twin simulation

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("engine.digital_twin.wear_model")


@dataclass
class WearParameters:
    """Parameters for wear calculation."""
    # Archard wear equation parameters
    k: float = 1e-6           # Wear coefficient (dimensionless)
    H: float = 2e9            # Hardness (Pa) - typical for steel
    
    # Adhesive wear parameters
    adhesive_coefficient: float = 0.1
    
    # Abrasive wear parameters  
    abrasive_coefficient: float = 0.05
    
    # Surface roughness evolution
    initial_roughness: float = 0.8  # micrometers Ra
    roughness_growth_rate: float = 0.001  # micrometers/hour


@dataclass
class WearState:
    """Current wear state of a component."""
    volume_loss: float = 0.0        # mm^3 - material volume lost
    depth: float = 0.0              # mm - wear depth
    surface_roughness: float = 0.8  # micrometers Ra
    equivalent_strain: float = 0.0  # dimensionless - cumulative strain
    
    def is_significant(self, threshold: float = 0.1) -> bool:
        """Check if wear is significant (> threshold mm)."""
        return self.depth > threshold


class WearModel:
    """
    Models wear accumulation on machine components over time.
    Implements Archard wear equation and other wear mechanisms.
    """
    
    def __init__(self, parameters: Optional[WearParameters] = None):
        self.parameters = parameters or WearParameters()
        logger.debug("Initialized WearModel")
    
    def calculate_archard_wear(
        self, 
        normal_force: float,      # N - normal force
        sliding_distance: float,  # m - sliding distance
        hardness: Optional[float] = None  # Pa - material hardness
    ) -> float:
        """
        Calculate wear volume using Archard wear equation:
        V = k * F * s / H
        where V = wear volume (m^3), k = wear coefficient, 
        F = normal force (N), s = sliding distance (m), H = hardness (Pa)
        
        Returns wear volume in mm^3 for convenience.
        """
        H = hardness or self.parameters.H
        
        # Convert to consistent units
        # V in m^3, then convert to mm^3 (1 m^3 = 1e9 mm^3)
        wear_volume_m3 = (self.parameters.k * normal_force * sliding_distance) / H
        wear_volume_mm3 = wear_volume_m3 * 1e9
        
        return max(0.0, wear_volume_mm3)
    
    def calculate_adhesive_wear(
        self,
        normal_force: float,      # N
        sliding_distance: float,  # m
        contact_area: float,      # mm^2
    ) -> float:
        """
        Calculate adhesive wear volume.
        Simplified model: proportional to normal force and sliding distance.
        """
        # Adhesive wear often modeled as fraction of normal load causing material transfer
        wear_volume_mm3 = (self.parameters.adhesive_coefficient * 
                          normal_force * sliding_distance / 1000)  # Simplified scaling
        return max(0.0, wear_volume_mm3)
    
    def calculate_abrasive_wear(
        self,
        normal_force: float,      # N
        sliding_distance: float,  # m
        abrasive_hardness: float, # HV - hardness of abrasive particles
        material_hardness: float, # HV - hardness of material
    ) -> float:
        """
        Calculate abrasive wear volume.
        Based on ratio of abrasive to material hardness.
        """
        if material_hardness <= 0:
            return 0.0
            
        hardness_ratio = min(abrasive_hardness / material_hardness, 10.0)  # Cap ratio
        wear_volume_mm3 = (self.parameters.abrasive_coefficient * 
                          normal_force * sliding_distance * hardness_ratio / 1000)
        return max(0.0, wear_volume_mm3)
    
    def update_wear_state(
        self,
        wear_state: WearState,
        wear_volume_mm3: float,
        contact_area_mm2: float = 1.0,
        operating_hours: float = 1.0
    ) -> WearState:
        """
        Update wear state based on accumulated wear volume.
        """
        # Calculate equivalent depth assuming uniform wear over contact area
        if contact_area_mm2 > 0:
            depth_increment = wear_volume_mm3 / contact_area_mm2  # mm
        else:
            depth_increment = 0.0
            
        # Update wear state
        new_state = WearState(
            volume_loss=wear_state.volume_loss + wear_volume_mm3,
            depth=wear_state.depth + depth_increment,
            surface_roughness=min(
                wear_state.surface_roughness + 
                self.parameters.roughness_growth_rate * operating_hours,
                50.0  # Cap roughness growth
            ),
            equivalent_strain=wear_state.equivalent_strain + (depth_increment / 10.0)  # Simplified
        )
        
        return new_state
    
    def simulate_spindle_wear(
        self,
        config_dict: Dict[str, Any],
        operating_hours: float,
        material_hardness_hv: float = 200.0  # Vickers hardness
    ) -> Dict[str, WearState]:
        """
        Simulate wear on spindle components over operating hours.
        Returns wear states for different spindle parts.
        """
        # Extract spindle parameters
        spindle = config_dict.get("spindle", {})
        flight_od = spindle.get("flight_od", 200.0)  # mm
        flight_thickness = spindle.get("flight_thickness", 10.0)  # mm
        shaft_od = spindle.get("shaft_od", 50.0)  # mm
        
        # Operational parameters
        rotational_speed = config_dict.get("rotational_speed", 100.0)  # rpm
        feed_rate = config_dict.get("feed_rate", 1000.0)  # kg/hr
        
        # Calculate sliding distances and forces
        # Flight surface sliding against material
        flight_surface_area = math.pi * flight_od * flight_thickness  # mm^2 approx
        material_contact_force = feed_rate * 9.81 / 3600  # Convert kg/hr to N (simplified)
        
        # Sliding distance = pi * OD * RPM * time / 1000 (to meters)
        sliding_distance_per_hour = (math.pi * flight_od / 1000) * rotational_speed  # m/hour
        total_sliding_distance = sliding_distance_per_hour * operating_hours  # m
        
        # Convert hardness from HV to Pa (approximate: 1 HV ≈ 9.807 MPa)
        hardness_pa = material_hardness_hv * 9.807e6
        
        # Calculate wear on flights
        flight_wear_volume = self.calculate_archard_wear(
            normal_force=material_contact_force,
            sliding_distance=total_sliding_distance,
            hardness=hardness_pa
        )
        
        # Shaft wear (simplified - bearing contact)
        shaft_contact_area = math.pi * shaft_od * 20  # Assume 20mm contact width
        shaft_normal_force = 5000.0  # N - estimated radial load
        shaft_sliding_distance = sliding_distance_per_hour * operating_hours * 0.1  # Less sliding
        
        shaft_wear_volume = self.calculate_archard_wear(
            normal_force=shaft_normal_force,
            sliding_distance=shaft_sliding_distance,
            hardness=hardness_pa
        )
        
        # Initialize and update wear states
        flight_wear_state = self.update_wear_state(
            WearState(), 
            flight_wear_volume,
            contact_area_mm2=flight_surface_area,
            operating_hours=operating_hours
        )
        
        shaft_wear_state = self.update_wear_state(
            WearState(),
            shaft_wear_volume,
            contact_area_mm2=shaft_contact_area,
            operating_hours=operating_hours
        )
        
        return {
            "flights": flight_wear_state,
            "shaft": shaft_wear_state
        }
    
    def simulate_drum_wear(
        self,
        config_dict: Dict[str, Any],
        operating_hours: float,
        material_hardness_hv: float = 200.0
    ) -> Dict[str, WearState]:
        """
        Simulate wear on drum components.
        """
        drum = config_dict.get("drum", {})
        drum_id = drum.get("drum_id", 1500.0)  # mm
        wall_thickness = drum.get("wall_thickness", 12.0)  # mm
        drum_length = drum.get("drum_length", 4000.0)  # mm
        
        rotational_speed = config_dict.get("rotational_speed", 100.0)  # rpm
        
        # Drum inner surface wears from material impact and abrasion
        inner_surface_area = math.pi * drum_id * drum_length  # mm^2
        
        # Impact force from material (simplified)
        impact_force = 2000.0  # N - estimated
        
        # Sliding/slipping distance at inner surface
        surface_speed = math.pi * drum_id * rotational_speed / 1000  # m/s
        slipping_distance = surface_speed * operating_hours * 3600 * 0.05  # 5% slipping
        
        hardness_pa = material_hardness_hv * 9.807e6
        
        # Wear from impact and abrasion
        impact_wear = self.calculate_archard_wear(
            normal_force=impact_force,
            sliding_distance=slipping_distance,
            hardness=hardness_pa
        )
        
        # Abrasive wear from material particles
        abrasive_wear = self.calculate_abrasive_wear(
            normal_force=impact_force,
            sliding_distance=slipping_distance,
            abrasive_hardness=600.0,  # SiO2 in biomass
            material_hardness=material_hardness_hv
        )
        
        total_wear_volume = impact_wear + abrasive_wear
        
        drum_wear_state = self.update_wear_state(
            WearState(),
            total_wear_volume,
            contact_area_mm2=inner_surface_area,
            operating_hours=operating_hours
        )
        
        return {
            "inner_surface": drum_wear_state,
            "outer_surface": WearState()  # Less wear on outside
        }
    
    def simulate_bearing_wear(
        self,
        config_dict: Dict[str, Any],
        operating_hours: float,
        material_hardness_hv: float = 200.0
    ) -> Dict[str, WearState]:
        """
        Simulate wear on bearings (simplified).
        """
        # Bearing wear is complex - simplified model based on load and speed
        rotational_speed = config_dict.get("rotational_speed", 100.0)  # rpm
        feed_rate = config_dict.get("feed_rate", 1000.0)  # kg/hr
        
        # Estimated bearing load (radial + axial)
        radial_load = feed_rate * 0.5 * 9.81 / 3600  # N - simplified
        axial_load = feed_rate * 0.2 * 9.81 / 3600   # N - simplified
        equivalent_load = math.sqrt(radial_load**2 + axial_load**2)
        
        # Bearing surface area (simplified)
        bearing_area = 500.0  # mm^2 - typical for medium bearing
        
        # Sliding distance in bearing (micro-slippage)
        sliding_distance = operating_hours * 0.1  # Much less than gears
        
        hardness_pa = material_hardness_hv * 9.807e6
        
        wear_volume = self.calculate_archard_wear(
            normal_force=equivalent_load,
            sliding_distance=sliding_distance,
            hardness=hardness_pa
        )
        
        bearing_wear_state = self.update_wear_state(
            WearState(),
            wear_volume,
            contact_area_mm2=bearing_area,
            operating_hours=operating_hours
        )
        
        return {
            "bearing": bearing_wear_state
        }


def create_default_wear_model() -> WearModel:
    """Create a wear model with default parameters suitable for steel machinery."""
    return WearModel(WearParameters(
        k=8e-7,          # Adjusted for steel-on-steel with lubrication
        H=3e9,           # Hardened steel ~3 GPa
        adhesive_coefficient=0.05,
        abrasive_coefficient=0.03,
        initial_roughness=0.4,
        roughness_growth_rate=0.0005
    ))
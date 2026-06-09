# app/physics/shafts.py
# Shaft analysis module for deflection, stress, and critical speed calculations

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("engine.physics.shafts")


@dataclass
class ShaftGeometry:
    """Shaft geometric properties."""
    diameter: float  # mm
    length: float    # mm
    youngs_modulus: float = 200e3  # MPa (default for steel)
    shear_modulus: float = 80e3    # MPa (default for steel)
    density: float = 7.85e-6       # kg/mm^3 (default for steel)
    thermal_expansion: float = 12.0e-6  # 1/°C (default for steel)
    reference_temperature: float = 20.0  # °C (reference temperature for zero thermal strain)


@dataclass
class ShaftLoads:
    """Loads applied to the shaft."""
    torque: float = 0.0        # N*m
    bending_moment: float = 0.0  # N*m
    axial_force: float = 0.0   # N (positive = tension)
    transverse_force: float = 0.0  # N (perpendicular to axis)
    temperature_change: float = 0.0  # °C (temperature change from reference)


@dataclass
class ShaftResults:
    """Results from shaft analysis."""
    max_shear_stress: float = 0.0      # MPa
    max_bending_stress: float = 0.0    # MPa
    max_principal_stress: float = 0.0  # MPa
    von_mises_stress: float = 0.0      # MPa
    deflection: float = 0.0            # mm
    angle_of_twist: float = 0.0        # degrees
    safety_factor: float = float('inf') # dimensionless
    passed: bool = True
    notes: List[str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


class ShaftAnalyzer:
    """Analyzes shaft deflection, stress, and critical speed."""

    def __init__(self, geometry: ShaftGeometry):
        self.geometry = geometry
        logger.debug(f"Initialized ShaftAnalyzer with geometry: {geometry}")

    def calculate_torsional_stress(self, torque: float) -> float:
        """
        Calculate maximum torsional shear stress in a circular shaft.
        
        Formula: τ = T * r / J
        Where T = torque (N*m), r = radius (mm), J = polar moment of inertia (mm^4)
        
        Args:
            torque: Applied torque in N*m
            
        Returns:
            Maximum shear stress in MPa
        """
        radius = self.geometry.diameter / 2.0  # mm
        # Polar moment of inertia for solid circular shaft: J = π * d^4 / 32
        J = math.pi * self.geometry.diameter**4 / 32.0  # mm^4
        # Convert torque from N*m to N*mm: 1 N*m = 1000 N*mm
        torque_nmm = torque * 1000.0
        
        if J == 0:
            logger.warning("Polar moment of inertia is zero - invalid diameter")
            return 0.0
            
        shear_stress = torque_nmm * radius / J  # MPa (since N*mm * mm / mm^4 = N/mm^2 = MPa)
        logger.debug(f"Torsional stress: {shear_stress:.3f} MPa for torque {torque} N*m")
        return abs(shear_stress)

    def calculate_bending_stress(self, bending_moment: float) -> float:
        """
        Calculate maximum bending stress in a circular shaft.
        
        Formula: σ = M * c / I
        Where M = bending moment (N*m), c = distance from neutral axis (mm), 
              I = area moment of inertia (mm^4)
        
        Args:
            bending_moment: Applied bending moment in N*m
            
        Returns:
            Maximum bending stress in MPa
        """
        radius = self.geometry.diameter / 2.0  # mm
        # Area moment of inertia for solid circular shaft: I = π * d^4 / 64
        I = math.pi * self.geometry.diameter**4 / 64.0  # mm^4
        # Convert bending moment from N*m to N*mm
        moment_nmm = bending_moment * 1000.0
        
        if I == 0:
            logger.warning("Area moment of inertia is zero - invalid diameter")
            return 0.0
            
        bending_stress = moment_nmm * radius / I  # MPa
        logger.debug(f"Bending stress: {bending_stress:.3f} MPa for moment {bending_moment} N*m")
        return abs(bending_stress)

    def calculate_deflection(
        self, 
        force: float, 
        length: Optional[float] = None,
        case: str = "cantilever_end"
    ) -> float:
        """
        Calculate shaft deflection under transverse load.
        
        Supported cases:
        - cantilever_end: point load at free end (δ = F*L^3/(3*E*I))
        - simply_supported_center: point load at center (δ = F*L^3/(48*E*I))
        - fixed_fixed_center: point load at center (δ = F*L^3/(192*E*I))
        
        Args:
            force: Transverse force in N
            length: Shaft length (mm) - if None, uses geometry.length
            case: Boundary condition case
            
        Returns:
            Deflection in mm
        """
        if length is None:
            length = self.geometry.length
            
        # Area moment of inertia
        I = math.pi * self.geometry.diameter**4 / 64.0  # mm^4
        E = self.geometry.youngs_modulus  # MPa
        
        if I == 0 or E == 0:
            logger.warning("Invalid moment of inertia or Young's modulus")
            return 0.0
            
        # Convert force to N (already in N) and length to mm
        # Formulas give deflection in mm when using N, mm, MPa
        
        if case == "cantilever_end":
            deflection = force * length**3 / (3.0 * E * I)
        elif case == "simply_supported_center":
            deflection = force * length**3 / (48.0 * E * I)
        elif case == "fixed_fixed_center":
            deflection = force * length**3 / (192.0 * E * I)
        else:
            logger.warning(f"Unknown deflection case: {case}. Using cantilever_end.")
            deflection = force * length**3 / (3.0 * E * I)
            
        logger.debug(f"Deflection: {deflection:.4f} mm for {force} N force, case: {case}")
        return deflection

    def calculate_angle_of_twist(self, torque: float, length: Optional[float] = None) -> float:
        """
        Calculate angle of twist due to applied torque.
        
        Formula: φ = T * L / (G * J)
        Where T = torque (N*m), L = length (mm), G = shear modulus (MPa), 
              J = polar moment of inertia (mm^4)
        
        Args:
            torque: Applied torque in N*m
            length: Shaft length (mm) - if None, uses geometry.length
            
        Returns:
            Angle of twist in degrees
        """
        if length is None:
            length = self.geometry.length
            
        radius = self.geometry.diameter / 2.0  # mm
        J = math.pi * self.geometry.diameter**4 / 32.0  # mm^4
        G = self.geometry.shear_modulus  # MPa
        
        if J == 0 or G == 0:
            logger.warning("Invalid polar moment of inertia or shear modulus")
            return 0.0
            
        # Convert torque from N*m to N*mm
        torque_nmm = torque * 1000.0
        
        # Angle in radians: T*L/(G*J)
        angle_rad = torque_nmm * length / (G * J)
        # Convert to degrees
        angle_deg = math.degrees(angle_rad)
        
        logger.debug(f"Angle of twist: {angle_deg:.4f} degrees for torque {torque} N*m")
        return angle_deg

    def calculate_thermal_stress(self, temperature_change: float) -> float:
        """Calculate thermal stress due to temperature change.
        
        For a constrained shaft, thermal stress = E * α * ΔT
        Where E = Young's modulus, α = coefficient of thermal expansion, ΔT = temperature change
        
        Args:
            temperature_change: Temperature change in °C (positive = heating)
            
        Returns:
            Thermal stress in MPa (positive = tensile)
        """
        if self.geometry.youngs_modulus <= 0 or self.geometry.thermal_expansion <= 0:
            logger.warning("Invalid Young's modulus or thermal expansion coefficient")
            return 0.0
            
        thermal_stress = self.geometry.youngs_modulus * self.geometry.thermal_expansion * temperature_change
        logger.debug(f"Thermal stress: {thermal_stress:.3f} MPa for ΔT={temperature_change:.1f}°C "
                    f"(E={self.geometry.youngs_modulus:.0f} MPa, α={self.geometry.thermal_expansion:.2e})")
        return thermal_stress

    def calculate_principal_stresses(
        self, 
        sigma_x: float,  # normal stress in x direction (bending/axial)
        tau_xy: float    # shear stress (torsion)
    ) -> Tuple[float, float, float]:
        """
        Calculate principal stresses from normal and shear stresses.
        
        For 2D stress state (σx, 0, τxy):
        σ1,2 = (σx/2) ± √((σx/2)^2 + τxy^2)
        τmax = √((σx/2)^2 + τxy^2)
        
        Args:
            sigma_x: Normal stress in MPa
            tau_xy: Shear stress in MPa
            
        Returns:
            Tuple of (σ1, σ2, τmax) in MPa
        """
        avg_stress = sigma_x / 2.0
        radius = math.sqrt((sigma_x / 2.0)**2 + tau_xy**2)
        
        sigma1 = avg_stress + radius
        sigma2 = avg_stress - radius
        tau_max = radius
        
        logger.debug(f"Principal stresses: σ1={sigma1:.3f}, σ2={sigma2:.3f}, τmax={tau_max:.3f} MPa")
        return sigma1, sigma2, tau_max

    def calculate_von_mises_stress(
        self, 
        sigma_x: float,  # normal stress
        tau_xy: float    # shear stress
    ) -> float:
        """
        Calculate von Mises equivalent stress for 2D stress state.
        
        Formula: σ_vm = √(σx^2 + 3*τxy^2)
        
        Args:
            sigma_x: Normal stress in MPa
            tau_xy: Shear stress in MPa
            
        Returns:
            Von Mises stress in MPa
        """
        von_mises = math.sqrt(sigma_x**2 + 3.0 * tau_xy**2)
        logger.debug(f"Von Mises stress: {von_mises:.3f} MPa")
        return von_mises

    def analyze_shaft(
        self, 
        loads: ShaftLoads,
        allowable_stress: Optional[float] = None
    ) -> ShaftResults:
        """
        Perform complete shaft analysis combining all loads.
        
        Args:
            loads: ShaftLoads object containing applied forces and moments
            allowable_stress: Allowable stress for material (MPa) - if None, 
                            uses 60% of yield strength for steel (approximate)
            
        Returns:
            ShaftResults object with stress, deflection, and safety factors
        """
        logger.info("Starting shaft analysis")
        
        # Calculate individual stress components
        tau_torsion = self.calculate_torsional_stress(loads.torque)
        sigma_bending = self.calculate_bending_stress(loads.bending_moment)
        
        # For combined loading, we assume bending and torsion occur at same point
        # Normal stress from bending and axial force
        area = math.pi * (self.geometry.diameter / 2.0)**2  # mm^2
        sigma_axial = loads.axial_force / area if area > 0 else 0.0  # MPa
        
        # Thermal stress (if temperature change is specified)
        sigma_thermal = self.calculate_thermal_stress(loads.temperature_change)
        
        # Total normal stress
        sigma_x = sigma_bending + sigma_axial + sigma_thermal
        
        # Shear stress from torsion and transverse force (simplified)
        # For transverse shear stress in circular section: τ = 4V/(3A)
        # But we'll focus on torsion as primary shear for now
        tau_xy = tau_torsion  # Could add transverse shear contribution
        
        # Calculate principal stresses and von Mises
        sigma1, sigma2, tau_max = self.calculate_principal_stresses(sigma_x, tau_xy)
        von_mises = self.calculate_von_mises_stress(sigma_x, tau_xy)
        
        # Calculate deflection (assuming transverse force causes bending)
        deflection = self.calculate_deflection(
            loads.transverse_force, 
            case="cantilever_end"  # Simplified assumption
        )
        
        # Calculate angle of twist
        angle_of_twist = self.calculate_angle_of_twist(loads.torque)
        
        # Determine allowable stress if not provided
        if allowable_stress is None:
            # Approximate yield strength for steel (can be made configurable)
            yield_strength = 250.0  # MPa for mild steel
            allowable_stress = 0.6 * yield_strength  # 60% of yield
            logger.debug(f"No allowable stress provided, using {allowable_stress:.1f} MPa (60% of yield)")
        
        # Calculate safety factor based on von Mises stress
        if von_mises > 0:
            safety_factor = allowable_stress / von_mises
        else:
            safety_factor = float('inf')
            
        # Check if design passes
        passed = von_mises <= allowable_stress and deflection < (self.geometry.length / 250.0)  # L/250 deflection limit
        
        # Prepare notes
        notes = []
        if von_mises > allowable_stress:
            notes.append(f"Von Mises stress ({von_mises:.1f} MPa) exceeds allowable ({allowable_stress:.1f} MPa)")
        if deflection >= self.geometry.length / 250.0:
            notes.append(f"Deflection ({deflection:.3f} mm) exceeds L/250 limit ({self.geometry.length/250.0:.3f} mm)")
        if loads.torque == 0 and loads.bending_moment == 0 and loads.temperature_change == 0:
            notes.append("No significant loads applied")
        elif loads.temperature_change != 0:
            notes.append(f"Thermal stress included: {sigma_thermal:.1f} MPa for ΔT={loads.temperature_change:.1f}°C")
            
        results = ShaftResults(
            max_shear_stress=tau_max,
            max_bending_stress=abs(sigma_bending),
            max_principal_stress=max(abs(sigma1), abs(sigma2)),
            von_mises_stress=von_mises,
            deflection=deflection,
            angle_of_twist=angle_of_twist,
            safety_factor=safety_factor,
            passed=passed,
            notes=notes
        )
        
        logger.info(f"Shaft analysis complete. Passed: {passed}, Safety factor: {safety_factor:.2f}")
        return results


# Convenience functions for direct use
def analyze_simple_shaft(
    diameter: float,
    length: float,
    torque: float = 0.0,
    bending_moment: float = 0.0,
    transverse_force: float = 0.0,
    axial_force: float = 0.0,
    youngs_modulus: float = 200e3,
    shear_modulus: float = 80e3,
    allowable_stress: Optional[float] = None,
    temperature_change: float = 0.0
) -> ShaftResults:
    """
    Convenience function for simple shaft analysis.
    
    Args:
        diameter: Shaft diameter in mm
        length: Shaft length in mm
        torque: Applied torque in N*m
        bending_moment: Applied bending moment in N*m
        transverse_force: Transverse force in N
        axial_force: Axial force in N (positive = tension)
        youngs_modulus: Young's modulus in MPa (default: steel)
        shear_modulus: Shear modulus in MPa (default: steel)
        allowable_stress: Allowable stress in MPa (optional)
        
    Returns:
        ShaftResults object
    """
    geometry = ShaftGeometry(
        diameter=diameter,
        length=length,
        youngs_modulus=youngs_modulus,
        shear_modulus=shear_modulus
    )
    loads = ShaftLoads(
        torque=torque,
        bending_moment=bending_moment,
        transverse_force=transverse_force,
        axial_force=axial_force,
        temperature_change=temperature_change
    )
    
    analyzer = ShaftAnalyzer(geometry)
    return analyzer.analyze_shaft(loads, allowable_stress)


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.DEBUG)
    
    # Analyze a simple steel shaft
    results = analyze_simple_shaft(
        diameter=25.0,      # mm
        length=200.0,       # mm
        torque=50.0,        # N*m
        bending_moment=100.0, # N*m
        transverse_force=500.0, # N
        allowable_stress=150.0  # MPa
    )
    
    print(f"Shaft Analysis Results:")
    print(f"  Von Mises Stress: {results.von_mises_stress:.2f} MPa")
    print(f"  Safety Factor: {results.safety_factor:.2f}")
    print(f"  Deflection: {results.deflection:.3f} mm")
    print(f"  Angle of Twist: {results.angle_of_twist:.2f} degrees")
    print(f"  Passed: {results.passed}")
    if results.notes:
        print(f"  Notes: {', '.join(results.notes)}")
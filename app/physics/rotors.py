# app/physics/rotors.py
# Rotor analysis module for dynamics, imbalance, and critical speed calculations

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("engine.physics.rotors")


@dataclass
class RotorGeometry:
    """Geometric properties of the rotor."""
    length: float  # mm
    outer_diameter: float  # mm
    inner_diameter: float = 0.0  # mm (0 for solid shaft)
    density: float = 7.85e-6  # kg/mm^3 (default for steel)
    youngs_modulus: float = 200e3  # MPa
    shear_modulus: float = 80e3  # MPa
    # Thermal properties
    thermal_expansion: float = 12.0e-6  # 1/°C (default for steel)
    reference_temperature: float = 20.0  # °C (reference temperature for zero thermal strain)


@dataclass
class RotorLoads:
    """Loads and disturbances applied to the rotor."""
    torque: float = 0.0           # N*m (applied torque)
    axial_force: float = 0.0      # N (axial force)
    imbalance_magnitude: float = 0.0  # g*mm (imbalance: mass * eccentricity)
    imbalance_angle: float = 0.0  # degrees (phase angle of imbalance)
    foundation_stiffness: float = 0.0  # N/mm (bearing support stiffness)
    foundation_damping: float = 0.0    # N*s/mm (bearing support damping)
    temperature_change: float = 0.0  # °C (change from reference temperature)


@dataclass
class RotorResults:
    """Results from rotor analysis."""
    critical_speed: float = 0.0         # rpm (first critical speed)
    critical_speeds: List[float] = None # rpm (multiple critical speeds)
    imbalance_response: float = 0.0     # mm (vibration amplitude due to imbalance)
    imbalance_force: float = 0.0        # N (centrifugal force from imbalance)
    torque_angle_of_twist: float = 0.0  # degrees (twist due to applied torque)
    natural_frequency: float = 0.0      # Hz (fundamental frequency)
    stability_margin: float = float('inf') # dimensionless (distance from instability)
    passed: bool = True
    notes: List[str] = None
    failure_mode: Optional[str] = None
    operating_speed: float = 0.0        # rpm (for stability check)

    def __post_init__(self):
        if self.critical_speeds is None:
            self.critical_speeds = []
        if self.notes is None:
            self.notes = []


class RotorAnalyzer:
    """Analyzes rotor dynamics, critical speeds, and imbalance response."""

    def __init__(self, geometry: RotorGeometry):
        self.geometry = geometry
        logger.debug(f"Initialized RotorAnalyzer with geometry: {geometry}")

    def calculate_temperature_adjusted_properties(self, temperature_change: float) -> Dict[str, float]:
        """
        Calculate temperature-adjusted material and geometric properties.
        
        Args:
            temperature_change: Temperature change from reference in °C
            
        Returns:
            Dictionary containing adjusted properties:
            - length: Adjusted length (mm)
            - outer_diameter: Adjusted outer diameter (mm)
            - inner_diameter: Adjusted inner diameter (mm)
            - youngs_modulus: Adjusted Young's modulus (MPa)
            - shear_modulus: Adjusted shear modulus (MPa)
            - density: Adjusted density (kg/mm^3)
        """
        # Calculate linear thermal strain
        thermal_strain = self.geometry.thermal_expansion * temperature_change
        
        # Adjust dimensions (assuming isotropic expansion)
        adjusted_length = self.geometry.length * (1.0 + thermal_strain)
        adjusted_outer_diameter = self.geometry.outer_diameter * (1.0 + thermal_strain)
        adjusted_inner_diameter = self.geometry.inner_diameter * (1.0 + thermal_strain)
        
        # Adjust material properties (simplified model - properties decrease with temperature)
        # For steel, approximate property change: ~0.1% per °C decrease in modulus
        temp_coefficient_modulus = -0.001  # per °C (approximate for steel)
        modulus_factor = 1.0 + temp_coefficient_modulus * temperature_change
        adjusted_youngs_modulus = max(self.geometry.youngs_modulus * modulus_factor, 0.0)
        adjusted_shear_modulus = max(self.geometry.shear_modulus * modulus_factor, 0.0)
        
        # Adjust density (mass constant, volume increases with temperature^3)
        # For small temperature changes, approximate as linear
        volume_factor = (1.0 + thermal_strain)**3
        adjusted_density = self.geometry.density / volume_factor if volume_factor > 0 else 0.0
        
        return {
            'length': adjusted_length,
            'outer_diameter': adjusted_outer_diameter,
            'inner_diameter': adjusted_inner_diameter,
            'youngs_modulus': adjusted_youngs_modulus,
            'shear_modulus': adjusted_shear_modulus,
            'density': adjusted_density
        }

    def calculate_polar_moment_of_inertia(self) -> float:
        """
        Calculate polar moment of inertia for the rotor shaft.
        
        For hollow circular section: J = π/2 * (r_outer^4 - r_inner^4)
        
        Returns:
            Polar moment of inertia in mm^4
        """
        r_outer = self.geometry.outer_diameter / 2.0  # mm
        r_inner = self.geometry.inner_diameter / 2.0  # mm
        
        if r_outer <= r_inner:
            logger.warning("Inner diameter must be less than outer diameter")
            return 0.0
            
        J = (math.pi / 2.0) * (r_outer**4 - r_inner**4)  # mm^4
        logger.debug(f"Polar moment of inertia: {J:.2e} mm^4")
        return J

    def calculate_mass_moment_of_inertia(self) -> float:
        """
        Calculate mass moment of inertia for the rotor shaft.
        
        For hollow circular section: I = (π/2) * ρ * L * (r_outer^4 - r_inner^4)
        Where ρ = density (kg/mm^3), L = length (mm)
        
        Returns:
            Mass moment of inertia in kg*mm^2
        """
        r_outer = self.geometry.outer_diameter / 2.0  # mm
        r_inner = self.geometry.inner_diameter / 2.0  # mm
        L = self.geometry.length  # mm
        rho = self.geometry.density  # kg/mm^3
        
        if r_outer <= r_inner or L <= 0:
            logger.warning("Invalid dimensions for mass moment of inertia calculation")
            return 0.0
            
        I = (math.pi / 2.0) * rho * L * (r_outer**4 - r_inner**4)  # kg*mm^2
        logger.debug(f"Mass moment of inertia: {I:.2e} kg*mm^2")
        return I

    def calculate_first_critical_speed(self) -> float:
        """
        Calculate first critical speed for a simply supported uniform shaft.
        
        Formula: ω_cr = π * sqrt(g * δ_st)  (Rayleigh's method approximation)
        More accurately for uniform shaft: ω_cr = (π^2 / L^2) * sqrt(E*I / (ρ*A))
        Where g = gravity, δ_st = static deflection, E = Young's modulus,
              I = area moment of inertia, ρ = density, A = cross-sectional area, L = length
        
        Returns:
            Critical speed in rpm
        """
        # Calculate area moment of inertia (for bending)
        r_outer = self.geometry.outer_diameter / 2.0  # mm
        r_inner = self.geometry.inner_diameter / 2.0  # mm
        I = (math.pi / 4.0) * (r_outer**4 - r_inner**4)  # mm^4 (area moment of inertia)
        
        # Calculate cross-sectional area
        A = math.pi * (r_outer**2 - r_inner**2)  # mm^2
        
        if I <= 0 or A <= 0 or self.geometry.length <= 0:
            logger.warning("Invalid parameters for critical speed calculation")
            return 0.0
            
        if self.geometry.youngs_modulus <= 0 or self.geometry.density <= 0:
            logger.warning("Material properties invalid for critical speed calculation")
            return 0.0
            
        # ω_cr = (π^2 / L^2) * sqrt(E*I / (ρ*A))  [rad/s]
        omega_cr = (math.pi**2 / self.geometry.length**2) * math.sqrt(
            (self.geometry.youngs_modulus * I) / (self.geometry.density * A)
        )  # rad/s
        
        # Convert to rpm: N_cr = ω_cr * 60 / (2π)
        n_cr = omega_cr * 60.0 / (2.0 * math.pi)  # rpm
        
        logger.debug(f"First critical speed: {n_cr:.2f} rpm "
                    f"(E={self.geometry.youngs_modulus:.0f} MPa, I={I:.2e} mm^4, "
                    f"ρ={self.geometry.density:.2e} kg/mm^3, A={A:.2f} mm^2, L={self.geometry.length:.2f} mm)")
        return n_cr

    def calculate_multiple_critical_speeds(self, num_modes: int = 3) -> List[float]:
        """
        Calculate multiple critical speeds for a simply supported uniform shaft.
        
        Formula: ω_n = (n^2 * π^2 / L^2) * sqrt(E*I / (ρ*A))  [rad/s]
        Where n = mode number (1,2,3,...)
        
        Args:
            num_modes: Number of modes to calculate
            
        Returns:
            List of critical speeds in rpm for modes 1 to num_modes
        """
        # Calculate area moment of inertia (for bending)
        r_outer = self.geometry.outer_diameter / 2.0  # mm
        r_inner = self.geometry.inner_diameter / 2.0  # mm
        I = (math.pi / 4.0) * (r_outer**4 - r_inner**4)  # mm^4
        
        # Calculate cross-sectional area
        A = math.pi * (r_outer**2 - r_inner**2)  # mm^2
        
        if I <= 0 or A <= 0 or self.geometry.length <= 0:
            logger.warning("Invalid parameters for critical speed calculation")
            return [0.0] * num_modes
            
        if self.geometry.youngs_modulus <= 0 or self.geometry.density <= 0:
            logger.warning("Material properties invalid for critical speed calculation")
            return [0.0] * num_modes
            
        # Base term: (π^2 / L^2) * sqrt(E*I / (ρ*A)) [rad/s] for n=1
        base_term = (math.pi**2 / self.geometry.length**2) * math.sqrt(
            (self.geometry.youngs_modulus * I) / (self.geometry.density * A)
        )  # rad/s
        
        critical_speeds = []
        for n in range(1, num_modes + 1):
            # ω_n = n^2 * base_term
            omega_n = (n**2) * base_term  # rad/s
            # Convert to rpm
            n_rpm = omega_n * 60.0 / (2.0 * math.pi)  # rpm
            critical_speeds.append(n_rpm)
            logger.debug(f"Critical speed mode {n}: {n_rpm:.2f} rpm")
            
        return critical_speeds

    def calculate_imbalance_force(self, imbalance_magnitude: float, speed: float) -> float:
        """
        Calculate centrifugal force due to rotor imbalance.
        
        Formula: F = m * e * ω^2
        Where m*e = imbalance magnitude (g*mm), ω = angular velocity (rad/s)
        Note: Convert g*mm to kg*m for proper units
        
        Args:
            imbalance_magnitude: Imbalance magnitude in g*mm
            speed: Rotational speed in rpm
            
        Returns:
            Centrifugal force in N
        """
        if speed < 0:
            logger.warning("Speed cannot be negative")
            return 0.0
            
        # Convert imbalance from g*mm to kg*m
        # 1 g = 0.001 kg, 1 mm = 0.001 m → 1 g*mm = 1e-6 kg*m
        imbalance_kgm = imbalance_magnitude * 1e-6  # kg*m
        
        # Convert speed from rpm to rad/s
        omega = speed * math.pi / 30.0  # rad/s
        
        # Centrifugal force: F = m*e*ω^2
        force = imbalance_kgm * omega**2  # N
        
        logger.debug(f"Imbalance force: {force:.4f} N "
                    f"(imbalance={imbalance_magnitude:.2f} g*mm, speed={speed:.2f} rpm)")
        return force

    def calculate_imbalance_response(
        self, 
        imbalance_magnitude: float, 
        speed: float,
        stiffness: float = 0.0,
        damping: float = 0.0
    ) -> float:
        """
        Calculate vibration amplitude due to imbalance (simplified SDOF model).
        
        Formula: X = (m*e * ω^2) / k  for undamped case at steady state
        Where m*e = imbalance magnitude, ω = angular velocity, k = stiffness
        
        More accurately for damped system: 
        X = (m*e * ω^2) / sqrt((k - m*ω^2)^2 + (c*ω)^2)
        
        Args:
            imbalance_magnitude: Imbalance magnitude in g*mm
            speed: Rotational speed in rpm
            stiffness: Support stiffness in N/mm
            damping: Support damping in N*s/mm
            
        Returns:
            Vibration amplitude in mm
        """
        if speed < 0:
            logger.warning("Speed cannot be negative")
            return 0.0
            
        if stiffness <= 0:
            logger.warning("Stiffness must be positive for response calculation")
            return 0.0
            
        # Calculate imbalance force
        imbalance_force = self.calculate_imbalance_force(imbalance_magnitude, speed)  # N
        
        # Convert speed to rad/s
        omega = speed * math.pi / 30.0  # rad/s
        
        # For simplicity, we'll use a lumped mass approach
        # Calculate equivalent mass of rotor
        r_outer = self.geometry.outer_diameter / 2.0  # mm
        r_inner = self.geometry.inner_diameter / 2.0  # mm
        L = self.geometry.length  # mm
        rho = self.geometry.density  # kg/mm^3
        volume = math.pi * L * (r_outer**2 - r_inner**2)  # mm^3
        mass = volume * rho  # kg
        
        # Calculate response amplitude
        # X = F0 / sqrt((k - m*ω^2)^2 + (c*ω)^2)
        # Where F0 = imbalance_force (N)
        k_Nmm = stiffness  # N/mm
        c_Ns_mm = damping  # N*s/mm
        
        # Convert units: k in N/mm, m in kg, ω in rad/s
        # Need consistent units: convert k to N/m for standard formula
        k_Nm = k_Nmm * 1000.0  # N/m
        # Mass is already in kg
        # Damping: c in N*s/mm → N*s/m
        c_Ns_m = c_Ns_mm * 1000.0  # N*s/m
        
        denominator = math.sqrt((k_Nm - mass * omega**2)**2 + (c_Ns_m * omega)**2)
        
        if denominator == 0:
            logger.warning("Denominator zero in imbalance response calculation")
            return 0.0
            
        amplitude_m = imbalance_force / denominator  # meters
        amplitude_mm = amplitude_m * 1000.0  # mm
        
        logger.debug(f"Imbalance response: {amplitude_mm:.4f} mm "
                    f"(force={imbalance_force:.4f} N, speed={speed:.2f} rpm)")
        return amplitude_mm

    def calculate_twist_due_to_torque(self, torque: float, length: Optional[float] = None) -> float:
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
            
        if length <= 0:
            logger.warning("Length is zero or negative")
            return 0.0
            
        J = self.calculate_polar_moment_of_inertia()  # mm^4
        if J <= 0:
            logger.warning("Polar moment of inertia is zero or negative")
            return 0.0
            
        if self.geometry.shear_modulus <= 0:
            logger.warning("Shear modulus is zero or negative")
            return 0.0
            
        G = self.geometry.shear_modulus  # MPa
        
        # Convert torque from N*m to N*mm
        torque_nmm = torque * 1000.0
        
        # Angle in radians: T*L/(G*J)
        angle_rad = torque_nmm * length / (G * J)
        # Convert to degrees
        angle_deg = math.degrees(angle_rad)
        
        logger.debug(f"Torque angle of twist: {angle_deg:.4f} degrees for torque {torque:.2f} N*m")
        return angle_deg

    def calculate_natural_frequency(self) -> float:
        """
        Calculate fundamental natural frequency of the rotor system.
        
        For a simple shaft: f_n = (1/(2π)) * sqrt(k_eq / m_eq)
        Where k_eq = equivalent stiffness, m_eq = equivalent mass
        
        Using Rayleigh's method for uniform shaft:
        f_n = (π/(2L^2)) * sqrt(E*I / ρ)  [Hz]
        
        Returns:
            Natural frequency in Hz
        """
        # Area moment of inertia for bending
        r_outer = self.geometry.outer_diameter / 2.0  # mm
        r_inner = self.geometry.inner_diameter / 2.0  # mm
        I = (math.pi / 4.0) * (r_outer**4 - r_inner**4)  # mm^4
        
        if I <= 0 or self.geometry.length <= 0:
            logger.warning("Invalid parameters for natural frequency calculation")
            return 0.0
            
        if self.geometry.youngs_modulus <= 0 or self.geometry.density <= 0:
            logger.warning("Material properties invalid for natural frequency calculation")
            return 0.0
            
        # f_n = (π/(2L^2)) * sqrt(E*I / ρ)  [Hz]
        # E in MPa (N/mm^2), I in mm^4, ρ in kg/mm^3
        # sqrt(E*I/ρ) has units: sqrt((N/mm^2)*mm^4/(kg/mm^3)) = sqrt(N*mm^5/kg)
        # Since N = kg*mm/s^2 → sqrt(kg*mm/s^2 * mm^5/kg) = sqrt(mm^6/s^2) = mm^3/s
        # Then (1/L^2) * mm^3/s = (1/mm^2) * mm^3/s = mm/s → not Hz!
        # Let's use the correct formula from critical speed:
        # ω_n = sqrt(g / δ_st) where δ_st = static deflection
        # For simply supported shaft with uniform load: δ_st = (5*w*L^4)/(384*E*I)
        # w = weight per unit length = ρ*A*g
        # This gets complex. Let's use the relation: ω_cr = π * sqrt(g * δ_st)
        # And for uniform shaft, δ_st is proportional to L^4/(E*I)
        # Actually, from earlier: ω_cr = (π^2 / L^2) * sqrt(E*I / (ρ*A)) [rad/s]
        # So f_n = ω_cr / (2π) for the first mode
        
        omega_cr = self.calculate_first_critical_speed() * (2.0 * math.pi) / 60.0  # Convert rpm to rad/s
        f_n = omega_cr / (2.0 * math.pi)  # Hz
        
        logger.debug(f"Natural frequency: {f_n:.2f} Hz")
        return f_n

    def analyze_rotor(
        self, 
        loads: RotorLoads,
        operating_speed: float = 0.0
    ) -> RotorResults:
        """
        Perform complete rotor analysis.
        
        Args:
            loads: RotorLoads object containing applied loads and disturbances
            operating_speed: Operating speed for stability check (rpm)
            
        Returns:
            RotorResults object with critical speeds, imbalance response, and stability
        """
        logger.info("Starting rotor analysis")
        
        # Calculate temperature-adjusted properties if temperature change is specified
        if loads.temperature_change != 0.0:
            adjusted_props = self.calculate_temperature_adjusted_properties(loads.temperature_change)
            # Create temporary geometry with adjusted properties
            from dataclasses import replace
            adjusted_geometry = replace(
                self.geometry,
                length=adjusted_props['length'],
                outer_diameter=adjusted_props['outer_diameter'],
                inner_diameter=adjusted_props['inner_diameter'],
                youngs_modulus=adjusted_props['youngs_modulus'],
                shear_modulus=adjusted_props['shear_modulus'],
                density=adjusted_props['density']
            )
            # Use adjusted geometry for calculations
            temp_analyzer = RotorAnalyzer(adjusted_geometry)
            # Calculate critical speeds using adjusted geometry
            critical_speed = temp_analyzer.calculate_first_critical_speed()
            critical_speeds = temp_analyzer.calculate_multiple_critical_speeds(num_modes=3)
            
            # Calculate imbalance response using adjusted geometry
            imbalance_response = temp_analyzer.calculate_imbalance_response(
                loads.imbalance_magnitude,
                loads.torque if loads.torque > 0 else operating_speed,  # Use torque speed or operating speed
                loads.foundation_stiffness,
                loads.foundation_damping
            )
            
            # Calculate imbalance force using adjusted geometry
            imbalance_force = temp_analyzer.calculate_imbalance_force(
                loads.imbalance_magnitude,
                loads.torque if loads.torque > 0 else operating_speed
            )
            
            # Calculate torque angle of twist using adjusted geometry
            torque_angle_of_twist = temp_analyzer.calculate_twist_due_to_torque(loads.torque)
            
            # Calculate natural frequency using adjusted geometry
            natural_frequency = temp_analyzer.calculate_natural_frequency()
        else:
            # No temperature change - use original geometry
            critical_speed = self.calculate_first_critical_speed()
            critical_speeds = self.calculate_multiple_critical_speeds(num_modes=3)
            
            # Calculate imbalance response
            imbalance_response = self.calculate_imbalance_response(
                loads.imbalance_magnitude,
                loads.torque if loads.torque > 0 else operating_speed,  # Use torque speed or operating speed
                loads.foundation_stiffness,
                loads.foundation_damping
            )
            
            # Calculate imbalance force
            imbalance_force = self.calculate_imbalance_force(
                loads.imbalance_magnitude,
                loads.torque if loads.torque > 0 else operating_speed
            )
            
            # Calculate torque angle of twist
            torque_angle_of_twist = self.calculate_twist_due_to_torque(loads.torque)
            
            # Calculate natural frequency
            natural_frequency = self.calculate_natural_frequency()
        
        # Determine stability margin (simplified)
        # In practice, this would involve complex eigenvalue analysis
        # We'll use a simplified approach based on speed separation from critical speeds
        stability_margin = float('inf')
        if operating_speed > 0 and critical_speed > 0:
            # Margin as percentage separation from nearest critical speed
            speed_separations = [abs(operating_speed - cs) for cs in critical_speeds if cs > 0]
            if speed_separations:
                min_separation = min(speed_separations)
                # Stability margin as percentage of operating speed
                stability_margin = (min_separation / operating_speed) * 100.0 if operating_speed > 0 else float('inf')
            else:
                stability_margin = float('inf')
        else:
            stability_margin = float('inf')
        
        # Prepare notes
        # Determine if rotor passes basic checks
        passed = True
        notes = []
        failure_mode = None
        
        # Add note if thermal effects were considered
        if loads.temperature_change != 0.0:
            notes.append(f"Thermal effects included (ΔT={loads.temperature_change:.1f} °C)")
        
        # Check if operating speed is too close to critical speed
        if operating_speed > 0:
            too_close_threshold = 0.1  # Within 10% of critical speed is problematic
            for cs in critical_speeds:
                if cs > 0:
                    separation_ratio = abs(operating_speed - cs) / cs
                    if separation_ratio < too_close_threshold:
                        passed = False
                        notes.append(f"Operating speed ({operating_speed:.0f} rpm) is too close to critical speed ({cs:.0f} rpm)")
                        failure_mode = "resonance"
                        break
                        
        # Check for excessive vibration due to imbalance
        max_allowed_vibration = 0.1  # mm (typical limit for precision machinery)
        if imbalance_response > max_allowed_vibration:
            passed = False
            notes.append(f"Imbalance vibration ({imbalance_response:.4f} mm) exceeds limit ({max_allowed_vibration} mm)")
            if failure_mode is None:
                failure_mode = "excessive_vibration"
                
        # Check for excessive twist
        max_allowed_twist = 5.0  # degrees per meter (typical limit)
        twist_per_meter = torque_angle_of_twist / (self.geometry.length / 1000.0)  # degrees/meter
        if abs(twist_per_meter) > max_allowed_twist:
            passed = False
            notes.append(f"Twist ({twist_per_meter:.2f} degrees/m) exceeds limit ({max_allowed_twist} degrees/m)")
            if failure_mode is None:
                failure_mode = "excessive_twist"
                
        results = RotorResults(
            critical_speed=critical_speed,
            critical_speeds=critical_speeds,
            imbalance_response=imbalance_response,
            imbalance_force=imbalance_force,
            torque_angle_of_twist=torque_angle_of_twist,
            natural_frequency=natural_frequency,
            stability_margin=stability_margin,
            passed=passed,
            notes=notes,
            failure_mode=failure_mode,
            operating_speed=operating_speed
        )
        
        logger.info(f"Rotor analysis complete. Passed: {passed}, Critical speed: {critical_speed:.2f} rpm, "
                   f"Imbalance response: {imbalance_response:.4f} mm")
        return results


# Convenience functions for direct use
def analyze_rotor(
    length: float,
    outer_diameter: float,
    inner_diameter: float = 0.0,
    density: float = 7.85e-6,
    youngs_modulus: float = 200e3,
    shear_modulus: float = 80e3,
    torque: float = 0.0,
    axial_force: float = 0.0,
    imbalance_magnitude: float = 0.0,
    imbalance_angle: float = 0.0,
    foundation_stiffness: float = 0.0,
    foundation_damping: float = 0.0,
    operating_speed: float = 0.0
) -> RotorResults:
    """
    Convenience function for simple rotor analysis.
    
    Args:
        length: Rotor length in mm
        outer_diameter: Outer diameter in mm
        inner_diameter: Inner diameter in mm (0 for solid shaft)
        density: Density in kg/mm^3 (default: steel)
        youngs_modulus: Young's modulus in MPa (default: steel)
        shear_modulus: Shear modulus in MPa (default: steel)
        torque: Applied torque in N*m
        axial_force: Axial force in N
        imbalance_magnitude: Imbalance magnitude in g*mm
        imbalance_angle: Imbalance angle in degrees
        foundation_stiffness: Foundation stiffness in N/mm
        foundation_damping: Foundation damping in N*s/mm
        operating_speed: Operating speed in rpm
        
    Returns:
        RotorResults object
    """
    geometry = RotorGeometry(
        length=length,
        outer_diameter=outer_diameter,
        inner_diameter=inner_diameter,
        density=density,
        youngs_modulus=youngs_modulus,
        shear_modulus=shear_modulus
    )
    loads = RotorLoads(
        torque=torque,
        axial_force=axial_force,
        imbalance_magnitude=imbalance_magnitude,
        imbalance_angle=imbalance_angle,
        foundation_stiffness=foundation_stiffness,
        foundation_damping=foundation_damping
    )
    
    analyzer = RotorAnalyzer(geometry)
    return analyzer.analyze_rotor(loads, operating_speed)


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.DEBUG)
    
    print("=== Rotor Analysis WITHOUT Thermal Effects ===")
    # Analyze a simple rotor at reference temperature
    results_no_thermal = analyze_rotor(
        length=500.0,           # mm
        outer_diameter=50.0,    # mm
        inner_diameter=10.0,    # mm (hollow shaft)
        density=7.85e-6,        # kg/mm^3
        youngs_modulus=200e3,   # MPa
        shear_modulus=80e3,     # MPa
        torque=100.0,           # N*m
        axial_force=500.0,      # N
        imbalance_magnitude=50.0, # g*mm
        imbalance_angle=0.0,    # degrees
        foundation_stiffness=0.0, # N/mm
        foundation_damping=0.0,   # N*s/mm
        operating_speed=1500.0, # rpm
        temperature_change=0.0  # °C (no temperature change)
    )
    
    print(f"Rotor Analysis Results:")
    print(f"  First Critical Speed: {results_no_thermal.critical_speed:.2f} rpm")
    print(f"  Critical Speeds: {[f'{cs:.2f}' for cs in results_no_thermal.critical_speeds]} rpm")
    print(f"  Natural Frequency: {results_no_thermal.natural_frequency:.2f} Hz")
    print(f"  Imbalance Force: {results_no_thermal.imbalance_force:.4f} N")
    print(f"  Imbalance Response: {results_no_thermal.imbalance_response:.4f} mm")
    print(f"  Torque Angle of Twist: {results_no_thermal.torque_angle_of_twist:.2f} degrees")
    print(f"  Stability Margin: {results_no_thermal.stability_margin:.2f} %")
    print(f"  Operating Speed: {results_no_thermal.operating_speed:.2f} rpm")
    print(f"  Passed: {results_no_thermal.passed}")
    if results_no_thermal.notes:
        print(f"  Notes: {', '.join(results_no_thermal.notes)}")
    if results_no_thermal.failure_mode:
        print(f"  Failure Mode: {results_no_thermal.failure_mode}")
    
    print("\n=== Rotor Analysis WITH Thermal Effects (ΔT = 100°C) ===")
    # Analyze the same rotor with a 100°C temperature increase
    results_with_thermal = analyze_rotor(
        length=500.0,           # mm
        outer_diameter=50.0,    # mm
        inner_diameter=10.0,    # mm (hollow shaft)
        density=7.85e-6,        # kg/mm^3
        youngs_modulus=200e3,   # MPa
        shear_modulus=80e3,     # MPa
        torque=100.0,           # N*m
        axial_force=500.0,      # N
        imbalance_magnitude=50.0, # g*mm
        imbalance_angle=0.0,    # degrees
        foundation_stiffness=0.0, # N/mm
        foundation_damping=0.0,   # N*s/mm
        operating_speed=1500.0, # rpm
        temperature_change=100.0 # °C (100°C temperature increase)
    )
    
    print(f"Rotor Analysis Results:")
    print(f"  First Critical Speed: {results_with_thermal.critical_speed:.2f} rpm")
    print(f"  Critical Speeds: {[f'{cs:.2f}' for cs in results_with_thermal.critical_speeds]} rpm")
    print(f"  Natural Frequency: {results_with_thermal.natural_frequency:.2f} Hz")
    print(f"  Imbalance Force: {results_with_thermal.imbalance_force:.4f} N")
    print(f"  Imbalance Response: {results_with_thermal.imbalance_response:.4f} mm")
    print(f"  Torque Angle of Twist: {results_with_thermal.torque_angle_of_twist:.2f} degrees")
    print(f"  Stability Margin: {results_with_thermal.stability_margin:.2f} %")
    print(f"  Operating Speed: {results_with_thermal.operating_speed:.2f} rpm")
    print(f"  Passed: {results_with_thermal.passed}")
    if results_with_thermal.notes:
        print(f"  Notes: {', '.join(results_with_thermal.notes)}")
    if results_with_thermal.failure_mode:
        print(f"  Failure Mode: {results_with_thermal.failure_mode}")
    
    print("\n=== Comparison ===")
    critical_speed_change = results_with_thermal.critical_speed - results_no_thermal.critical_speed
    natural_freq_change = results_with_thermal.natural_frequency - results_no_thermal.natural_frequency
    imbalance_response_change = results_with_thermal.imbalance_response - results_no_thermal.imbalance_response
    twist_change = results_with_thermal.torque_angle_of_twist - results_no_thermal.torque_angle_of_twist
    
    print(f"Critical speed change: {critical_speed_change:.2f} rpm")
    print(f"Natural frequency change: {natural_freq_change:.4f} Hz")
    print(f"Imbalance response change: {imbalance_response_change:.6f} mm")
    print(f"Torque angle of twist change: {twist_change:.4f} degrees")
    print(f"First critical speed: {results_no_thermal.critical_speed:.2f} → {results_with_thermal.critical_speed:.2f} rpm")
    print(f"Stability margin: {results_no_thermal.stability_margin:.2f} → {results_with_thermal.stability_margin:.2f} %")
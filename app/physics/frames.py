# app/physics/frames.py
# Frame analysis module for beam bending, buckling, and structural stress calculations

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("engine.physics.frames")


@dataclass
class FrameMaterial:
    """Material properties for frame analysis."""
    youngs_modulus: float  # MPa
    yield_strength: float  # MPa
    ultimate_strength: float  # MPa
    shear_modulus: float  # MPa
    density: float  # kg/mm^3
    poisson_ratio: float = 0.3


@dataclass
class FrameGeometry:
    """Geometric properties of frame members."""
    length: float  # mm
    cross_section_area: float  # mm^2
    moment_of_inertia: float  # mm^4 (about bending axis)
    polar_moment_of_inertia: float  # mm^4 (for torsion)
    section_modulus: float  # mm^3 (I/c)
    radius_of_gyration: float  # mm (sqrt(I/A))
    effective_length_factor: float = 1.0  # For buckling (K)
    # Thermal properties
    thermal_expansion: float = 12.0e-6  # 1/°C (default for steel)
    reference_temperature: float = 20.0  # °C (reference temperature for zero thermal strain)


@dataclass
class FrameLoads:
    """Loads applied to frame members."""
    axial_force: float = 0.0      # N (positive = tension)
    shear_force: float = 0.0      # N (transverse)
    bending_moment: float = 0.0   # N*m
    torque: float = 0.0           # N*m
    distributed_load: float = 0.0 # N/mm (uniformly distributed)
    temperature_change: float = 0.0  # °C (change from reference temperature)


@dataclass
class FrameResults:
    """Results from frame analysis."""
    axial_stress: float = 0.0          # MPa
    shear_stress: float = 0.0          # MPa
    bending_stress: float = 0.0        # MPa
    torsional_stress: float = 0.0      # MPa
    von_mises_stress: float = 0.0      # MPa
    buckling_load: float = 0.0         # N (Euler critical load)
    deflection: float = 0.0            # mm
    angle_of_twist: float = 0.0        # degrees
    axial_safety_factor: float = float('inf')
    bending_safety_factor: float = float('inf')
    shear_safety_factor: float = float('inf')
    combined_safety_factor: float = float('inf')
    buckling_safety_factor: float = float('inf')
    passed: bool = True
    notes: List[str] = None
    failure_mode: Optional[str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


class FrameAnalyzer:
    """Analyzes frame members for stress, deflection, buckling, and stability."""

    def __init__(self, material: FrameMaterial, geometry: FrameGeometry):
        self.material = material
        self.geometry = geometry
        logger.debug(f"Initialized FrameAnalyzer with material and geometry")

    def calculate_temperature_adjusted_properties(self, temperature_change: float) -> Dict[str, float]:
        """
        Calculate temperature-adjusted geometric and material properties for frame member.

        Args:
            temperature_change: Temperature change from reference in C

        Returns:
            Dictionary of adjusted properties: length, cross_section_area,
            moment_of_inertia, polar_moment_of_inertia, section_modulus,
            radius_of_gyration, youngs_modulus, shear_modulus, density
        """
        if abs(temperature_change) < 0.5:
            return {
                "length": self.geometry.length,
                "cross_section_area": self.geometry.cross_section_area,
                "moment_of_inertia": self.geometry.moment_of_inertia,
                "polar_moment_of_inertia": self.geometry.polar_moment_of_inertia,
                "section_modulus": self.geometry.section_modulus,
                "radius_of_gyration": self.geometry.radius_of_gyration,
                "youngs_modulus": self.material.youngs_modulus,
                "shear_modulus": self.material.shear_modulus,
                "density": self.material.density,
            }

        thermal_strain = self.geometry.thermal_expansion * temperature_change

        adjusted_length = self.geometry.length * (1.0 + thermal_strain)
        adjusted_area = self.geometry.cross_section_area * (1.0 + thermal_strain) ** 2
        adjusted_inertia = self.geometry.moment_of_inertia * (1.0 + thermal_strain) ** 4
        adjusted_polar = self.geometry.polar_moment_of_inertia * (1.0 + thermal_strain) ** 4
        adjusted_section = self.geometry.section_modulus * (1.0 + thermal_strain) ** 3
        adjusted_radius = self.geometry.radius_of_gyration * (1.0 + thermal_strain)

        temp_coefficient_modulus = -0.001
        modulus_factor = 1.0 + temp_coefficient_modulus * temperature_change
        adjusted_youngs = max(self.material.youngs_modulus * modulus_factor, 0.0)
        adjusted_shear = max(self.material.shear_modulus * modulus_factor, 0.0)

        volume_factor = (1.0 + thermal_strain) ** 3
        adjusted_density = self.material.density / volume_factor if volume_factor > 0 else 0.0

        logger.info(
            f"Temperature-adjusted frame properties (dT={temperature_change:+.1f}C): "
            f"length={adjusted_length:.3f}mm, area={adjusted_area:.3f}mm2, "
            f"I={adjusted_inertia:.3f}mm4, E={adjusted_youngs:.0f}MPa"
        )

        return {
            "length": adjusted_length,
            "cross_section_area": adjusted_area,
            "moment_of_inertia": adjusted_inertia,
            "polar_moment_of_inertia": adjusted_polar,
            "section_modulus": adjusted_section,
            "radius_of_gyration": adjusted_radius,
            "youngs_modulus": adjusted_youngs,
            "shear_modulus": adjusted_shear,
            "density": adjusted_density,
        }

    def calculate_thermal_stress(self, temperature_change: float) -> float:
        """
        Calculate thermal stress due to temperature change.
        
        Formula: σ_thermal = E * α * ΔT
        Where E = Young's modulus (MPa), α = Coefficient of thermal expansion (1/°C),
              ΔT = Temperature change from reference (°C)
        
        Args:
            temperature_change: Temperature change from reference in °C
            
        Returns:
            Thermal stress in MPa (positive = tension)
        """
        if self.material.youngs_modulus <= 0:
            logger.warning("Young's modulus is zero or negative")
            return 0.0
            
        thermal_stress = self.material.youngs_modulus * self.geometry.thermal_expansion * temperature_change
        logger.debug(f"Thermal stress: {thermal_stress:.3f} MPa (E={self.material.youngs_modulus:.0f} MPa, "
                    f"α={self.geometry.thermal_expansion:.2e} 1/°C, ΔT={temperature_change:.1f} °C)")
        return thermal_stress

    def calculate_axial_stress(self, axial_force: float) -> float:
        """
        Calculate axial stress.
        
        Formula: σ = F / A
        Where F = axial force (N), A = cross-sectional area (mm^2)
        
        Args:
            axial_force: Applied axial force in N (positive = tension)
            
        Returns:
            Axial stress in MPa (positive = tension)
        """
        if self.geometry.cross_section_area <= 0:
            logger.warning("Cross-sectional area is zero or negative")
            return 0.0
            
        stress = axial_force / self.geometry.cross_section_area  # MPa
        logger.debug(f"Axial stress: {stress:.3f} MPa for force {axial_force:.2f} N")
        return stress

    def calculate_shear_stress(self, shear_force: float) -> float:
        """
        Calculate average shear stress.
        
        Formula: τ = F / A (for simplified calculation)
        For more accurate shear stress in beams: τ = VQ/(It) 
        But we'll use average for initial analysis.
        
        Args:
            shear_force: Applied shear force in N
            
        Returns:
            Average shear stress in MPa
        """
        if self.geometry.cross_section_area <= 0:
            logger.warning("Cross-sectional area is zero or negative")
            return 0.0
            
        # For rectangular sections, max shear stress is 1.5 * V/A
        # For circular sections, max shear stress is 4/3 * V/A
        # We'll use a shape factor of 1.33 as approximation
        shape_factor = 1.33
        stress = shape_factor * shear_force / self.geometry.cross_section_area  # MPa
        logger.debug(f"Shear stress: {stress:.3f} MPa for force {shear_force:.2f} N")
        return stress

    def calculate_bending_stress(self, bending_moment: float) -> float:
        """
        Calculate bending stress.
        
        Formula: σ = M * c / I = M / S
        Where M = bending moment (N*m), c = distance from neutral axis (mm),
              I = moment of inertia (mm^4), S = section modulus (mm^3)
        
        Args:
            bending_moment: Applied bending moment in N*m
            
        Returns:
            Bending stress in MPa
        """
        if self.geometry.section_modulus <= 0:
            logger.warning("Section modulus is zero or negative")
            return 0.0
            
        # Convert bending moment from N*m to N*mm
        moment_nmm = bending_moment * 1000.0
        
        stress = moment_nmm / self.geometry.section_modulus  # MPa
        logger.debug(f"Bending stress: {stress:.3f} MPa for moment {bending_moment:.2f} N*m")
        return abs(stress)

    def calculate_torsional_stress(self, torque: float) -> float:
        """
        Calculate torsional shear stress.
        
        Formula: τ = T * r / J
        Where T = torque (N*m), r = radius (mm), J = polar moment of inertia (mm^4)
        
        Args:
            torque: Applied torque in N*m
            
        Returns:
            Torsional shear stress in MPa
        """
        if self.geometry.polar_moment_of_inertia <= 0:
            logger.warning("Polar moment of inertia is zero or negative")
            return 0.0
            
        # For circular sections, max shear stress occurs at outer radius
        # We'll approximate radius as sqrt(A/pi) for non-circular sections
        if self.geometry.cross_section_area > 0:
            equivalent_radius = math.sqrt(self.geometry.cross_section_area / math.pi)  # mm
        else:
            equivalent_radius = 0.0
            
        # Convert torque from N*m to N*mm
        torque_nmm = torque * 1000.0
        
        stress = torque_nmm * equivalent_radius / self.geometry.polar_moment_of_inertia  # MPa
        logger.debug(f"Torsional stress: {stress:.3f} MPa for torque {torque:.2f} N*m")
        return abs(stress)

    def calculate_von_mises_stress(
        self, 
        sigma_x: float,  # normal stress (axial + bending)
        tau_xy: float    # shear stress (transverse + torsional)
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

    def calculate_euler_buckling_load(self) -> float:
        """
        Calculate Euler critical buckling load for pinned-pinned column.
        
        Formula: Pcr = π^2 * E * I / (K * L)^2
        Where E = Young's modulus (MPa), I = moment of inertia (mm^4),
              L = length (mm), K = effective length factor
        
        Returns:
            Euler buckling load in N
        """
        if self.material.youngs_modulus <= 0 or self.geometry.moment_of_inertia <= 0:
            logger.warning("Young's modulus or moment of inertia is zero or negative")
            return 0.0
            
        if self.material.youngs_modulus <= 0 or self.geometry.moment_of_inertia <= 0:
            logger.warning("Young's modulus or moment of inertia is zero or negative")
            return 0.0
            
        if self.geometry.length <= 0:
            logger.warning("Length is zero or negative")
            return 0.0
            
        if self.material.youngs_modulus <= 0 or self.geometry.moment_of_inertia <= 0:
            logger.warning("Young's modulus or moment of inertia is zero or negative")
            return 0.0
            
        effective_length = self.geometry.effective_length_factor * self.geometry.length
        if effective_length <= 0:
            logger.warning("Effective length is zero or negative")
            return 0.0
            
        # Pcr = π² * E * I / Le²
        # E in MPa (N/mm²), I in mm⁴, Le in mm → Pcr in N
        pcr = (math.pi**2 * self.material.youngs_modulus * self.geometry.moment_of_inertia) / (effective_length**2)
        
        logger.debug(f"Euler buckling load: {pcr:.2f} N (E={self.material.youngs_modulus:.0f} MPa, I={self.geometry.moment_of_inertia:.2e} mm⁴, Le={effective_length:.2f} mm)")
        return pcr

    def calculate_deflection(
        self, 
        point_load: float = 0.0,      # N
        distributed_load: float = 0.0, # N/mm
        length: Optional[float] = None,
        case: str = "cantilever_end_point"
    ) -> float:
        """
        Calculate deflection under various loading conditions.
        
        Supported cases:
        - cantilever_end_point: point load at free end (δ = PL³/(3EI))
        - cantilever_uniform: uniform distributed load (δ = wL⁴/(8EI))
        - simply_supported_center_point: point load at center (δ = PL³/(48EI))
        - simply_supported_uniform: uniform distributed load (δ = 5wL⁴/(384EI))
        - fixed_fixed_center_point: point load at center (δ = PL³/(192EI))
        - fixed_fixed_uniform: uniform distributed load (δ = wL⁴/(384EI))
        
        Args:
            point_load: Point load in N
            distributed_load: Distributed load in N/mm
            length: Member length (mm) - if None, uses geometry.length
            case: Boundary condition and loading case
            
        Returns:
            Deflection in mm
        """
        if length is None:
            length = self.geometry.length
            
        if length <= 0:
            logger.warning("Length is zero or negative")
            return 0.0
            
        if self.material.youngs_modulus <= 0 or self.geometry.moment_of_inertia <= 0:
            logger.warning("Young's modulus or moment of inertia is zero or negative")
            return 0.0
            
        E = self.material.youngs_modulus  # MPa
        I = self.geometry.moment_of_inertia  # mm^4
        
        # Formulas give deflection in mm when using N, N/mm, mm, MPa
        
        if case == "cantilever_end_point":
            deflection = (point_load * length**3) / (3.0 * E * I)
        elif case == "cantilever_uniform":
            deflection = (distributed_load * length**4) / (8.0 * E * I)
        elif case == "simply_supported_center_point":
            deflection = (point_load * length**3) / (48.0 * E * I)
        elif case == "simply_supported_uniform":
            deflection = (5.0 * distributed_load * length**4) / (384.0 * E * I)
        elif case == "fixed_fixed_center_point":
            deflection = (point_load * length**3) / (192.0 * E * I)
        elif case == "fixed_fixed_uniform":
            deflection = (distributed_load * length**4) / (384.0 * E * I)
        else:
            logger.warning(f"Unknown deflection case: {case}. Using cantilever_end_point.")
            deflection = (point_load * length**3) / (3.0 * E * I)
            
        logger.debug(f"Deflection: {deflection:.4f} mm for case: {case}")
        return deflection

    def calculate_angle_of_twist(self, torque: float, length: Optional[float] = None) -> float:
        """
        Calculate angle of twist due to applied torque.
        
        Formula: φ = T * L / (G * J)
        Where T = torque (N*m), L = length (mm), G = shear modulus (MPa), 
              J = polar moment of inertia (mm^4)
        
        Args:
            torque: Applied torque in N*m
            length: Member length (mm) - if None, uses geometry.length
            
        Returns:
            Angle of twist in degrees
        """
        if length is None:
            length = self.geometry.length
            
        if length <= 0:
            logger.warning("Length is zero or negative")
            return 0.0
            
        if self.material.shear_modulus <= 0 or self.geometry.polar_moment_of_inertia <= 0:
            logger.warning("Shear modulus or polar moment of inertia is zero or negative")
            return 0.0
            
        G = self.material.shear_modulus  # MPa
        J = self.geometry.polar_moment_of_inertia  # mm^4
        
        # Convert torque from N*m to N*mm
        torque_nmm = torque * 1000.0
        
        # Angle in radians: T*L/(G*J)
        angle_rad = torque_nmm * length / (G * J)
        # Convert to degrees
        angle_deg = math.degrees(angle_rad)
        
        logger.debug(f"Angle of twist: {angle_deg:.4f} degrees for torque {torque:.2f} N*m")
        return angle_deg

    def analyze_frame_member(
        self, 
        loads: FrameLoads,
        length: Optional[float] = None
    ) -> FrameResults:
        """
        Perform complete frame member analysis.
        
        Args:
            loads: FrameLoads object containing applied forces and moments
            length: Member length (mm) - if None, uses geometry.length
            
        Returns:
            FrameResults object with stresses, deflections, and safety factors
        """
        logger.info("Starting frame member analysis")
        
        if length is None:
            length = self.geometry.length
            
        # Calculate thermal stress
        thermal_stress = self.calculate_thermal_stress(loads.temperature_change)
        
        # Calculate individual stress components
        sigma_axial = self.calculate_axial_stress(loads.axial_force)
        sigma_bending = self.calculate_bending_stress(loads.bending_moment)
        tau_shear = self.calculate_shear_stress(loads.shear_force)
        tau_torsion = self.calculate_torsional_stress(loads.torque)
        
        # For combined loading, we assume worst case occurs at same point
        # Normal stress from axial, bending, and thermal
        sigma_x = sigma_axial + sigma_bending + thermal_stress  # Could be more precise based on location
        
        # Shear stress from transverse force and torsion
        # For simplicity, we'll combine them (conservative)
        tau_xy = tau_shear + tau_torsion
        
        # Calculate von Mises stress
        von_mises = self.calculate_von_mises_stress(sigma_x, tau_xy)
        
        # Calculate deflection (simplified - assuming transverse load causes bending)
        # We'll consider both point load (shear force converted to equivalent point load) 
        # and distributed load
        equivalent_point_load = loads.shear_force  # Simplified
        deflection = self.calculate_deflection(
            point_load=equivalent_point_load,
            distributed_load=loads.distributed_load,
            length=length,
            case="cantilever_end_point"  # Simplified assumption
        )
        
        # Calculate angle of twist
        angle_of_twist = self.calculate_angle_of_twist(loads.torque, length)
        
        # Calculate buckling load
        buckling_load = self.calculate_euler_buckling_load()
        
        # Determine allowable stresses (using yield strength with factors)
        # In practice, these would come from design codes
        allowable_axial = self.material.yield_strength * 0.6  # 60% of yield
        allowable_bending = self.material.yield_strength * 0.6  # 60% of yield
        allowable_shear = self.material.yield_strength * 0.4  # 40% of yield (approx)
        allowable_combined = self.material.yield_strength * 0.5  # 50% of yield for combined
        
        # Calculate safety factors
        axial_sf = allowable_axial / abs(sigma_axial) if sigma_axial != 0 else float('inf')
        bending_sf = allowable_bending / abs(sigma_bending) if sigma_bending != 0 else float('inf')
        shear_sf = allowable_shear / abs(tau_shear) if tau_shear != 0 else float('inf')
        
        # Combined stress safety factor (using von Mises)
        combined_sf = allowable_combined / von_mises if von_mises != 0 else float('inf')
        
        # Buckling safety factor (only for compression)
        if loads.axial_force < 0:  # Compressive force
            buckling_sf = buckling_load / abs(loads.axial_force) if buckling_load > 0 else 0.0
        else:
            buckling_sf = float('inf')  # No buckling concern for tension
            
        # Determine if member passes
        passed = True
        notes = []
        failure_mode = None
        
        # Check axial stress
        if abs(sigma_axial) > allowable_axial:
            passed = False
            notes.append(f"Axial stress ({abs(sigma_axial):.1f} MPa) exceeds allowable ({allowable_axial:.1f} MPa)")
            if failure_mode is None:
                failure_mode = "axial_yield"
                
        # Check bending stress
        if abs(sigma_bending) > allowable_bending:
            passed = False
            notes.append(f"Bending stress ({abs(sigma_bending):.1f} MPa) exceeds allowable ({allowable_bending:.1f} MPa)")
            if failure_mode is None:
                failure_mode = "bending_yield"
                
        # Check shear stress
        if abs(tau_shear) > allowable_shear:
            passed = False
            notes.append(f"Shear stress ({abs(tau_shear):.1f} MPa) exceeds allowable ({allowable_shear:.1f} MPa)")
            if failure_mode is None:
                failure_mode = "shear_yield"
                
        # Check combined stress
        if von_mises > allowable_combined:
            passed = False
            notes.append(f"Von Mises stress ({von_mises:.1f} MPa) exceeds allowable ({allowable_combined:.1f} MPa)")
            if failure_mode is None:
                failure_mode = "combined_yield"
                
        # Check buckling
        if loads.axial_force < 0 and abs(loads.axial_force) > buckling_load:
            passed = False
            notes.append(f"Axial compressive force ({abs(loads.axial_force):.1f} N) exceeds buckling load ({buckling_load:.1f} N)")
            failure_mode = "buckling"
            
        # Check deflection (typical limit L/200 for beams)
        max_deflection = length / 200.0
        if deflection > max_deflection:
            passed = False
            notes.append(f"Deflection ({deflection:.3f} mm) exceeds L/200 limit ({max_deflection:.3f} mm)")
            if failure_mode is None:
                failure_mode = "excessive_deflection"
        
        # Add note if thermal effects were considered
        if loads.temperature_change != 0.0:
            notes.append(f"Thermal effects included (ΔT={loads.temperature_change:.1f} °C, thermal stress={thermal_stress:.1f} MPa)")
                
        results = FrameResults(
            axial_stress=sigma_axial,
            shear_stress=tau_shear,
            bending_stress=sigma_bending,
            torsional_stress=tau_torsion,
            von_mises_stress=von_mises,
            buckling_load=buckling_load,
            deflection=deflection,
            angle_of_twist=angle_of_twist,
            axial_safety_factor=axial_sf,
            bending_safety_factor=bending_sf,
            shear_safety_factor=shear_sf,
            combined_safety_factor=combined_sf,
            buckling_safety_factor=buckling_sf,
            passed=passed,
            notes=notes,
            failure_mode=failure_mode
        )
        
        logger.info(f"Frame analysis complete. Passed: {passed}, Min SF: {min(axial_sf, bending_sf, shear_sf, combined_sf, buckling_sf):.2f}")
        return results


# Convenience functions for direct use
def analyze_frame_member(
    length: float,
    cross_section_area: float,
    moment_of_inertia: float,
    section_modulus: float,
    youngs_modulus: float = 200e3,
    yield_strength: float = 250.0,
    ultimate_strength: float = 400.0,
    shear_modulus: float = 80e3,
    density: float = 7.85e-6,
    poisson_ratio: float = 0.3,
    effective_length_factor: float = 1.0,
    axial_force: float = 0.0,
    shear_force: float = 0.0,
    bending_moment: float = 0.0,
    torque: float = 0.0,
    distributed_load: float = 0.0,
    temperature_change: float = 0.0,
    thermal_expansion: float = 12.0e-6,
    reference_temperature: float = 20.0
) -> FrameResults:
    """
    Convenience function for simple frame member analysis.
    
    Args:
        length: Member length in mm
        cross_section_area: Cross-sectional area in mm^2
        moment_of_inertia: Moment of inertia in mm^4
        section_modulus: Section modulus in mm^3
        youngs_modulus: Young's modulus in MPa (default: steel)
        yield_strength: Yield strength in MPa (default: mild steel)
        ultimate_strength: Ultimate strength in MPa (default: mild steel)
        shear_modulus: Shear modulus in MPa (default: steel)
        density: Density in kg/mm^3 (default: steel)
        poisson_ratio: Poisson's ratio (default: 0.3)
        effective_length_factor: Effective length factor for buckling (default: 1.0 for pinned-pinned)
        axial_force: Applied axial force in N (positive = tension)
        shear_force: Applied shear force in N
        bending_moment: Applied bending moment in N*m
        torque: Applied torque in N*m
        distributed_load: Uniformly distributed load in N/mm
        temperature_change: Temperature change from reference in °C (default: 0.0)
        thermal_expansion: Coefficient of thermal expansion in 1/°C (default: 12.0e-6 for steel)
        reference_temperature: Reference temperature in °C (default: 20.0)
        
    Returns:
        FrameResults object
    """
    material = FrameMaterial(
        youngs_modulus=youngs_modulus,
        yield_strength=yield_strength,
        ultimate_strength=ultimate_strength,
        shear_modulus=shear_modulus,
        density=density,
        poisson_ratio=poisson_ratio
    )
    geometry = FrameGeometry(
        length=length,
        cross_section_area=cross_section_area,
        moment_of_inertia=moment_of_inertia,
        polar_moment_of_inertia=moment_of_inertia,  # Simplified - assumes circular section
        section_modulus=section_modulus,
        radius_of_gyration=math.sqrt(moment_of_inertia / cross_section_area) if cross_section_area > 0 else 0.0,
        effective_length_factor=effective_length_factor,
        thermal_expansion=thermal_expansion,
        reference_temperature=reference_temperature
    )
    loads = FrameLoads(
        axial_force=axial_force,
        shear_force=shear_force,
        bending_moment=bending_moment,
        torque=torque,
        distributed_load=distributed_load,
        temperature_change=temperature_change
    )
    
    analyzer = FrameAnalyzer(material, geometry)
    return analyzer.analyze_frame_member(loads)


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.DEBUG)
    
    print("=== Frame Analysis WITHOUT Thermal Effects ===")
    # Analyze a simple steel beam at reference temperature
    results_no_thermal = analyze_frame_member(
        length=1000.0,           # mm
        cross_section_area=500.0, # mm^2 (e.g., 20x25 mm rectangle)
        moment_of_inertia=50000.0, # mm^4
        section_modulus=2000.0,   # mm^3
        youngs_modulus=200e3,     # MPa
        yield_strength=250.0,     # MPa
        ultimate_strength=400.0,  # MPa
        shear_modulus=80e3,       # MPa
        density=7.85e-6,          # kg/mm^3
        axial_force=1000.0,       # N (tension)
        shear_force=500.0,        # N
        bending_moment=50.0,      # N*m
        torque=10.0,              # N*m
        distributed_load=2.0,     # N/mm
        temperature_change=0.0    # °C (no temperature change)
    )
    
    print(f"Frame Analysis Results:")
    print(f"  Axial Stress: {results_no_thermal.axial_stress:.2f} MPa")
    print(f"  Bending Stress: {results_no_thermal.bending_stress:.2f} MPa")
    print(f"  Shear Stress: {results_no_thermal.shear_stress:.2f} MPa")
    print(f"  Torsional Stress: {results_no_thermal.torsional_stress:.2f} MPa")
    print(f"  Von Mises Stress: {results_no_thermal.von_mises_stress:.2f} MPa")
    print(f"  Buckling Load: {results_no_thermal.buckling_load:.2f} N")
    print(f"  Deflection: {results_no_thermal.deflection:.3f} mm")
    print(f"  Angle of Twist: {results_no_thermal.angle_of_twist:.2f} degrees")
    print(f"  Axial Safety Factor: {results_no_thermal.axial_safety_factor:.2f}")
    print(f"  Bending Safety Factor: {results_no_thermal.bending_safety_factor:.2f}")
    print(f"  Shear Safety Factor: {results_no_thermal.shear_safety_factor:.2f}")
    print(f"  Combined Safety Factor: {results_no_thermal.combined_safety_factor:.2f}")
    print(f"  Buckling Safety Factor: {results_no_thermal.buckling_safety_factor:.2f}")
    print(f"  Passed: {results_no_thermal.passed}")
    if results_no_thermal.notes:
        print(f"  Notes: {', '.join(results_no_thermal.notes)}")
    if results_no_thermal.failure_mode:
        print(f"  Failure Mode: {results_no_thermal.failure_mode}")
    
    print("\n=== Frame Analysis WITH Thermal Effects (ΔT = 50°C) ===")
    # Analyze the same beam with a 50°C temperature increase
    results_with_thermal = analyze_frame_member(
        length=1000.0,           # mm
        cross_section_area=500.0, # mm^2 (e.g., 20x25 mm rectangle)
        moment_of_inertia=50000.0, # mm^4
        section_modulus=2000.0,   # mm^3
        youngs_modulus=200e3,     # MPa
        yield_strength=250.0,     # MPa
        ultimate_strength=400.0,  # MPa
        shear_modulus=80e3,       # MPa
        density=7.85e-6,          # kg/mm^3
        axial_force=1000.0,       # N (tension)
        shear_force=500.0,        # N
        bending_moment=50.0,      # N*m
        torque=10.0,              # N*m
        distributed_load=2.0,     # N/mm
        temperature_change=50.0   # °C (50°C temperature increase)
    )
    
    print(f"Frame Analysis Results:")
    print(f"  Axial Stress: {results_with_thermal.axial_stress:.2f} MPa")
    print(f"  Bending Stress: {results_with_thermal.bending_stress:.2f} MPa")
    print(f"  Shear Stress: {results_with_thermal.shear_stress:.2f} MPa")
    print(f"  Torsional Stress: {results_with_thermal.torsional_stress:.2f} MPa")
    print(f"  Von Mises Stress: {results_with_thermal.von_mises_stress:.2f} MPa")
    print(f"  Buckling Load: {results_with_thermal.buckling_load:.2f} N")
    print(f"  Deflection: {results_with_thermal.deflection:.3f} mm")
    print(f"  Angle of Twist: {results_with_thermal.angle_of_twist:.2f} degrees")
    print(f"  Axial Safety Factor: {results_with_thermal.axial_safety_factor:.2f}")
    print(f"  Bending Safety Factor: {results_with_thermal.bending_safety_factor:.2f}")
    print(f"  Shear Safety Factor: {results_with_thermal.shear_safety_factor:.2f}")
    print(f"  Combined Safety Factor: {results_with_thermal.combined_safety_factor:.2f}")
    print(f"  Buckling Safety Factor: {results_with_thermal.buckling_safety_factor:.2f}")
    print(f"  Passed: {results_with_thermal.passed}")
    if results_with_thermal.notes:
        print(f"  Notes: {', '.join(results_with_thermal.notes)}")
    if results_with_thermal.failure_mode:
        print(f"  Failure Mode: {results_with_thermal.failure_mode}")
    
    print("\n=== Comparison ===")
    stress_increase = results_with_thermal.axial_stress - results_no_thermal.axial_stress
    print(f"Thermal stress increase: {stress_increase:.2f} MPa")
    print(f"Axial stress change: {results_no_thermal.axial_stress:.2f} → {results_with_thermal.axial_stress:.2f} MPa")
    print(f"Von Mises stress change: {results_no_thermal.von_mises_stress:.2f} → {results_with_thermal.von_mises_stress:.2f} MPa")
    print(f"Safety factor change: {results_no_thermal.axial_safety_factor:.2f} → {results_with_thermal.axial_safety_factor:.2f}")
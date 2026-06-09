# app/physics/fatigue.py
# Fatigue analysis module for life prediction using S-N curves and Miner's rule

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("engine.physics.fatigue")


@dataclass
class FatigueMaterialProperties:
    """Material properties for fatigue analysis."""
    ultimate_tensile_strength: float  # MPa
    yield_strength: float  # MPa
    endurance_limit: float  # MPa (for steel, typically 0.5*UTS for < 1.4 GPa UTS)
    fatigue_strength_coefficient: float  # MPa (Basquin's sigma_f')
    fatigue_strength_exponent: float  # dimensionless (Basquin's b)
    fatigue_ductility_coefficient: float  # dimensionless (Coffin-Manson epsilon_f')
    fatigue_ductility_exponent: float  # dimensionless (Coffin-Manson c)
    # Thermal properties
    thermal_expansion: float = 12.0e-6  # 1/°C (default for steel)
    reference_temperature: float = 20.0  # °C
    # For simplicity, we'll focus on high-cycle fatigue (elastic strain dominant)


@dataclass
class FatigueLoading:
    """Loading conditions for fatigue analysis."""
    mean_stress: float = 0.0      # MPa
    alternating_stress: float = 0.0  # MPa
    stress_ratio: float = -1.0    # R = sigma_min / sigma_max
    num_cycles: int = 0           # Number of applied cycles at this stress level
    temperature_change: float = 0.0  # °C (change from reference temperature)
    # For variable amplitude loading, we'd have a list of these


@dataclass
class FatigueResults:
    """Results from fatigue analysis."""
    safety_factor: float = float('inf')  # Based on alternating stress vs allowable
    life_cycles: float = 0.0             # Estimated life to failure (cycles)
    life_hours: float = 0.0              # Life in hours (if frequency known)
    damage_fraction: float = 0.0         # Miner's rule damage fraction (D)
    passed: bool = True
    notes: List[str] = None
    failure_mode: Optional[str] = None
    equivalent_alternating_stress: float = 0.0  # MPa (after mean stress correction)

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


class FatigueAnalyzer:
    """Analyzes fatigue life using various criteria and models."""

    def __init__(self, material: FatigueMaterialProperties):
        self.material = material
        self._adjusted_sut: Optional[float] = None
        self._adjusted_sy: Optional[float] = None
        self._thermal_notes: List[str] = None
        logger.debug(f"Initialized FatigueAnalyzer with material properties")

    def calculate_temperature_adjusted_properties(self, temperature_change: float) -> Dict[str, float]:
        """
        Calculate temperature-adjusted material properties for fatigue analysis.

        High temperature reduces UTS, yield strength, and endurance limit.
        Also introduces thermal strain that adds to mechanical strain.

        Args:
            temperature_change: Temperature change from reference in °C

        Returns:
            Dictionary containing adjusted properties:
            - ultimate_tensile_strength: Adjusted UTS (MPa)
            - yield_strength: Adjusted yield strength (MPa)
            - temperature_factor: Marin temperature factor for endurance limit
            - thermal_strain: Thermal expansion strain (mm/mm)
        """
        if abs(temperature_change) < 0.5:
            return {
                "ultimate_tensile_strength": self.material.ultimate_tensile_strength,
                "yield_strength": self.material.yield_strength,
                "temperature_factor": 1.0,
                "thermal_strain": 0.0,
            }

        dt = temperature_change
        alpha = self.material.thermal_expansion
        temp_c = self.material.reference_temperature + dt

        # UTS derating: steel strength decreases at elevated temperature
        # Typical: ~10% loss at 200°C, ~20% at 300°C, ~50% at 500°C
        if temp_c > 100.0:
            uts_derating = 1.0 - 0.0005 * (temp_c - 100.0)
            uts_derating = max(uts_derating, 0.3)
        else:
            uts_derating = 1.0

        # Yield strength follows a similar trend
        if temp_c > 100.0:
            sy_derating = 1.0 - 0.0005 * (temp_c - 100.0)
            sy_derating = max(sy_derating, 0.3)
        else:
            sy_derating = 1.0

        # Marin temperature factor for endurance limit (kd in the Marin equation)
        # Per Shigley: kd = 1.0 for T <= 450°C, decreases above
        if temp_c <= 450.0:
            kd = 1.0
        elif temp_c <= 550.0:
            kd = 1.0 - 0.005 * (temp_c - 450.0)
        else:
            kd = 0.5

        # Thermal strain
        thermal_strain = alpha * dt

        adjusted_uts = self.material.ultimate_tensile_strength * uts_derating
        adjusted_sy = self.material.yield_strength * sy_derating

        self._adjusted_sut = adjusted_uts
        self._adjusted_sy = adjusted_sy

        uts_drop = self.material.ultimate_tensile_strength - adjusted_uts
        sy_drop = self.material.yield_strength - adjusted_sy
        logger.info(
            f"Temperature-adjusted fatigue properties (dT={temperature_change:+.1f}C): "
            f"UTS={adjusted_uts:.1f}MPa (-{uts_drop:.0f}MPa), "
            f"Sy={adjusted_sy:.1f}MPa (-{sy_drop:.0f}MPa), "
            f"kd={kd:.3f}, thermal_strain={thermal_strain:.2e}"
        )

        return {
            "ultimate_tensile_strength": adjusted_uts,
            "yield_strength": adjusted_sy,
            "temperature_factor": kd,
            "thermal_strain": thermal_strain,
        }

    def calculate_endurance_limit(self) -> float:
        """
        Calculate endurance limit for steels.
        
        For steels with UTS < 1.4 GPa: Se' = 0.5 * Sut
        For steels with UTS >= 1.4 GPa: Se' = 700 MPa
        
        Returns:
            Endurance limit in MPa
        """
        Sut = self.material.ultimate_tensile_strength
        if Sut < 1400.0:  # MPa
            Se_prime = 0.5 * Sut
        else:
            Se_prime = 700.0  # MPa
            
        logger.debug(f"Endurance limit (Se'): {Se_prime:.2f} MPa (based on Sut={Sut:.2f} MPa)")
        return Se_prime

    def calculate_modified_endurance_limit(
        self,
        load_factor: float = 1.0,
        size_factor: float = 1.0,
        surface_factor: float = 1.0,
        temperature_factor: float = 1.0,
        reliability_factor: float = 1.0,
        miscellaneous_factor: float = 1.0
    ) -> float:
        """
        Calculate modified endurance limit applying Marin factors.
        
        Formula: Se = ka * kb * kc * kd * ke * kf * Se'
        Where:
            ka = surface factor
            kb = size factor
            kc = load factor
            kd = temperature factor
            ke = reliability factor
            kf = miscellaneous effects factor
            Se' = endurance limit from rotating beam test
            
        Args:
            load_factor: Loading type factor (bending=1.0, axial=0.85, torsion=0.59)
            size_factor: Size effect factor
            surface_factor: Surface finish factor
            temperature_factor: Temperature factor
            reliability_factor: Reliability factor
            miscellaneous_factor: Miscellaneous effects factor
            
        Returns:
            Modified endurance limit in MPa
        """
        Se_prime = self.calculate_endurance_limit()
        Se = load_factor * size_factor * surface_factor * temperature_factor * reliability_factor * miscellaneous_factor * Se_prime
        
        logger.debug(f"Modified endurance limit (Se): {Se:.2f} MPa "
                    f"(ka={load_factor}, kb={size_factor}, kc={surface_factor}, kd={temperature_factor}, "
                    f"ke={reliability_factor}, kf={miscellaneous_factor}, Se'={Se_prime:.2f})")
        return Se

    def apply_mean_stress_correction(
        self,
        alternating_stress: float,
        mean_stress: float,
        method: str = "goodman"
    ) -> float:
        """
        Apply mean stress correction to alternating stress.
        
        Methods:
        - Goodman: sigma_a_eq = sigma_a / (1 - sigma_m / Sut)
        - Gerber: sigma_a_eq = sigma_a / (1 - (sigma_m / Sut)^2)
        - Soderberg: sigma_a_eq = sigma_a / (1 - sigma_m / Sy)
        - ASME Elliptic: sigma_a_eq = sigma_a / sqrt(1 - (sigma_m / Sut)^2)
        
        Args:
            alternating_stress: Alternating stress component (MPa)
            mean_stress: Mean stress component (MPa)
            method: Correction method ("goodman", "gerber", "soderberg", "elliptic")
            
        Returns:
            Equivalent alternating stress (MPa) with zero mean
        """
        Sut = self.material.ultimate_tensile_strength
        Sy = self.material.yield_strength
        
        if method == "goodman":
            if mean_stress >= Sut:
                logger.warning("Mean stress >= UTS in Goodman correction - infinite equivalent stress")
                return float('inf')
            sigma_a_eq = alternating_stress / (1.0 - mean_stress / Sut)
        elif method == "gerber":
            if abs(mean_stress) >= Sut:
                logger.warning("|Mean stress| >= UTS in Gerber correction - infinite equivalent stress")
                return float('inf')
            sigma_a_eq = alternating_stress / (1.0 - (mean_stress / Sut)**2)
        elif method == "soderberg":
            if mean_stress >= Sy:
                logger.warning("Mean stress >= Yield strength in Soderberg correction - infinite equivalent stress")
                return float('inf')
            sigma_a_eq = alternating_stress / (1.0 - mean_stress / Sy)
        elif method == "elliptic":
            if abs(mean_stress) >= Sut:
                logger.warning("|Mean stress| >= UTS in Elliptic correction - infinite equivalent stress")
                return float('inf')
            sigma_a_eq = alternating_stress / math.sqrt(1.0 - (mean_stress / Sut)**2)
        else:
            logger.warning(f"Unknown mean stress correction method: {method}. Using Goodman.")
            if mean_stress >= Sut:
                return float('inf')
            sigma_a_eq = alternating_stress / (1.0 - mean_stress / Sut)
            
        logger.debug(f"Mean stress correction ({method}): sigma_a={alternating_stress:.3f}, sigma_m={mean_stress:.3f} -> sigma_a_eq={sigma_a_eq:.3f} MPa")
        return sigma_a_eq

    def calculate_fatigue_life_basquin(
        self,
        alternating_stress: float,
        mean_stress: float = 0.0,
        method: str = "goodman"
    ) -> float:
        """
        Calculate fatigue life using Basquin's equation.
        
        Basquin's equation: sigma_a = sigma_f' * (2N)^b
        Where sigma_f' = fatigue strength coefficient, b = fatigue strength exponent
        Solving for N: N = 0.5 * (sigma_a / sigma_f')^(1/b)
        
        Args:
            alternating_stress: Alternating stress (MPa)
            mean_stress: Mean stress (MPa)
            method: Mean stress correction method
            
        Returns:
            Estimated life to failure in cycles
        """
        # Apply mean stress correction first
        sigma_a_eq = self.apply_mean_stress_correction(alternating_stress, mean_stress, method)
        
        if sigma_a_eq == float('inf'):
            return 0.0  # Zero life if mean stress too high
            
        sigma_f_prime = self.material.fatigue_strength_coefficient
        b = self.material.fatigue_strength_exponent
        
        if sigma_f_prime <= 0 or b >= 0:
            logger.warning("Invalid fatigue strength coefficient or exponent")
            return 0.0
            
        # Basquin's equation: sigma_a = sigma_f' * (2N)^b
        # Solving for N: N = 0.5 * (sigma_a / sigma_f')^(1/b)
        try:
            N = 0.5 * (sigma_a_eq / sigma_f_prime) ** (1.0 / b)
        except (ZeroDivisionError, OverflowError) as e:
            logger.warning(f"Error in Basquin's equation calculation: {e}")
            return 0.0
            
        logger.debug(f"Fatigue life (Basquin): {N:.2e} cycles "
                    f"(sigma_a_eq={sigma_a_eq:.3f} MPa, sigma_f'={sigma_f_prime:.3f} MPa, b={b:.4f})")
        return N

    def calculate_fatigue_life_endurance_limit(
        self,
        alternating_stress: float,
        mean_stress: float = 0.0,
        method: str = "goodman"
    ) -> float:
        """
        Calculate fatigue life using endurance limit approach.
        
        If corrected alternating stress < endurance limit -> infinite life
        Else -> estimate life based on S-N curve above endurance limit
        
        Args:
            alternating_stress: Alternating stress (MPa)
            mean_stress: Mean stress (MPa)
            method: Mean stress correction method
            
        Returns:
            Estimated life to failure in cycles (float('inf') for infinite life)
        """
        # Apply mean stress correction
        sigma_a_eq = self.apply_mean_stress_correction(alternating_stress, mean_stress, method)
        
        if sigma_a_eq == float('inf'):
            return 0.0  # Zero life
            
        # Get modified endurance limit (assuming default Marin factors for now)
        Se = self.calculate_modified_endurance_limit()
        
        if sigma_a_eq <= Se:
            logger.debug(f"Alternating stress ({sigma_a_eq:.3f} MPa) <= endurance limit ({Se:.3f} MPa) -> infinite life")
            return float('inf')
            
        # For stresses above endurance limit, we need the S-N curve
        # We'll use Basquin's equation as before but note it's only valid above Se
        # In practice, there's a knee in the curve at Se
        # For simplicity, we'll use Basquin but note this is approximate
        N = self.calculate_fatigue_life_basquin(sigma_a_eq, mean_stress, method)
        
        logger.debug(f"Fatigue life (Endurance limit method): {N:.2e} cycles "
                    f"(sigma_a_eq={sigma_a_eq:.3f} MPa, Se={Se:.3f} MPa)")
        return N

    def calculate_miners_damage(
        self,
        stress_blocks: List[Tuple[float, float, int]]  # (sigma_a, sigma_m, n_cycles) for each block
    ) -> float:
        """
        Calculate cumulative damage using Miner's rule.
        
        Formula: D = sum(n_i / N_i) for i = 1 to k
        Where n_i = cycles applied at stress level i, N_i = cycles to failure at stress level i
        
        Args:
            stress_blocks: List of tuples (alternating_stress, mean_stress, cycles_applied)
            
        Returns:
            Damage fraction D (D >= 1 indicates failure)
        """
        total_damage = 0.0
        details = []
        
        for i, (sigma_a, sigma_m, n_applied) in enumerate(stress_blocks):
            # Calculate life at this stress level
            N_i = self.calculate_fatigue_life_endurance_limit(sigma_a, sigma_m, method="goodman")
            
            if N_i == float('inf') or N_i == 0.0:
                # If infinite life, damage is zero; if zero life, damage is infinite
                damage_i = 0.0 if N_i == float('inf') else float('inf')
            else:
                damage_i = n_applied / N_i
                
            total_damage += damage_i
            details.append(f"Block {i+1}: sigma_a={sigma_a:.1f}, sigma_m={sigma_m:.1f}, n_applied={n_applied}, N_i={N_i:.2e}, damage={damage_i:.2e}")
            logger.debug(details[-1])
            
        logger.info(f"Miner's rule total damage: {total_damage:.2e}")
        for detail in details:
            logger.debug(detail)
            
        return total_damage

    def analyze_fatigue(
        self,
        loading: FatigueLoading,
        load_type: str = "bending",  # bending, axial, torsion
        size_factor: float = 1.0,
        surface_factor: float = 1.0,
        temperature_factor: float = 1.0,
        reliability_factor: float = 0.90,  # 90% reliability
        miscellaneous_factor: float = 1.0,
        frequency: float = 0.0  # Hz (for converting cycles to time)
    ) -> FatigueResults:
        """
        Perform complete fatigue analysis.
        
        Args:
            loading: FatigueLoading object with stress conditions
            load_type: Type of loading (affects load factor in Marin equation)
            size_factor: Size effect factor
            surface_factor: Surface finish factor
            temperature_factor: Temperature factor
            reliability_factor: Reliability factor (0.50-0.999)
            miscellaneous_factor: Miscellaneous effects factor
            frequency: Loading frequency in Hz (to convert cycles to hours)
            
        Returns:
            FatigueResults object with life, safety factor, and damage
        """
        logger.info("Starting fatigue analysis")
        self._thermal_notes = None

        # Apply thermal adjustment if temperature change is specified
        thermal_adj = None
        if abs(loading.temperature_change) >= 0.5:
            thermal_adj = self.calculate_temperature_adjusted_properties(loading.temperature_change)
            # Override temperature_factor with Marin kd if not manually set
            if temperature_factor == 1.0:
                temperature_factor = thermal_adj["temperature_factor"]
            self._thermal_notes = [
                f"Thermal effects applied: dT={loading.temperature_change:+.1f}C",
                f"Adjusted UTS: {thermal_adj['ultimate_tensile_strength']:.1f} MPa",
                f"Marin kd (temp): {thermal_adj['temperature_factor']:.3f}",
            ]

        # Determine load factor for Marin equation
        load_factor_map = {
            "bending": 1.0,
            "axial": 0.85,
            "torsion": 0.59
        }
        load_factor = load_factor_map.get(load_type.lower(), 1.0)
        
        # Calculate modified endurance limit
        Se = self.calculate_modified_endurance_limit(
            load_factor=load_factor,
            size_factor=size_factor,
            surface_factor=surface_factor,
            temperature_factor=temperature_factor,
            reliability_factor=reliability_factor,
            miscellaneous_factor=miscellaneous_factor
        )
        
        # Apply mean stress correction (using Goodman as default)
        sigma_a_eq = self.apply_mean_stress_correction(
            loading.alternating_stress,
            loading.mean_stress,
            method="goodman"
        )
        
        # Calculate safety factor based on alternating stress vs endurance limit
        if sigma_a_eq == float('inf'):
            safety_factor = 0.0
        elif Se == 0.0:
            safety_factor = float('inf') if sigma_a_eq == 0.0 else 0.0
        else:
            safety_factor = Se / sigma_a_eq if sigma_a_eq > 0 else float('inf')
        
        # Calculate fatigue life
        if sigma_a_eq == float('inf') or Se == 0.0:
            life_cycles = 0.0
        elif sigma_a_eq <= Se:
            life_cycles = float('inf')  # Infinite life
        else:
            # Use Basquin's equation for finite life prediction
            life_cycles = self.calculate_fatigue_life_basquin(
                sigma_a_eq,
                loading.mean_stress,
                method="goodman"
            )
        
        # Calculate life in hours if frequency provided
        if frequency > 0 and life_cycles != float('inf') and life_cycles > 0:
            life_hours = life_cycles / (frequency * 3600.0)  # cycles / (cycles/hour)
        elif life_cycles == float('inf'):
            life_hours = float('inf')
        else:
            life_hours = 0.0
            
        # Calculate damage fraction for the given number of cycles
        if loading.num_cycles > 0:
            if life_cycles == float('inf'):
                damage_fraction = 0.0
            elif life_cycles == 0.0:
                damage_fraction = float('inf')
            else:
                damage_fraction = loading.num_cycles / life_cycles
        else:
            damage_fraction = 0.0
            
        # Determine if component passes
        passed = True
        notes = []
        failure_mode = None
        
        # Check safety factor (typically > 1.0 for infinite life assessment)
        min_safety_factor = 1.0
        if safety_factor < min_safety_factor and sigma_a_eq > Se:
            passed = False
            notes.append(f"Safety factor ({safety_factor:.2f}) below minimum ({min_safety_factor})")
            if failure_mode is None:
                failure_mode = "fatigue_yield"
                
        # Check if life is insufficient (if design life specified)
        # For now, we'll consider infinite life as passing, finite life needs comparison to requirement
        # Since we don't have a design life requirement, we'll skip this check
        
        # Check damage fraction
        if damage_fraction >= 1.0:
            passed = False
            notes.append(f"Damage fraction ({damage_fraction:.2e}) >= 1.0 -> failure predicted")
            if failure_mode is None:
                failure_mode = "miners_rule"

        # Append thermal notes if applicable
        if self._thermal_notes:
            notes.extend(self._thermal_notes)
                
        results = FatigueResults(
            safety_factor=safety_factor,
            life_cycles=life_cycles,
            life_hours=life_hours,
            damage_fraction=damage_fraction,
            passed=passed,
            notes=notes,
            failure_mode=failure_mode,
            equivalent_alternating_stress=sigma_a_eq
        )
        
        logger.info(f"Fatigue analysis complete. Passed: {passed}, Safety factor: {safety_factor:.2f}, "
                   f"Life: {life_cycles if life_cycles != float('inf') else 'inf'} cycles")
        return results


# Convenience functions for direct use
def analyze_fatigue(
    ultimate_tensile_strength: float,
    yield_strength: float,
    alternating_stress: float,
    mean_stress: float = 0.0,
    num_cycles: int = 0,
    load_type: str = "bending",
    size_factor: float = 1.0,
    surface_factor: float = 1.0,
    temperature_factor: float = 1.0,
    reliability_factor: float = 0.90,
    miscellaneous_factor: float = 1.0,
    frequency: float = 0.0,
    fatigue_strength_coefficient: Optional[float] = None,
    fatigue_strength_exponent: Optional[float] = None,
    temperature_change: float = 0.0,
    thermal_expansion: float = 12.0e-6,
    reference_temperature: float = 20.0
) -> FatigueResults:
    """
    Convenience function for simple fatigue analysis.
    
    Args:
        ultimate_tensile_strength: UTS in MPa
        yield_strength: Yield strength in MPa
        alternating_stress: Alternating stress in MPa
        mean_stress: Mean stress in MPa
        num_cycles: Number of applied cycles
        load_type: Loading type ("bending", "axial", "torsion")
        size_factor: Size effect factor
        surface_factor: Surface finish factor
        temperature_factor: Temperature factor (overridden by thermal model if temperature_change set)
        reliability_factor: Reliability factor (0.50-0.999)
        miscellaneous_factor: Miscellaneous effects factor
        frequency: Loading frequency in Hz
        fatigue_strength_coefficient: Basquin's sigma_f' (MPa) - if None, estimated from UTS
        fatigue_strength_exponent: Basquin's b - if None, estimated
        temperature_change: Temperature change from reference in °C (0 = no thermal effects)
        thermal_expansion: Coefficient of thermal expansion in 1/°C
        reference_temperature: Reference temperature for zero thermal strain in °C
        
    Returns:
        FatigueResults object
    """
    # Estimate Basquin's parameters if not provided
    if fatigue_strength_coefficient is None:
        fatigue_strength_coefficient = ultimate_tensile_strength + 500.0
    if fatigue_strength_exponent is None:
        fatigue_strength_exponent = -0.09
        
    material = FatigueMaterialProperties(
        ultimate_tensile_strength=ultimate_tensile_strength,
        yield_strength=yield_strength,
        endurance_limit=0.0,
        fatigue_strength_coefficient=fatigue_strength_coefficient,
        fatigue_strength_exponent=fatigue_strength_exponent,
        fatigue_ductility_coefficient=0.0,
        fatigue_ductility_exponent=0.0,
        thermal_expansion=thermal_expansion,
        reference_temperature=reference_temperature
    )
    loading = FatigueLoading(
        mean_stress=mean_stress,
        alternating_stress=alternating_stress,
        num_cycles=num_cycles,
        temperature_change=temperature_change
    )
    
    analyzer = FatigueAnalyzer(material)
    return analyzer.analyze_fatigue(
        loading,
        load_type=load_type,
        size_factor=size_factor,
        surface_factor=surface_factor,
        temperature_factor=temperature_factor,
        reliability_factor=reliability_factor,
        miscellaneous_factor=miscellaneous_factor,
        frequency=frequency
    )


def analyze_variable_amplitude_fatigue(
    ultimate_tensile_strength: float,
    yield_strength: float,
    stress_blocks: List[Tuple[float, float, int]],  # (sigma_a, sigma_m, cycles)
    load_type: str = "bending",
    size_factor: float = 1.0,
    surface_factor: float = 1.0,
    temperature_factor: float = 1.0,
    reliability_factor: float = 0.90,
    miscellaneous_factor: float = 1.0,
    frequency: float = 0.0
) -> FatigueResults:
    """
    Analyze variable amplitude fatigue loading using Miner's rule.
    
    Args:
        ultimate_tensile_strength: UTS in MPa
        yield_strength: Yield strength in MPa
        stress_blocks: List of (alternating_stress, mean_stress, cycles_applied)
        load_type: Loading type
        size_factor: Size effect factor
        surface_factor: Surface finish factor
        temperature_factor: Temperature factor
        reliability_factor: Reliability factor
        miscellaneous_factor: Miscellaneous effects factor
        frequency: Loading frequency in Hz
        
    Returns:
        FatigueResults object with damage fraction
    """
    material = FatigueMaterialProperties(
        ultimate_tensile_strength=ultimate_tensile_strength,
        yield_strength=yield_strength,
        endurance_limit=0.0,
        fatigue_strength_coefficient=ultimate_tensile_strength + 500.0,  # Estimate
        fatigue_strength_exponent=-0.09,  # Typical value
        fatigue_ductility_coefficient=0.0,
        fatigue_ductility_exponent=0.0
    )
    
    analyzer = FatigueAnalyzer(material)
    
    # Calculate modified endurance limit (using first block's parameters for factors)
    Se = analyzer.calculate_modified_endurance_limit(
        load_factor={"bending": 1.0, "axial": 0.85, "torsion": 0.59}.get(load_type.lower(), 1.0),
        size_factor=size_factor,
        surface_factor=surface_factor,
        temperature_factor=temperature_factor,
        reliability_factor=reliability_factor,
        miscellaneous_factor=miscellaneous_factor
    )
    
    # Calculate total damage using Miner's rule
    damage_fraction = analyzer.calculate_miners_damage(stress_blocks)
    
    # Estimate equivalent constant amplitude life for reference
    # We'll use the first block to estimate life (simplified)
    if stress_blocks:
        first_block = stress_blocks[0]
        life_cycles = analyzer.calculate_fatigue_life_endurance_limit(
            first_block[0],  # sigma_a
            first_block[1],  # sigma_m
            method="goodman"
        )
    else:
        life_cycles = 0.0
        
    # Convert to hours if frequency provided
    if frequency > 0 and life_cycles != float('inf') and life_cycles > 0:
        life_hours = life_cycles / (frequency * 3600.0)
    elif life_cycles == float('inf'):
        life_hours = float('inf')
    else:
        life_hours = 0.0
        
    # Safety factor based on equivalent alternating stress vs endurance limit
    # We'll use a simplified approach: find the maximum alternating stress in blocks
    max_sigma_a = max([block[0] for block in stress_blocks]) if stress_blocks else 0.0
    # Assume zero mean stress for safety factor calculation (conservative)
    sigma_a_eq = analyzer.apply_mean_stress_correction(max_sigma_a, 0.0, method="goodman")
    safety_factor = Se / sigma_a_eq if sigma_a_eq > 0 else float('inf')
    
    passed = damage_fraction < 1.0
    notes = []
    failure_mode = None
    
    if damage_fraction >= 1.0:
        passed = False
        notes.append(f"Damage fraction ({damage_fraction:.2e}) >= 1.0 -> failure predicted by Miner's rule")
        failure_mode = "miners_rule"
        
    results = FatigueResults(
        safety_factor=safety_factor,
        life_cycles=life_cycles,
        life_hours=life_hours,
        damage_fraction=damage_fraction,
        passed=passed,
        notes=notes,
        failure_mode=failure_mode,
        equivalent_alternating_stress=sigma_a_eq
    )
    
    return results


@dataclass
class StressState:
    """Stress state for fatigue analysis."""
    sigma_a: float = 0.0      # Alternating stress (MPa)
    sigma_m: float = 0.0      # Mean stress (MPa)
    sigma_max: float = 0.0    # Maximum stress (MPa)
    sigma_min: float = 0.0    # Minimum stress (MPa)
    stress_amplitude: float = 0.0  # MPa (alternating stress)
    mean_stress: float = 0.0  # MPa (mean stress)
    
    def __post_init__(self):
        # Ensure consistency
        if self.sigma_a == 0.0 and self.stress_amplitude > 0.0:
            self.sigma_a = self.stress_amplitude
        if self.sigma_m == 0.0 and self.mean_stress > 0.0:
            self.sigma_m = self.mean_stress


@dataclass
class FatigueResult:
    """Results from fatigue analysis."""
    safety_factor: float = float('inf')  # Based on alternating stress vs allowable
    life_cycles: float = 0.0             # Estimated life to failure (cycles)
    life_hours: float = 0.0              # Life in hours (if frequency known)
    damage_fraction: float = 0.0         # Miner's rule damage fraction (D)
    passed: bool = True
    notes: list = None
    failure_mode: Optional[str] = None
    equivalent_alternating_stress: float = 0.0  # MPa (after mean stress correction)
    
    def __post_init__(self):
        if self.notes is None:
            self.notes = []


class FatigueAnalysis:
    """Main fatigue analysis interface for Digital Twin compatibility."""
    
    def __init__(self):
        """Initialize with default material properties (can be overridden in calculate_fatigue_life)."""
        # Default material properties (moderate strength steel)
        self.default_material = FatigueMaterialProperties(
            ultimate_tensile_strength=400.0,  # MPa
            yield_strength=250.0,             # MPa
            endurance_limit=0.0,              # Will be calculated
            fatigue_strength_coefficient=600.0,  # Estimated
            fatigue_strength_exponent=-0.09,   # Typical for steel
            fatigue_ductility_coefficient=0.0,
            fatigue_ductility_exponent=0.0
        )
        self.analyzer = FatigueAnalyzer(self.default_material)
        logger.debug("Initialized FatigueAnalysis wrapper")
    
    def calculate_fatigue_life(
        self,
        stress_state: StressState,
        sut: float,
        sy: float,
        cycles: float,
        frequency: float = 0.0,
        temperature_change: float = 0.0,
        thermal_expansion: float = 12.0e-6,
        reference_temperature: float = 20.0
    ) -> FatigueResult:
        """
        Calculate fatigue life for given stress state and material properties.
        
        Args:
            stress_state: StressState object with alternating and mean stress
            sut: Ultimate tensile strength (MPa)
            sy: Yield strength (MPa)
            cycles: Number of stress cycles applied
            frequency: Loading frequency (Hz) for converting to hours
            temperature_change: Temperature change from reference in °C
            thermal_expansion: Coefficient of thermal expansion in 1/°C
            reference_temperature: Reference temperature in °C
            
        Returns:
            FatigueResult object with life prediction and damage assessment
        """
        # Create material properties
        material = FatigueMaterialProperties(
            ultimate_tensile_strength=sut,
            yield_strength=sy,
            endurance_limit=0.0,
            fatigue_strength_coefficient=sut + 500.0,
            fatigue_strength_exponent=-0.09,
            fatigue_ductility_coefficient=0.0,
            fatigue_ductility_exponent=0.0,
            thermal_expansion=thermal_expansion,
            reference_temperature=reference_temperature
        )
        
        # Create analyzer with this material
        analyzer = FatigueAnalyzer(material)
        
        # Create loading condition
        loading = FatigueLoading(
            mean_stress=stress_state.sigma_m,
            alternating_stress=stress_state.sigma_a,
            num_cycles=int(cycles) if cycles > 0 else 1,
            temperature_change=temperature_change
        )
        
        # Perform analysis
        results = analyzer.analyze_fatigue(
            loading=loading,
            load_type="bending",
            size_factor=1.0,
            surface_factor=1.0,
            temperature_factor=1.0,
            reliability_factor=0.90,
            miscellaneous_factor=1.0,
            frequency=frequency
        )
        
        # Convert to FatigueResult format expected by digital twin
        return FatigueResult(
            safety_factor=results.safety_factor,
            life_cycles=results.life_cycles,
            life_hours=results.life_hours,
            damage_fraction=results.damage_fraction,
            passed=results.passed,
            notes=results.notes,
            failure_mode=results.failure_mode,
            equivalent_alternating_stress=results.equivalent_alternating_stress
        )


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("FATIGUE THERMAL EFFECTS DEMONSTRATION")
    print("=" * 60)
    
    common_fatigue = dict(
        ultimate_tensile_strength=600.0,
        yield_strength=400.0,
        alternating_stress=200.0,
        mean_stress=50.0,
        num_cycles=100000,
        load_type="bending",
        frequency=10.0
    )
    
    # Baseline (no thermal effects)
    print("\n--- Baseline (No Thermal Effects) ---")
    base = analyze_fatigue(**common_fatigue)
    print(f"  Safety Factor: {base.safety_factor:.2f}")
    print(f"  Life: {base.life_cycles if base.life_cycles != float('inf') else 'inf'} cycles")
    print(f"  Damage Fraction: {base.damage_fraction:.2e}")
    
    # Thermal case (+200°C)
    print("\n--- Thermal Case (+200°C) ---")
    hot = analyze_fatigue(**common_fatigue, temperature_change=200.0)
    print(f"  Safety Factor: {hot.safety_factor:.2f}")
    print(f"  Life: {hot.life_cycles if hot.life_cycles != float('inf') else 'inf'} cycles")
    print(f"  Damage Fraction: {hot.damage_fraction:.2e}")
    for note in hot.notes:
        print(f"  - {note}")
    
    # Extreme thermal case (+500°C to show kd derating)
    print("\n--- Extreme Thermal Case (+500°C, kd < 1) ---")
    extreme = analyze_fatigue(**common_fatigue, temperature_change=500.0)
    print(f"  Safety Factor: {extreme.safety_factor:.2f}")
    print(f"  Life: {extreme.life_cycles if extreme.life_cycles != float('inf') else 'inf'} cycles")
    print(f"  Damage Fraction: {extreme.damage_fraction:.2e}")
    for note in extreme.notes:
        print(f"  - {note}")
    
    # Comparison
    print("\n--- Thermal Impact Summary ---")
    if base.life_cycles != float('inf') and hot.life_cycles != float('inf') and hot.life_cycles > 0:
        life_change = ((hot.life_cycles - base.life_cycles) / base.life_cycles) * 100
        print(f"  Life Change (+200C): {life_change:+.1f}%")
    print(f"  Safety Factor Change (+200C): {hot.safety_factor - base.safety_factor:+.2f}")
    print(f"  Safety Factor Change (+500C): {extreme.safety_factor - base.safety_factor:+.2f}")
    
    print("\n" + "="*60 + "\n")
    
    # Standard single fatigue analysis (baseline)
    print("--- Standard Fatigue Analysis (Baseline) ---")
    results = analyze_fatigue(**common_fatigue)
    print(f"  Safety Factor: {results.safety_factor:.2f}")
    print(f"  Life: {results.life_cycles if results.life_cycles != float('inf') else 'inf'} cycles")
    print(f"  Life: {results.life_hours if results.life_hours != float('inf') else 'inf'} hours")
    print(f"  Damage Fraction: {results.damage_fraction:.2e}")
    print(f"  Equivalent Alternating Stress: {results.equivalent_alternating_stress:.2f} MPa")
    print(f"  Passed: {results.passed}")
    if results.notes:
        print(f"  Notes: {', '.join(results.notes)}")
    if results.failure_mode:
        print(f"  Failure Mode: {results.failure_mode}")
        
    print("\n" + "="*50 + "\n")
    
    # Variable amplitude fatigue analysis (Miner's rule)
    stress_blocks = [
        (180.0, 20.0, 50000),
        (120.0, 10.0, 100000),
        (80.0, 5.0, 200000)
    ]
    
    results_var = analyze_variable_amplitude_fatigue(
        ultimate_tensile_strength=600.0,
        yield_strength=400.0,
        stress_blocks=stress_blocks,
        load_type="bending",
        frequency=10.0
    )
    
    print(f"Fatigue Analysis Results (Variable Amplitude - Miner's Rule):")
    print(f"  Safety Factor: {results_var.safety_factor:.2f}")
    print(f"  Life (equiv): {results_var.life_cycles if results_var.life_cycles != float('inf') else 'inf'} cycles")
    print(f"  Life (equiv): {results_var.life_hours if results_var.life_hours != float('inf') else 'inf'} hours")
    print(f"  Damage Fraction: {results_var.damage_fraction:.2e}")
    print(f"  Equivalent Alternating Stress: {results_var.equivalent_alternating_stress:.2f} MPa")
    print(f"  Passed: {results_var.passed}")
    if results_var.notes:
        print(f"  Notes: {', '.join(results_var.notes)}")
    if results_var.failure_mode:
        print(f"  Failure Mode: {results_var.failure_mode}")
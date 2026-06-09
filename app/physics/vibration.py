# app/physics/vibration.py
# Vibration analysis module for modal analysis, forced vibration, and damping

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("engine.physics.vibration")


@dataclass
class VibrationSystem:
    """Properties of a vibrational system."""
    mass: float  # kg
    stiffness: float  # N/m
    damping_coefficient: float = 0.0  # N*s/m
    # Thermal properties
    thermal_expansion: float = 12.0e-6  # 1/deg C (default for steel)
    reference_temperature: float = 20.0  # deg C
    youngs_modulus: float = 200e9  # Pa (for stiffness derating)
    # For MDOF systems, we'd have matrices, but we'll start with SDOF


@dataclass
class VibrationLoading:
    """Loading conditions for vibration analysis."""
    force_amplitude: float = 0.0  # N
    force_frequency: float = 0.0  # Hz
    temperature_change: float = 0.0  # deg C (positive = heating)
    # Could also support base excitation, rotating imbalance, etc.


@dataclass
class VibrationResults:
    """Results from vibration analysis."""
    natural_frequency: float = 0.0  # Hz
    damped_natural_frequency: float = 0.0  # Hz
    damping_ratio: float = 0.0  # dimensionless
    critical_damping: float = 0.0  # N*s/m
    magnification_factor: float = 0.0  # dimensionless
    displacement_amplitude: float = 0.0  # m
    velocity_amplitude: float = 0.0  # m/s
    acceleration_amplitude: float = 0.0  # m/s^2
    phase_angle: float = 0.0  # degrees
    transmissibility: float = 0.0  # dimensionless (for base excitation)
    passed: bool = True
    notes: List[str] = None
    failure_mode: Optional[str] = None
    resonance: bool = False

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


class VibrationAnalyzer:
    """Analyzes vibrational systems for response to various excitations."""

    def __init__(self, system: VibrationSystem):
        self.system = system
        self._k_thermal = 1.0  # stiffness derating factor
        self._c_thermal = 1.0  # damping adjustment factor
        logger.debug(f"Initialized VibrationAnalyzer with system: {system}")

    def calculate_temperature_adjusted_properties(
        self, temperature_change: float = 0.0
    ) -> Dict[str, float]:
        """
        Calculate thermally-adjusted system properties.

        Thermal effects on vibration:
        1. Stiffness decreases as Young's modulus drops at high temperature.
           E(T) = E0 * (1 - alpha_E * delta_T) where alpha_E ~ 0.00036 / C for steel
           (typical modulus derating: ~0.036% per C for steel)
        2. Damping coefficient increases as lubricant viscosity changes.
           For thin oils, viscosity drops (less damping); for greases, may vary.
           Simplified model: damping scaled by 1/(1 + 0.002 * delta_T) above 100 C.
        3. Thermal expansion changes dimensions (affects mass distribution
           minimally for SDOF lumped-parameter model).

        Args:
            temperature_change: Temperature rise in deg C

        Returns:
            Dict with 'k_derating', 'c_derating', 'adjusted_stiffness', 'adjusted_damping'
        """
        if temperature_change == 0:
            self._k_thermal = 1.0
            self._c_thermal = 1.0
            return {
                "k_derating": 1.0,
                "c_derating": 1.0,
                "adjusted_stiffness": self.system.stiffness,
                "adjusted_damping": self.system.damping_coefficient,
            }

        # Young's modulus derating (typical 0.036% per C for steel)
        # E(T) = E0 * (1 - 0.00036 * delta_T)
        alpha_E = 0.00036  # 1/C for steel
        modulus_factor = 1.0 - alpha_E * temperature_change
        modulus_factor = max(modulus_factor, 0.5)  # cap at 50% reduction

        # Stiffness is proportional to E * I / L^3, so k scales with E
        k_derating = modulus_factor

        # Damping adjustment: lubricant viscosity changes with temperature.
        # Simplified model - above 100 C, damping decreases as oil thins.
        c_derating = 1.0
        current_temp = self.system.reference_temperature + temperature_change
        if current_temp > 100.0:
            # linear reduction: 0.5% per C above 100 C
            c_derating = 1.0 - 0.005 * (current_temp - 100.0)
            c_derating = max(c_derating, 0.2)  # cap at 80% reduction

        self._k_thermal = k_derating
        self._c_thermal = c_derating

        adjusted_stiffness = self.system.stiffness * k_derating
        adjusted_damping = self.system.damping_coefficient * c_derating

        logger.debug(
            f"Thermal adjustment: dT={temperature_change:.1f} C, "
            f"k_factor={k_derating:.4f}, c_factor={c_derating:.4f}, "
            f"k_adj={adjusted_stiffness:.2f} N/m, c_adj={adjusted_damping:.6f} N*s/m"
        )

        return {
            "k_derating": k_derating,
            "c_derating": c_derating,
            "adjusted_stiffness": adjusted_stiffness,
            "adjusted_damping": adjusted_damping,
        }

    def calculate_natural_frequency(self) -> float:
        """
        Calculate natural frequency of undamped system.
        
        Formula: omega _n = sqrt(k/m) [rad/s]
                 f_n = omega _n / (2pi ) [Hz]
        
        Returns:
            Natural frequency in Hz
        """
        if self.system.mass <= 0 or self.system.stiffness <= 0:
            logger.warning("Mass or stiffness is zero or negative")
            return 0.0
            
        omega_n = math.sqrt(self.system.stiffness / self.system.mass)  # rad/s
        f_n = omega_n / (2.0 * math.pi)  # Hz
        
        logger.debug(f"Natural frequency: {f_n:.4f} Hz (k={self.system.stiffness:.2f} N/m, m={self.system.mass:.4f} kg)")
        return f_n

    def calculate_damping_ratio(self) -> float:
        """
        Calculate damping ratio.
        
        Formula: zeta  = c / (2 * sqrt(m*k))
        
        Returns:
            Damping ratio (dimensionless)
        """
        if self.system.mass <= 0 or self.system.stiffness <= 0:
            logger.warning("Mass or stiffness is zero or negative")
            return 0.0
            
        critical_damping = 2.0 * math.sqrt(self.system.mass * self.system.stiffness)  # N*s/m
        if critical_damping == 0:
            logger.warning("Critical damping is zero")
            return 0.0
            
        zeta = self.system.damping_coefficient / critical_damping
        
        logger.debug(f"Damping ratio: {zeta:.4f} (c={self.system.damping_coefficient:.4f} N*s/m, c_crit={critical_damping:.4f} N*s/m)")
        return zeta

    def calculate_critical_damping(self) -> float:
        """
        Calculate critical damping coefficient.
        
        Formula: c_crit = 2 * sqrt(m*k)
        
        Returns:
            Critical damping coefficient in N*s/m
        """
        if self.system.mass <= 0 or self.system.stiffness <= 0:
            logger.warning("Mass or stiffness is zero or negative")
            return 0.0
            
        c_crit = 2.0 * math.sqrt(self.system.mass * self.system.stiffness)  # N*s/m
        logger.debug(f"Critical damping: {c_crit:.4f} N*s/m")
        return c_crit

    def calculate_damped_natural_frequency(self) -> float:
        """
        Calculate damped natural frequency.
        
        Formula: omega _d = omega _n * sqrt(1 - zeta ^2) [rad/s]
                 f_d = omega _d / (2pi ) [Hz]
        
        Returns:
            Damped natural frequency in Hz
        """
        omega_n = math.sqrt(self.system.stiffness / self.system.mass)  # rad/s
        zeta = self.calculate_damping_ratio()
        
        if zeta >= 1.0:
            logger.warning("Damping ratio >= 1 (overdamped or critically damped) - no oscillation")
            return 0.0
            
        omega_d = omega_n * math.sqrt(1.0 - zeta**2)  # rad/s
        f_d = omega_d / (2.0 * math.pi)  # Hz
        
        logger.debug(f"Damped natural frequency: {f_d:.4f} Hz (zeta ={zeta:.4f})")
        return f_d

    def calculate_magnification_factor(
        self,
        frequency_ratio: Optional[float] = None,
        forcing_frequency: Optional[float] = None
    ) -> float:
        """
        Calculate magnification factor for forced vibration.
        
        Formula: MF = 1 / sqrt((1 - r^2)^2 + (2zeta r)^2)
        Where r = omega /omega _n (frequency ratio)
        
        Args:
            frequency_ratio: Ratio of forcing frequency to natural frequency (omega /omega _n)
            forcing_frequency: Forcing frequency in Hz (if provided, will calculate ratio)
            
        Returns:
            Magnification factor (dimensionless)
        """
        if frequency_ratio is None and forcing_frequency is None:
            logger.warning("Either frequency_ratio or forcing_frequency must be provided")
            return 0.0
            
        if frequency_ratio is None:
            f_n = self.calculate_natural_frequency()
            if f_n == 0:
                logger.warning("Natural frequency is zero - cannot calculate frequency ratio")
                return 0.0
            frequency_ratio = forcing_frequency / f_n
            
        zeta = self.calculate_damping_ratio()
        
        # Magnification factor for viscous damping
        denominator = math.sqrt((1.0 - frequency_ratio**2)**2 + (2.0 * zeta * frequency_ratio)**2)
        
        if denominator == 0:
            logger.warning("Denominator zero in magnification factor calculation")
            return float('inf')
            
        MF = 1.0 / denominator
        
        logger.debug(f"Magnification factor: {MF:.4f} (r={frequency_ratio:.4f}, zeta ={zeta:.4f})")
        return MF

    def calculate_displacement_amplitude(
        self,
        force_amplitude: float,
        forcing_frequency: float
    ) -> float:
        """
        Calculate steady-state displacement amplitude due to harmonic force.
        
        Formula: X = (F0 / k) * MF
        Where F0 = force amplitude, k = stiffness, MF = magnification factor
        
        Args:
            force_amplitude: Force amplitude in N
            forcing_frequency: Forcing frequency in Hz
            
        Returns:
            Displacement amplitude in meters
        """
        if self.system.stiffness <= 0:
            logger.warning("Stiffness is zero or negative")
            return 0.0
            
        # Static deflection
        X_static = force_amplitude / self.system.stiffness  # m
        
        # Magnification factor
        MF = self.calculate_magnification_factor(forcing_frequency=forcing_frequency)
        
        # Displacement amplitude
        X = X_static * MF  # m
        
        logger.debug(f"Displacement amplitude: {X:.6f} m (F0={force_amplitude:.2f} N, k={self.system.stiffness:.2f} N/m, MF={MF:.4f})")
        return X

    def calculate_velocity_and_acceleration_amplitudes(
        self,
        displacement_amplitude: float,
        forcing_frequency: float
    ) -> Tuple[float, float]:
        """
        Calculate velocity and acceleration amplitudes from displacement.
        
        For harmonic motion: x = X * sin(omega t)
                            v = X * omega  * cos(omega t) -> V = X * omega 
                            a = -X * omega ^2 * sin(omega t) -> A = X * omega ^2
        
        Args:
            displacement_amplitude: Displacement amplitude in m
            forcing_frequency: Forcing frequency in Hz
            
        Returns:
            Tuple of (velocity_amplitude, acceleration_amplitude) in m/s and m/s^2
        """
        omega = forcing_frequency * 2.0 * math.pi  # rad/s
        
        velocity_amplitude = displacement_amplitude * omega  # m/s
        acceleration_amplitude = displacement_amplitude * omega**2  # m/s^2
        
        logger.debug(f"Velocity amplitude: {velocity_amplitude:.4f} m/s, Acceleration amplitude: {acceleration_amplitude:.4f} m/s^2")
        return velocity_amplitude, acceleration_amplitude

    def calculate_phase_angle(
        self,
        forcing_frequency: float
    ) -> float:
        """
        Calculate phase angle between force and displacement.
        
        Formula: phi  = atan2(2zeta r, 1 - r^2) [radians]
                 phi _deg = phi  * (180/pi ) [degrees]
        
        Args:
            forcing_frequency: Forcing frequency in Hz
            
        Returns:
            Phase angle in degrees (force leads displacement by this angle)
        """
        if self.system.stiffness <= 0 or self.system.mass <= 0:
            logger.warning("Stiffness or mass is zero or negative")
            return 0.0
            
        f_n = self.calculate_natural_frequency()
        if f_n == 0:
            logger.warning("Natural frequency is zero - cannot calculate phase angle")
            return 0.0
            
        r = forcing_frequency / f_n  # frequency ratio
        zeta = self.calculate_damping_ratio()
        
        # Phase angle in radians
        # phi  = atan2(2zeta r, 1 - r^2)
        phi_rad = math.atan2(2.0 * zeta * r, 1.0 - r**2)
        # Convert to degrees
        phi_deg = math.degrees(phi_rad)
        
        logger.debug(f"Phase angle: {phi_deg:.2f} degrees (r={r:.4f}, zeta ={zeta:.4f})")
        return phi_deg

    def calculate_transmissibility(
        self,
        forcing_frequency: float
    ) -> float:
        """
        Calculate transmissibility for base excitation.
        
        Formula: TR = sqrt(1 + (2zeta r)^2) / sqrt((1 - r^2)^2 + (2zeta r)^2)
        Where r = omega /omega _n
        
        Args:
            forcing_frequency: Forcing frequency in Hz
            
        Returns:
            Transmissibility (dimensionless)
        """
        if self.system.stiffness <= 0 or self.system.mass <= 0:
            logger.warning("Stiffness or mass is zero or negative")
            return 0.0
            
        f_n = self.calculate_natural_frequency()
        if f_n == 0:
            logger.warning("Natural frequency is zero - cannot calculate transmissibility")
            return 0.0
            
        r = forcing_frequency / f_n  # frequency ratio
        zeta = self.calculate_damping_ratio()
        
        numerator = math.sqrt(1.0 + (2.0 * zeta * r)**2)
        denominator = math.sqrt((1.0 - r**2)**2 + (2.0 * zeta * r)**2)
        
        if denominator == 0:
            logger.warning("Denominator zero in transmissibility calculation")
            return float('inf')
            
        TR = numerator / denominator
        
        logger.debug(f"Transmissibility: {TR:.4f} (r={r:.4f}, zeta ={zeta:.4f})")
        return TR

    def analyze_forced_vibration(
        self,
        loading: VibrationLoading
    ) -> VibrationResults:
        """
        Analyze system response to harmonic forcing.
        
        Args:
            loading: VibrationLoading object with force amplitude and frequency
            
        Returns:
            VibrationResults object with response characteristics
        """
        # Apply thermal adjustment if temperature_change is provided
        thermal_adj = self.calculate_temperature_adjusted_properties(
            loading.temperature_change
        )

        # Temporarily replace system properties with thermal-adjusted values
        _orig_stiffness = self.system.stiffness
        _orig_damping = self.system.damping_coefficient
        self.system.stiffness = thermal_adj["adjusted_stiffness"]
        self.system.damping_coefficient = thermal_adj["adjusted_damping"]

        logger.info(
            f"Starting forced vibration analysis"
            + (f" (dT={loading.temperature_change:.1f} C" if loading.temperature_change else "")
            + (f", k_adj={thermal_adj['adjusted_stiffness']:.1f} N/m" if thermal_adj['k_derating'] != 1.0 else "")
            + (")" if loading.temperature_change else "")
        )
        
        # Calculate basic system properties
        natural_frequency = self.calculate_natural_frequency()
        damping_ratio = self.calculate_damping_ratio()
        critical_damping = self.calculate_critical_damping()
        damped_natural_frequency = self.calculate_damped_natural_frequency()
        
        # Check for resonance
        resonance = False
        if natural_frequency > 0:
            # Consider resonance if forcing frequency within 5% of natural frequency
            if abs(loading.force_frequency - natural_frequency) / natural_frequency < 0.05:
                resonance = True
                
        # Calculate magnification factor
        magnification_factor = self.calculate_magnification_factor(
            forcing_frequency=loading.force_frequency
        )
        
        # Calculate displacement amplitude
        if loading.force_amplitude > 0 and self.system.stiffness > 0:
            displacement_amplitude = self.calculate_displacement_amplitude(
                loading.force_amplitude,
                loading.force_frequency
            )
        else:
            displacement_amplitude = 0.0
            
        # Calculate velocity and acceleration amplitudes
        velocity_amplitude, acceleration_amplitude = self.calculate_velocity_and_acceleration_amplitudes(
            displacement_amplitude,
            loading.force_frequency
        )
        
        # Calculate phase angle
        phase_angle = self.calculate_phase_angle(loading.force_frequency)
        
        # Calculate transmissibility (for base excitation)
        transmissibility = self.calculate_transmissibility(loading.force_frequency)
        
        # Determine if system passes (based on displacement limits)
        passed = True
        notes = []
        failure_mode = None
        
        # Check for excessive displacement
        max_allowed_displacement = 0.01  # m (10 mm - typical limit for precision machinery)
        if displacement_amplitude > max_allowed_displacement:
            passed = False
            notes.append(f"Displacement amplitude ({displacement_amplitude*1000:.2f} mm) exceeds limit ({max_allowed_displacement*1000:.2f} mm)")
            if failure_mode is None:
                failure_mode = "excessive_displacement"
                
        # Check for resonance condition
        if resonance:
            passed = False  # Resonance is often undesirable unless specifically designed for
            notes.append(f"Resonance condition: forcing frequency ({loading.force_frequency:.2f} Hz) ~ natural frequency ({natural_frequency:.2f} Hz)")
            if failure_mode is None:
                failure_mode = "resonance"
                
        # Check for excessive acceleration
        max_allowed_acceleration = 50.0  # m/s^2 (about 5g)
        if acceleration_amplitude > max_allowed_acceleration:
            passed = False
            notes.append(f"Acceleration amplitude ({acceleration_amplitude:.2f} m/s^2) exceeds limit ({max_allowed_acceleration:.2f} m/s^2)")
            if failure_mode is None:
                failure_mode = "excessive_acceleration"
                
        # Restore original system properties
        self.system.stiffness = _orig_stiffness
        self.system.damping_coefficient = _orig_damping

        # Add thermal note if temperature change applied
        if loading.temperature_change:
            notes.append(
                f"Thermal adjustment: dT={loading.temperature_change:.0f} C, "
                f"k_derating={thermal_adj['k_derating']:.3f}, "
                f"natural_freq_shift={natural_frequency:.3f} Hz (from {math.sqrt(_orig_stiffness / self.system.mass) / (2.0 * math.pi):.3f} Hz)"
            )

        results = VibrationResults(
            natural_frequency=natural_frequency,
            damped_natural_frequency=damped_natural_frequency,
            damping_ratio=damping_ratio,
            critical_damping=critical_damping,
            magnification_factor=magnification_factor,
            displacement_amplitude=displacement_amplitude,
            velocity_amplitude=velocity_amplitude,
            acceleration_amplitude=acceleration_amplitude,
            phase_angle=phase_angle,
            transmissibility=transmissibility,
            passed=passed,
            notes=notes,
            failure_mode=failure_mode,
            resonance=resonance
        )
        
        logger.info(f"Forced vibration analysis complete. Passed: {passed}, "
                   f"Displacement: {displacement_amplitude*1000:.3f} mm, MF: {magnification_factor:.3f}")
        return results


# Convenience functions for direct use
def analyze_vibration(
    mass: float,
    stiffness: float,
    damping_coefficient: float = 0.0,
    force_amplitude: float = 0.0,
    force_frequency: float = 0.0,
    temperature_change: float = 0.0
) -> VibrationResults:
    """
    Convenience function for simple vibration analysis.
    
    Args:
        mass: Mass in kg
        stiffness: Stiffness in N/m
        damping_coefficient: Damping coefficient in N*s/m
        force_amplitude: Force amplitude in N
        force_frequency: Forcing frequency in Hz
        temperature_change: Temperature rise in deg C
        
    Returns:
        VibrationResults object
    """
    system = VibrationSystem(
        mass=mass,
        stiffness=stiffness,
        damping_coefficient=damping_coefficient
    )
    loading = VibrationLoading(
        force_amplitude=force_amplitude,
        force_frequency=force_frequency,
        temperature_change=temperature_change
    )
    
    analyzer = VibrationAnalyzer(system)
    return analyzer.analyze_forced_vibration(loading)


def analyze_base_excitation(
    mass: float,
    stiffness: float,
    damping_coefficient: float = 0.0,
    base_acceleration_amplitude: float = 0.0,
    base_frequency: float = 0.0,
    temperature_change: float = 0.0
) -> VibrationResults:
    """
    Analyze vibration due to base excitation (simplified).
    
    Args:
        mass: Mass in kg
        stiffness: Stiffness in N/m
        damping_coefficient: Damping coefficient in N*s/m
        base_acceleration_amplitude: Base acceleration amplitude in m/s^2
        base_frequency: Base frequency in Hz
        temperature_change: Temperature rise in deg C
        
    Returns:
        VibrationResults object
    """
    # For base excitation, we can convert to equivalent force
    # F_eq = m * a_base
    force_amplitude = mass * base_acceleration_amplitude
    
    system = VibrationSystem(
        mass=mass,
        stiffness=stiffness,
        damping_coefficient=damping_coefficient
    )
    loading = VibrationLoading(
        force_amplitude=force_amplitude,
        force_frequency=base_frequency,
        temperature_change=temperature_change
    )
    
    analyzer = VibrationAnalyzer(system)
    results = analyzer.analyze_forced_vibration(loading)
    
    # For base excitation, transmissibility is more relevant than displacement
    # We'll keep the results as is but note the interpretation
    return results


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.DEBUG)
    
    print("=" * 60)
    print("Vibration Analysis - Baseline (room temperature)")
    print("=" * 60)
    # Analyze a simple mass-spring-damper system at room temperature
    results = analyze_vibration(
        mass=10.0,           # kg
        stiffness=10000.0,   # N/m
        damping_coefficient=50.0,  # N*s/m
        force_amplitude=100.0,     # N
        force_frequency=5.0        # Hz
    )
    
    print(f"Vibration Analysis Results:")
    print(f"  Natural Frequency: {results.natural_frequency:.4f} Hz")
    print(f"  Damped Natural Frequency: {results.damped_natural_frequency:.4f} Hz")
    print(f"  Damping Ratio: {results.damping_ratio:.4f}")
    print(f"  Critical Damping: {results.critical_damping:.4f} N*s/m")
    print(f"  Magnification Factor: {results.magnification_factor:.4f}")
    print(f"  Displacement Amplitude: {results.displacement_amplitude*1000:.4f} mm")
    print(f"  Velocity Amplitude: {results.velocity_amplitude:.4f} m/s")
    print(f"  Acceleration Amplitude: {results.acceleration_amplitude:.4f} m/s^2")
    print(f"  Phase Angle: {results.phase_angle:.2f} degrees")
    print(f"  Transmissibility: {results.transmissibility:.4f}")
    print(f"  Resonance: {results.resonance}")
    print(f"  Passed: {results.passed}")
    if results.notes:
        print(f"  Notes: {', '.join(results.notes)}")
    if results.failure_mode:
        print(f"  Failure Mode: {results.failure_mode}")
        
    print("\n" + "=" * 60)
    print("Vibration Analysis - Elevated Temperature (+300 C)")
    print("=" * 60)
    # Same system with +300 C temperature rise
    results_hot = analyze_vibration(
        mass=10.0,           # kg
        stiffness=10000.0,   # N/m
        damping_coefficient=50.0,  # N*s/m
        force_amplitude=100.0,     # N
        force_frequency=5.0,        # Hz
        temperature_change=300.0    # C
    )
    
    print(f"Vibration Analysis Results (dT=+300 C):")
    print(f"  Natural Frequency: {results_hot.natural_frequency:.4f} Hz")
    print(f"  Damped Natural Frequency: {results_hot.damped_natural_frequency:.4f} Hz")
    print(f"  Damping Ratio: {results_hot.damping_ratio:.4f}")
    print(f"  Critical Damping: {results_hot.critical_damping:.4f} N*s/m")
    print(f"  Magnification Factor: {results_hot.magnification_factor:.4f}")
    print(f"  Displacement Amplitude: {results_hot.displacement_amplitude*1000:.4f} mm")
    print(f"  Velocity Amplitude: {results_hot.velocity_amplitude:.4f} m/s")
    print(f"  Acceleration Amplitude: {results_hot.acceleration_amplitude:.4f} m/s^2")
    print(f"  Phase Angle: {results_hot.phase_angle:.2f} degrees")
    print(f"  Transmissibility: {results_hot.transmissibility:.4f}")
    print(f"  Resonance: {results_hot.resonance}")
    print(f"  Passed: {results_hot.passed}")
    if results_hot.notes:
        print(f"  Notes: {', '.join(results_hot.notes)}")
    if results_hot.failure_mode:
        print(f"  Failure Mode: {results_hot.failure_mode}")
    
    # Compare natural frequencies
    baseline_fn = results.natural_frequency
    hot_fn = results_hot.natural_frequency
    if baseline_fn > 0:
        shift_pct = (hot_fn - baseline_fn) / baseline_fn * 100
        print(f"\n  Natural frequency shift: {shift_pct:.2f}%")
        
    print("\n" + "="*60)
    print("Base Excitation - Room Temperature")
    print("="*60)
    # Example: Base excitation (e.g., earthquake or machine base vibration)
    results_base = analyze_base_excitation(
        mass=5.0,              # kg
        stiffness=50000.0,     # N/m (stiff mounting)
        damping_coefficient=20.0, # N*s/m
        base_acceleration_amplitude=2.0,  # m/s^2 (about 0.2g)
        base_frequency=10.0    # Hz
    )
    
    print(f"Base Excitation Vibration Analysis Results:")
    print(f"  Natural Frequency: {results_base.natural_frequency:.4f} Hz")
    print(f"  Damping Ratio: {results_base.damping_ratio:.4f}")
    print(f"  Transmissibility: {results_base.transmissibility:.4f}")
    print(f"  Passed: {results_base.passed}")
    if results_base.notes:
        print(f"  Notes: {', '.join(results_base.notes)}")
    if results_base.failure_mode:
        print(f"  Failure Mode: {results_base.failure_mode}")
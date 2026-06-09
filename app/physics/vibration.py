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
    # For MDOF systems, we'd have matrices, but we'll start with SDOF


@dataclass
class VibrationLoading:
    """Loading conditions for vibration analysis."""
    force_amplitude: float = 0.0  # N
    force_frequency: float = 0.0  # Hz
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
        logger.debug(f"Initialized VibrationAnalyzer with system: {system}")

    def calculate_natural_frequency(self) -> float:
        """
        Calculate natural frequency of undamped system.
        
        Formula: ω_n = sqrt(k/m) [rad/s]
                 f_n = ω_n / (2π) [Hz]
        
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
        
        Formula: ζ = c / (2 * sqrt(m*k))
        
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
        
        Formula: ω_d = ω_n * sqrt(1 - ζ^2) [rad/s]
                 f_d = ω_d / (2π) [Hz]
        
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
        
        logger.debug(f"Damped natural frequency: {f_d:.4f} Hz (ζ={zeta:.4f})")
        return f_d

    def calculate_magnification_factor(
        self,
        frequency_ratio: Optional[float] = None,
        forcing_frequency: Optional[float] = None
    ) -> float:
        """
        Calculate magnification factor for forced vibration.
        
        Formula: MF = 1 / sqrt((1 - r^2)^2 + (2ζr)^2)
        Where r = ω/ω_n (frequency ratio)
        
        Args:
            frequency_ratio: Ratio of forcing frequency to natural frequency (ω/ω_n)
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
        
        logger.debug(f"Magnification factor: {MF:.4f} (r={frequency_ratio:.4f}, ζ={zeta:.4f})")
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
        
        For harmonic motion: x = X * sin(ωt)
                            v = X * ω * cos(ωt) -> V = X * ω
                            a = -X * ω^2 * sin(ωt) -> A = X * ω^2
        
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
        
        Formula: φ = atan2(2ζr, 1 - r^2) [radians]
                 φ_deg = φ * (180/π) [degrees]
        
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
        # φ = atan2(2ζr, 1 - r^2)
        phi_rad = math.atan2(2.0 * zeta * r, 1.0 - r**2)
        # Convert to degrees
        phi_deg = math.degrees(phi_rad)
        
        logger.debug(f"Phase angle: {phi_deg:.2f} degrees (r={r:.4f}, ζ={zeta:.4f})")
        return phi_deg

    def calculate_transmissibility(
        self,
        forcing_frequency: float
    ) -> float:
        """
        Calculate transmissibility for base excitation.
        
        Formula: TR = sqrt(1 + (2ζr)^2) / sqrt((1 - r^2)^2 + (2ζr)^2)
        Where r = ω/ω_n
        
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
        
        logger.debug(f"Transmissibility: {TR:.4f} (r={r:.4f}, ζ={zeta:.4f})")
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
        logger.info("Starting forced vibration analysis")
        
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
            notes.append(f"Resonance condition: forcing frequency ({loading.force_frequency:.2f} Hz) ≈ natural frequency ({natural_frequency:.2f} Hz)")
            if failure_mode is None:
                failure_mode = "resonance"
                
        # Check for excessive acceleration
        max_allowed_acceleration = 50.0  # m/s^2 (about 5g)
        if acceleration_amplitude > max_allowed_acceleration:
            passed = False
            notes.append(f"Acceleration amplitude ({acceleration_amplitude:.2f} m/s^2) exceeds limit ({max_allowed_acceleration:.2f} m/s^2)")
            if failure_mode is None:
                failure_mode = "excessive_acceleration"
                
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
    force_frequency: float = 0.0
) -> VibrationResults:
    """
    Convenience function for simple vibration analysis.
    
    Args:
        mass: Mass in kg
        stiffness: Stiffness in N/m
        damping_coefficient: Damping coefficient in N*s/m
        force_amplitude: Force amplitude in N
        force_frequency: Forcing frequency in Hz
        
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
        force_frequency=force_frequency
    )
    
    analyzer = VibrationAnalyzer(system)
    return analyzer.analyze_forced_vibration(loading)


def analyze_base_excitation(
    mass: float,
    stiffness: float,
    damping_coefficient: float = 0.0,
    base_acceleration_amplitude: float = 0.0,
    base_frequency: float = 0.0
) -> VibrationResults:
    """
    Analyze vibration due to base excitation (simplified).
    
    Args:
        mass: Mass in kg
        stiffness: Stiffness in N/m
        damping_coefficient: Damping coefficient in N*s/m
        base_acceleration_amplitude: Base acceleration amplitude in m/s^2
        base_frequency: Base frequency in Hz
        
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
        force_frequency=base_frequency
    )
    
    analyzer = VibrationAnalyzer(system)
    results = analyzer.analyze_forced_vibration(loading)
    
    # For base excitation, transmissibility is more relevant than displacement
    # We'll keep the results as is but note the interpretation
    return results


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.DEBUG)
    
    # Analyze a simple mass-spring-damper system
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
        
    print("\n" + "="*50 + "\n")
    
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
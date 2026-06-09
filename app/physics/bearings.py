# app/physics/bearings.py
# Bearing analysis module for load calculations, life expectancy, and friction

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("engine.physics.bearings")


@dataclass
class BearingGeometry:
    """Bearing geometric properties."""
    bearing_type: str  # e.g., "ball", "roller", "tapered_roller"
    bore_diameter: float  # mm
    outer_diameter: float  # mm
    width: float  # mm
    dynamic_load_rating: float  # N (C - basic dynamic load rating)
    static_load_rating: float   # N (Co - basic static load rating)
    limiting_speed: float  # rpm (maximum operational speed)
    # Thermal properties
    thermal_expansion: float = 12.0e-6  # 1/°C (default for steel)
    reference_temperature: float = 20.0  # °C


@dataclass
class BearingLoads:
    """Loads applied to the bearing."""
    radial_load: float = 0.0      # N (radial direction)
    axial_load: float = 0.0       # N (axial direction)
    moment_load: float = 0.0      # N*mm (tilting moment)
    speed: float = 0.0            # rpm (rotational speed)
    temperature_change: float = 0.0  # °C (change from reference temperature)


@dataclass
class BearingResults:
    """Results from bearing analysis."""
    equivalent_dynamic_load: float = 0.0  # N (P)
    equivalent_static_load: float = 0.0   # N (Po)
    fatigue_life_hours: float = 0.0       # L10 life in hours
    fatigue_life_revolutions: float = 0.0 # L10 life in revolutions
    static_safety_factor: float = float('inf') # Co/Po
    hydrodynamic_lubrication: bool = False
    operating_temperature: float = 40.0   # °C (ambient + rise)
    friction_torque: float = 0.0          # N*mm
    power_loss: float = 0.0               # Watts
    passed: bool = True
    notes: List[str] = None
    failure_mode: Optional[str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


class BearingAnalyzer:
    """Analyzes bearing load capacity, life, and friction."""

    def __init__(self, geometry: BearingGeometry):
        self.geometry = geometry
        self._adjusted_dynamic_rating: Optional[float] = None
        self._adjusted_static_rating: Optional[float] = None
        self._adjusted_bore: Optional[float] = None
        self._adjusted_outer: Optional[float] = None
        self._adjusted_width: Optional[float] = None
        self._thermal_notes: List[str] = None
        logger.debug(f"Initialized BearingAnalyzer for {geometry.bearing_type} bearing")

    def calculate_temperature_adjusted_properties(self, temperature_change: float) -> Dict[str, float]:
        """
        Calculate temperature-adjusted dimensions and load ratings.

        Thermal expansion affects bearing geometry (clearances, fits) and
        material properties (hardness, lubricant viscosity), which in turn
        affect dynamic/static load ratings.

        Args:
            temperature_change: Temperature change from reference in °C

        Returns:
            Dictionary containing adjusted properties:
            - bore_diameter: Adjusted bore diameter (mm)
            - outer_diameter: Adjusted outer diameter (mm)
            - width: Adjusted width (mm)
            - dynamic_load_rating: Temperature-derated dynamic load rating (N)
            - static_load_rating: Temperature-derated static load rating (N)
        """
        if abs(temperature_change) < 0.5:
            return {
                "bore_diameter": self.geometry.bore_diameter,
                "outer_diameter": self.geometry.outer_diameter,
                "width": self.geometry.width,
                "dynamic_load_rating": self.geometry.dynamic_load_rating,
                "static_load_rating": self.geometry.static_load_rating,
            }

        alpha = self.geometry.thermal_expansion
        dt = temperature_change

        # Dimensional changes from thermal expansion
        bore_adj = self.geometry.bore_diameter * (1.0 + alpha * dt)
        outer_adj = self.geometry.outer_diameter * (1.0 + alpha * dt)
        width_adj = self.geometry.width * (1.0 + alpha * dt)

        # Load rating derating: bearing steel hardness decreases at high temp
        # ISO 281 recommends derating above ~120°C
        temp_c = self.geometry.reference_temperature + temperature_change
        if temp_c > 120.0:
            derating = 1.0 - 0.0006 * (temp_c - 120.0)
            derating = max(derating, 0.5)
        else:
            derating = 1.0

        dynamic_adj = self.geometry.dynamic_load_rating * derating
        static_adj = self.geometry.static_load_rating * derating

        self._adjusted_dynamic_rating = dynamic_adj
        self._adjusted_static_rating = static_adj
        self._adjusted_bore = bore_adj
        self._adjusted_outer = outer_adj
        self._adjusted_width = width_adj

        dyn_drop = self.geometry.dynamic_load_rating - dynamic_adj
        stat_drop = self.geometry.static_load_rating - static_adj
        logger.info(
            f"Temperature-adjusted bearing properties (dT={temperature_change:+.1f}C): "
            f"bore={bore_adj:.3f}mm, outer={outer_adj:.3f}mm, "
            f"dynamic={dynamic_adj:.1f}N (-{dyn_drop:.0f}N), "
            f"static={static_adj:.1f}N (-{stat_drop:.0f}N)"
        )

        return {
            "bore_diameter": bore_adj,
            "outer_diameter": outer_adj,
            "width": width_adj,
            "dynamic_load_rating": dynamic_adj,
            "static_load_rating": static_adj,
        }

    def calculate_equivalent_dynamic_load(
        self, 
        radial_load: float, 
        axial_load: float,
        radial_factor: float = 1.0,
        axial_factor: float = 0.0,
        spin_factor: float = 1.0
    ) -> float:
        """
        Calculate equivalent dynamic load for bearing life calculation.
        
        Formula: P = X*Fr + Y*Fa
        Where X = radial factor, Y = axial factor (depends on bearing type and Fa/Fr ratio)
        
        For simplicity, we'll use simplified factors. In practice, these come from 
        bearing manufacturer catalogs based on specific bearing geometry.
        
        Args:
            radial_load: Applied radial load in N
            axial_load: Applied axial load in N
            radial_factor: Radial load factor (X)
            axial_factor: Axial load factor (Y)
            spin_factor: Centrifugal force factor (for high speeds)
            
        Returns:
            Equivalent dynamic load in N
        """
        # Apply spin factor to radial load (simplified)
        Fr_eff = radial_load * spin_factor
        
        # Equivalent load
        P = radial_factor * Fr_eff + axial_factor * axial_load
        
        logger.debug(f"Equivalent dynamic load: {P:.2f} N (Fr={radial_load:.2f}, Fa={axial_load:.2f}, X={radial_factor}, Y={axial_factor})")
        return max(P, 0.0)  # Load cannot be negative

    def calculate_equivalent_static_load(
        self, 
        radial_load: float, 
        axial_load: float,
        radial_factor: float = 0.6,
        axial_factor: float = 0.5
    ) -> float:
        """
        Calculate equivalent static load for static load checking.
        
        Formula: Po = Xo*Fr + Yo*Fa
        Where Xo and Yo are static load factors (typically 0.6 and 0.5 for radial bearings)
        
        Args:
            radial_load: Applied radial load in N
            axial_load: Applied axial load in N
            radial_factor: Static radial load factor (Xo)
            axial_factor: Static axial load factor (Yo)
            
        Returns:
            Equivalent static load in N
        """
        Po = radial_factor * radial_load + axial_factor * axial_load
        logger.debug(f"Equivalent static load: {Po:.2f} N (Fr={radial_load:.2f}, Fa={axial_load:.2f}, Xo={radial_factor}, Yo={axial_factor})")
        return max(Po, 0.0)

    def calculate_fatigue_life(
        self, 
        equivalent_dynamic_load: float,
        dynamic_load_rating: Optional[float] = None,
        life_exponent: float = 3.0  # 3 for ball bearings, 10/3 for roller bearings
    ) -> Tuple[float, float]:
        """
        Calculate bearing fatigue life (L10 life).
        
        Formula: L10 = (C/P)^p * 10^6 revolutions
        Where C = dynamic load rating, P = equivalent dynamic load, p = life exponent
        Life in hours: L10h = L10 / (60 * n) where n = speed in rpm
        
        Args:
            equivalent_dynamic_load: Equivalent dynamic load (P) in N
            dynamic_load_rating: Basic dynamic load rating (C) in N - if None, uses geometry.dynamic_load_rating
            life_exponent: Exponent for life calculation (3 for ball, 10/3 for roller)
            
        Returns:
            Tuple of (life_hours, life_revolutions)
        """
        if dynamic_load_rating is None:
            dynamic_load_rating = self.geometry.dynamic_load_rating
            
        if equivalent_dynamic_load <= 0:
            logger.warning("Equivalent dynamic load is zero or negative - infinite life")
            return float('inf'), float('inf')
            
        if dynamic_load_rating <= 0:
            logger.warning("Dynamic load rating is zero or negative - zero life")
            return 0.0, 0.0
            
        # Calculate life in revolutions
        life_revolutions = ((dynamic_load_rating / equivalent_dynamic_load) ** life_exponent) * 1e6
        
        # Calculate life in hours
        if self.geometry.limiting_speed > 0:
            life_hours = life_revolutions / (60.0 * self.geometry.limiting_speed)
        else:
            # If speed not provided, cannot calculate hours
            life_hours = 0.0
            
        logger.debug(f"Bearing life: {life_revolutions:.2e} revolutions ({life_hours:.2f} hours) "
                    f"for C={dynamic_load_rating:.2f} N, P={equivalent_dynamic_load:.2f} N, p={life_exponent}")
        return life_hours, life_revolutions

    def calculate_static_safety_factor(
        self, 
        equivalent_static_load: float,
        static_load_rating: Optional[float] = None
    ) -> float:
        """
        Calculate static safety factor.
        
        Formula: fs = Co / Po
        Where Co = basic static load rating, Po = equivalent static load
        
        Args:
            equivalent_static_load: Equivalent static load in N
            static_load_rating: Basic static load rating in N - if None, uses geometry.static_load_rating
            
        Returns:
            Static safety factor (dimensionless)
        """
        if static_load_rating is None:
            static_load_rating = self.geometry.static_load_rating
            
        if equivalent_static_load <= 0:
            logger.warning("Equivalent static load is zero or negative - infinite safety factor")
            return float('inf')
            
        if static_load_rating <= 0:
            logger.warning("Static load rating is zero or negative - zero safety factor")
            return 0.0
            
        safety_factor = static_load_rating / equivalent_static_load
        logger.debug(f"Static safety factor: {safety_factor:.2f} (Co={static_load_rating:.2f}, Po={equivalent_static_load:.2f})")
        return safety_factor

    def estimate_friction_torque(
        self,
        radial_load: float,
        axial_load: float,
        speed: float,
        lubrication_type: str = "oil",
        viscosity: float = 20.0  # mm^2/s at operating temp
    ) -> float:
        """
        Estimate bearing friction torque.
        
        Simplified model: M = M0 + M1
        Where M0 = f0 * (ν * n)^0.6 * d^3  (hydrodynamic friction)
              M1 = f1 * P * d               (boundary friction)
              
        For simplicity, we'll use an empirical approach based on bearing type.
        
        Args:
            radial_load: Radial load in N
            axial_load: Axial load in N
            speed: Rotational speed in rpm
            lubrication_type: "oil" or "grease"
            viscosity: Kinematic viscosity in mm^2/s
            
        Returns:
            Friction torque in N*mm
        """
        # Simplified friction model based on bearing type
        if self.geometry.bearing_type == "ball":
            # Ball bearing friction coefficient (typical)
            f0 = 0.0015  # Hydrodynamic friction factor
            f1 = 0.0005  # Boundary friction factor
        elif self.geometry.bearing_type == "roller":
            f0 = 0.0020
            f1 = 0.0010
        else:
            f0 = 0.0018
            f1 = 0.0007
            
        # Mean diameter
        dm = (self.geometry.bore_diameter + self.geometry.outer_diameter) / 2.0  # mm
        
        # Hydrodynamic friction torque
        # M0 = f0 * dm^3 * (viscosity * speed)^0.6
        # Using simplified constants for demonstration
        n_factor = speed / 1000.0  # Normalize speed
        visc_factor = viscosity / 20.0  # Normalize viscosity
        M0 = f0 * (dm**3) * (n_factor * visc_factor)**0.6 * 0.1  # Scaling factor
        
        # Boundary friction torque
        # M1 = f1 * P * dm
        P = math.sqrt(radial_load**2 + axial_load**2)  # Equivalent load
        M1 = f1 * P * dm * 0.05  # Scaling factor
        
        friction_torque = M0 + M1
        
        logger.debug(f"Friction torque: {friction_torque:.2f} N*mm (M0={M0:.2f}, M1={M1:.2f})")
        return friction_torque

    def calculate_power_loss(self, friction_torque: float, speed: float) -> float:
        """
        Calculate power loss due to bearing friction.
        
        Formula: P_loss = M * ω
        Where M = friction torque (N*m), ω = angular velocity (rad/s)
        
        Args:
            friction_torque: Friction torque in N*mm
            speed: Rotational speed in rpm
            
        Returns:
            Power loss in Watts
        """
        # Convert friction torque from N*mm to N*m
        M_Nm = friction_torque / 1000.0
        
        # Convert speed from rpm to rad/s
        omega = speed * math.pi / 30.0  # rad/s
        
        power_loss = M_Nm * omega
        logger.debug(f"Power loss: {power_loss:.3f} W (M={M_Nm:.4f} N*m, ω={omega:.2f} rad/s)")
        return power_loss

    def analyze_bearing(
        self, 
        loads: BearingLoads,
        temperature_rise_per_watt: float = 0.5  # °C/W (simplified thermal model)
    ) -> BearingResults:
        """
        Perform complete bearing analysis.
        
        Args:
            loads: BearingLoads object containing applied loads and speed
            temperature_rise_per_watt: Temperature rise per watt of power loss (°C/W)
            
        Returns:
            BearingResults object with life, safety factors, and performance metrics
        """
        logger.info("Starting bearing analysis")

        # Apply thermal adjustment if temperature change is specified
        if abs(loads.temperature_change) >= 0.5:
            adj = self.calculate_temperature_adjusted_properties(loads.temperature_change)
            self._thermal_notes = [
                f"Thermal effects applied: dT={loads.temperature_change:+.1f}C",
                f"Derated dynamic load: {adj['dynamic_load_rating']:.1f} N",
                f"Derated static load: {adj['static_load_rating']:.1f} N",
            ]
        else:
            adj = None
            self._thermal_notes = None
        
        # Determine adjusted load ratings if thermal effects are active
        dyn_rating = adj["dynamic_load_rating"] if adj else None
        stat_rating = adj["static_load_rating"] if adj else None

        # Calculate equivalent loads
        # For simplicity, we'll use factors based on bearing type
        if self.geometry.bearing_type == "ball":
            # For ball bearings, approximate factors (would normally use Fa/Fr ratio to lookup X,Y)
            if loads.radial_load > 0:
                FaFr_ratio = loads.axial_load / loads.radial_load
                if FaFr_ratio <= 0.25:
                    X, Y = 1.0, 0.0
                elif FaFr_ratio <= 0.5:
                    X, Y = 0.92, 0.39
                elif FaFr_ratio <= 1.0:
                    X, Y = 0.82, 0.78
                else:
                    X, Y = 0.66, 1.24
            else:
                # Pure axial load
                X, Y = 0.0, 1.0
        else:
            # For roller bearings and others, use simplified factors
            X, Y = 1.0, 0.0  # Conservative: only radial load considered
            
        equivalent_dynamic_load = self.calculate_equivalent_dynamic_load(
            loads.radial_load, 
            loads.axial_load,
            radial_factor=X,
            axial_factor=Y
        )
        
        equivalent_static_load = self.calculate_equivalent_static_load(
            loads.radial_load,
            loads.axial_load,
            radial_factor=0.6,
            axial_factor=0.5
        )
        
        # Calculate fatigue life with thermal-adjusted ratings
        life_hours, life_revolutions = self.calculate_fatigue_life(
            equivalent_dynamic_load,
            dynamic_load_rating=dyn_rating
        )
        
        # Calculate static safety factor with thermal-adjusted ratings
        static_safety_factor = self.calculate_static_safety_factor(
            equivalent_static_load,
            static_load_rating=stat_rating
        )
        
        # Calculate friction and power loss
        friction_torque = self.estimate_friction_torque(
            loads.radial_load,
            loads.axial_load,
            loads.speed
        )
        power_loss = self.calculate_power_loss(friction_torque, loads.speed)
        
        # Estimate operating temperature (simplified)
        ambient_temp = 25.0  # °C
        temp_rise = power_loss * temperature_rise_per_watt
        operating_temp = ambient_temp + temp_rise
        
        # Check for hydrodynamic lubrication (simplified)
        # In reality, this depends on speed, viscosity, load, and geometry
        hydrodynamic_lubrication = (loads.speed > 100 and power_loss < 10.0)  # Simplified criterion
        
        # Determine if bearing passes basic checks
        passed = True
        notes = []
        failure_mode = None
        
        # Check minimum life requirement (e.g., 10,000 hours for industrial equipment)
        min_life_hours = 10000.0
        if life_hours < min_life_hours:
            passed = False
            notes.append(f"Fatigue life ({life_hours:.1f} hours) below minimum ({min_life_hours:.1f} hours)")
            failure_mode = "fatigue"
            
        # Check static safety factor (typically > 0.5-1.0 depending on application)
        min_static_fs = 1.0
        if static_safety_factor < min_static_fs:
            passed = False
            notes.append(f"Static safety factor ({static_safety_factor:.2f}) below minimum ({min_static_fs:.2f})")
            if failure_mode is None:
                failure_mode = "static_overload"
                
        # Check temperature (typical max for grease lubrication)
        max_temp = 80.0  # °C
        if operating_temp > max_temp:
            passed = False
            notes.append(f"Operating temperature ({operating_temp:.1f} °C) exceeds limit ({max_temp} °C)")
            if failure_mode is None:
                failure_mode = "overheating"
                
        # Check speed limit
        if loads.speed > self.geometry.limiting_speed:
            passed = False
            notes.append(f"Speed ({loads.speed:.0f} rpm) exceeds limiting speed ({self.geometry.limiting_speed:.0f} rpm)")
            if failure_mode is None:
                failure_mode = "speed_exceeded"
                
        # Append thermal notes if applicable
        if self._thermal_notes:
            notes.extend(self._thermal_notes)

        results = BearingResults(
            equivalent_dynamic_load=equivalent_dynamic_load,
            equivalent_static_load=equivalent_static_load,
            fatigue_life_hours=life_hours,
            fatigue_life_revolutions=life_revolutions,
            static_safety_factor=static_safety_factor,
            hydrodynamic_lubrication=hydrodynamic_lubrication,
            operating_temperature=operating_temp,
            friction_torque=friction_torque,
            power_loss=power_loss,
            passed=passed,
            notes=notes,
            failure_mode=failure_mode
        )
        
        logger.info(f"Bearing analysis complete. Passed: {passed}, Life: {life_hours:.1f} hours, "
                   f"Static FS: {static_safety_factor:.2f}")
        return results


# Convenience functions for direct use
def analyze_bearing(
    bore_diameter: float,
    outer_diameter: float,
    width: float,
    dynamic_load_rating: float,
    static_load_rating: float,
    limiting_speed: float,
    radial_load: float = 0.0,
    axial_load: float = 0.0,
    speed: float = 0.0,
    bearing_type: str = "ball",
    temperature_rise_per_watt: float = 0.5,
    temperature_change: float = 0.0,
    thermal_expansion: float = 12.0e-6,
    reference_temperature: float = 20.0
) -> BearingResults:
    """
    Convenience function for simple bearing analysis.
    
    Args:
        bore_diameter: Bearing bore diameter in mm
        outer_diameter: Bearing outer diameter in mm
        width: Bearing width in mm
        dynamic_load_rating: Basic dynamic load rating (C) in N
        static_load_rating: Basic static load rating (Co) in N
        limiting_speed: Maximum speed in rpm
        radial_load: Applied radial load in N
        axial_load: Applied axial load in N
        speed: Rotational speed in rpm
        bearing_type: Type of bearing ("ball", "roller", etc.)
        temperature_rise_per_watt: Temperature rise per watt of power loss (°C/W)
        temperature_change: Temperature change from reference in °C (0 = no thermal effects)
        thermal_expansion: Coefficient of thermal expansion in 1/°C
        reference_temperature: Reference temperature for zero thermal strain in °C
        
    Returns:
        BearingResults object
    """
    geometry = BearingGeometry(
        bearing_type=bearing_type,
        bore_diameter=bore_diameter,
        outer_diameter=outer_diameter,
        width=width,
        dynamic_load_rating=dynamic_load_rating,
        static_load_rating=static_load_rating,
        limiting_speed=limiting_speed,
        thermal_expansion=thermal_expansion,
        reference_temperature=reference_temperature
    )
    loads = BearingLoads(
        radial_load=radial_load,
        axial_load=axial_load,
        speed=speed,
        temperature_change=temperature_change
    )
    
    analyzer = BearingAnalyzer(geometry)
    return analyzer.analyze_bearing(loads, temperature_rise_per_watt)


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("BEARING THERMAL EFFECTS DEMONSTRATION")
    print("=" * 60)
    
    # Common parameters
    common = dict(
        bore_diameter=25.0,
        outer_diameter=52.0,
        width=15.0,
        dynamic_load_rating=20000.0,
        static_load_rating=10000.0,
        limiting_speed=15000.0,
        radial_load=500.0,
        axial_load=200.0,
        speed=1500.0,
        bearing_type="ball"
    )
    
    # Baseline (no thermal effects)
    print("\n--- Baseline (No Thermal Effects) ---")
    base = analyze_bearing(**common)
    print(f"  Fatigue Life: {base.fatigue_life_hours:.1f} hours")
    print(f"  Static Safety Factor: {base.static_safety_factor:.2f}")
    print(f"  Power Loss: {base.power_loss:.3f} W")
    print(f"  Passed: {base.passed}")
    
    # Thermal case (+150°C to show derating)
    print("\n--- Thermal Case (+150°C) ---")
    hot = analyze_bearing(**common, temperature_change=150.0)
    print(f"  Fatigue Life: {hot.fatigue_life_hours:.1f} hours")
    print(f"  Static Safety Factor: {hot.static_safety_factor:.2f}")
    print(f"  Power Loss: {hot.power_loss:.3f} W")
    print(f"  Passed: {hot.passed}")
    for note in hot.notes:
        print(f"  - {note}")
    
    # Comparison
    print("\n--- Thermal Impact Summary ---")
    life_change = ((hot.fatigue_life_hours - base.fatigue_life_hours) / base.fatigue_life_hours) * 100
    print(f"  Fatigue Life Change: {life_change:+.1f}%")
    print(f"  Static FS Change: {hot.static_safety_factor - base.static_safety_factor:+.2f}")
    print()

    # Standard single bearing analysis (baseline)
    print("\n--- Standard Single Bearing Analysis (Baseline) ---")
    results = analyze_bearing(**common)
    print(f"  Equivalent Dynamic Load: {results.equivalent_dynamic_load:.2f} N")
    print(f"  Equivalent Static Load: {results.equivalent_static_load:.2f} N")
    print(f"  Fatigue Life: {results.fatigue_life_hours:.1f} hours")
    print(f"  Static Safety Factor: {results.static_safety_factor:.2f}")
    print(f"  Friction Torque: {results.friction_torque:.2f} N*mm")
    print(f"  Power Loss: {results.power_loss:.3f} W")
    print(f"  Operating Temperature: {results.operating_temperature:.1f} °C")
    print(f"  Hydrodynamic Lubrication: {results.hydrodynamic_lubrication}")
    print(f"  Passed: {results.passed}")
    if results.notes:
        print(f"  Notes: {', '.join(results.notes)}")
    if results.failure_mode:
        print(f"  Failure Mode: {results.failure_mode}")
#!/usr/bin/env python3
"""
Example demonstrating the thermal effects enhancement to the physics engine.

This example shows how temperature changes affect shaft stress and overall system performance,
illustrating the value of the thermal effects enhancement to the Physics & FEA Engine.
"""

import app.physics.shafts as shafts
import app.physics.bearings as bearings
import app.physics.fatigue as fatigue


def analyze_shaft_thermal_scenarios():
    """Analyze shaft under various thermal conditions to demonstrate enhancement value."""
    print("=" * 70)
    print("THERMAL ENHANCEMENT DEMONSTRATION FOR PHYSICS & FEA ENGINE")
    print("=" * 70)
    print("This example shows how temperature changes affect mechanical stress")
    print("in shaft systems, demonstrating the value of thermal effects modeling.")
    print()
    
    # Shaft parameters (representative of a motor shaft)
    diameter = 25.0      # mm
    length = 300.0       # mm
    torque = 75.0        # N*m
    bending_moment = 150.0  # N*m (from pulley weight or gear forces)
    transverse_force = 300.0  # N
    allowable_stress = 170.0  # MPa (for heat-treated steel)
    
    print(f"Shalt Parameters:")
    print(f"  Diameter: {diameter} mm")
    print(f"  Length: {length} mm")
    print(f"  Torque: {torque} N*m")
    print(f"  Bending Moment: {bending_moment} N*m")
    print(f"  Transverse Force: {transverse_force} N")
    print(f"  Allowable Stress: {allowable_stress} MPa")
    print()
    
    # Scenario 1: Room temperature (baseline)
    print("-" * 50)
    print("SCENARIO 1: ROOM TEMPERATURE (20°C) - BASELINE")
    print("-" * 50)
    
    result_baseline = shafts.analyze_simple_shaft(
        diameter=diameter,
        length=length,
        torque=torque,
        bending_moment=bending_moment,
        transverse_force=transverse_force,
        allowable_stress=allowable_stress,
        temperature_change=0.0  # No temperature change from reference
    )
    
    print(f"Results:")
    print(f"  Von Mises Stress: {result_baseline.von_mises_stress:.2f} MPa")
    print(f"  Safety Factor: {result_baseline.safety_factor:.2f}")
    print(f"  Passed: {result_baseline.passed}")
    if result_baseline.notes:
        for note in result_baseline.notes:
            if "Thermal stress" not in note:  # Skip thermal notes for baseline
                print(f"  Note: {note}")
    print()
    
    # Scenario 2: Elevated temperature (operating condition)
    print("-" * 50)
    print("SCENARIO 2: ELEVATED TEMPERATURE (70°C OPERATING)")
    print("-" * 50)
    
    result_hot = shafts.analyze_simple_shaft(
        diameter=diameter,
        length=length,
        torque=torque,
        bending_moment=bending_moment,
        transverse_force=transverse_force,
        allowable_stress=allowable_stress,
        temperature_change=50.0  # 50°C increase from 20°C reference
    )
    
    print(f"Results:")
    print(f"  Von Mises Stress: {result_hot.von_mises_stress:.2f} MPa")
    print(f"  Safety Factor: {result_hot.safety_factor:.2f}")
    print(f"  Passed: {result_hot.passed}")
    for note in result_hot.notes:
        print(f"  Note: {note}")
    print()
    
    # Scenario 3: High temperature (extreme condition)
    print("-" * 50)
    print("SCENARIO 3: HIGH TEMPERATURE (120°C - EXTREME CONDITION)")
    print("-" * 50)
    
    result_extreme = shafts.analyze_simple_shaft(
        diameter=diameter,
        length=length,
        torque=torque,
        bending_moment=bending_moment,
        transverse_force=transverse_force,
        allowable_stress=allowable_stress,
        temperature_change=100.0  # 100°C increase from 20°C reference
    )
    
    print(f"Results:")
    print(f"  Von Mises Stress: {result_extreme.von_mises_stress:.2f} MPa")
    print(f"  Safety Factor: {result_extreme.safety_factor:.2f}")
    print(f"  Passed: {result_extreme.passed}")
    for note in result_extreme.notes:
        print(f"  Note: {note}")
    print()
    
    # Analysis of thermal effects
    print("-" * 50)
    print("THERMAL EFFECTS ANALYSIS")
    print("-" * 50)
    
    mechanical_stress = result_baseline.von_mises_stress
    thermal_stress_50c = result_hot.von_mises_stress - mechanical_stress
    thermal_stress_100c = result_extreme.von_mises_stress - mechanical_stress
    
    print(f"Mechanical Stress Baseline: {mechanical_stress:.2f} MPa")
    print(f"Induced Thermal Stress (50°C ΔT): {thermal_stress_50c:.2f} MPa")
    print(f"Induced Thermal Stress (100°C ΔT): {thermal_stress_100c:.2f} MPa")
    print(f"Thermal Stress per °C: {thermal_stress_50c/50.0:.4f} MPa/°C")
    print()
    print("Key Insights:")
    print(f"1. Temperature increase of 50°C increases stress by {thermal_stress_50c:.1f} MPa")
    print(f"2. This represents a {((result_hot.von_mises_stress/mechanical_stress)-1)*100:.1f}% increase in stress")
    print(f"3. Safety factor drops from {result_baseline.safety_factor:.2f} to {result_hot.safety_factor:.2f}")
    if not result_hot.passed and result_baseline.passed:
        print(f"4. Thermal effects can cause failure in otherwise acceptable designs")
    print()
    
    # Demonstrate integration with other physics modules
    print("-" * 50)
    print("INTEGRATION WITH BEARING & FATIGUE ANALYSIS")
    print("-" * 50)
    
    # Bearing analysis (affected by thermal expansion changing clearances)
    bearing_result = bearings.analyze_bearing(
        bore_diameter=20.0,
        outer_diameter=47.0,
        width=14.0,
        dynamic_load_rating=15000.0,
        static_load_rating=8000.0,
        limiting_speed=10000.0,
        radial_load=150.0,  # Reduced load due to thermal considerations
        axial_load=50.0,
        speed=1500.0,
        bearing_type="ball"
    )
    
    print(f"Bearing Analysis (Conservative Loading Due to Thermal Effects):")
    print(f"  Passed: {bearing_result.passed}")
    print(f"  Fatigue Life: {bearing_result.fatigue_life_hours:.0f} hours")
    print(f"  Static Safety Factor: {bearing_result.static_safety_factor:.2f}")
    print()
    
    # Fatigue analysis (temperature affects fatigue life)
    # Note: For simplicity, we're using room temperature fatigue properties
    # In a full implementation, temperature would also affect fatigue properties
    fatigue_result = fatigue.analyze_fatigue(
        ultimate_tensile_strength=500.0,  # Slightly reduced for elevated temp
        yield_strength=350.0,
        alternating_stress=result_hot.max_bending_stress,
        mean_stress=result_hot.max_shear_stress,
        num_cycles=int(1500 * 8 * 3600 * 365),  # 1 year at 8 hrs/day
        load_type='bending',
        frequency=1500.0/60.0  # Hz
    )
    
    print(f"Fatigue Analysis (Conservative Properties for Elevated Temp):")
    print(f"  Passed: {fatigue_result.passed}")
    if fatigue_result.life_cycles == float('inf'):
        print(f"  Life: Infinite cycles")
    else:
        print(f"  Life: {fatigue_result.life_cycles:.0f} cycles")
    print(f"  Safety Factor: {fatigue_result.safety_factor:.2f}")
    print()
    
    # Overall assessment
    print("-" * 50)
    print("OVERALL ASSESSMENT WITH THERMAL EFFECTS")
    print("-" * 50)
    
    overall_passed = result_hot.passed and bearing_result.passed and fatigue_result.passed
    
    print(f"Overall System Status (at 70°C operating temp): {'PASS' if overall_passed else 'FAIL'}")
    print()
    print("Value of Thermal Effects Enhancement:")
    print("• Predicts temperature-induced stress that mechanical-only analysis misses")
    print("• Enables proper safety factor evaluation under operating conditions")
    print("• Prevents unexpected field failures due to thermal-mechanical coupling")
    print("• Allows optimization of cooling systems and material selection")
    print("• Essential for accurate digital twin and predictive maintenance")
    print()
    print("=" * 70)


if __name__ == "__main__":
    analyze_shaft_thermal_scenarios()
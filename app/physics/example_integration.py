#!/usr/bin/env python3
"""
Example integration analysis showing how to use multiple physics modules together
to analyze a complete mechanical system.

This example analyzes a motor shaft system:
1. Shaft stress and deflection analysis
2. Bearing life and friction analysis  
3. Fatigue life assessment
4. Vibration analysis for operational stability
"""

import app.physics.shafts as shafts
import app.physics.bearings as bearings
import app.physics.fatigue as fatigue
import app.physics.vibration as vibration


def analyze_motor_shaft_system():
    """Analyze a complete motor shaft system using multiple physics modules."""
    print("=" * 60)
    print("MOTOR SHAFT SYSTEM ANALYSIS")
    print("=" * 60)
    
    # System parameters
    shaft_length = 200.0      # mm
    shaft_diameter = 25.0     # mm
    motor_torque = 100.0      # N*m
    motor_weight = 500.0      # N (weight of motor and load)
    operating_speed = 1800.0  # rpm
    
    print(f"System Parameters:")
    print(f"  Shaft Length: {shaft_length} mm")
    print(f"  Shaft Diameter: {shaft_diameter} mm")
    print(f"  Motor Torque: {motor_torque} N*m")
    print(f"  Motor Weight: {motor_weight} N")
    print(f"  Operating Speed: {operating_speed} rpm")
    print()
    
    # 1. SHAFT ANALYSIS
    print("-" * 40)
    print("1. SHAFT ANALYSIS")
    print("-" * 40)
    
    shaft_result = shafts.analyze_simple_shaft(
        diameter=shaft_diameter,
        length=shaft_length,
        torque=motor_torque,
        bending_moment=motor_weight * shaft_length / 4,  # Simplified: central load on simply supported shaft
        transverse_force=motor_weight / 2,               # Reaction at each bearing
        allowable_stress=150.0  # MPa for mild steel
    )
    
    print(f"Shaft Analysis Results:")
    print(f"  Passed: {shaft_result.passed}")
    print(f"  Von Mises Stress: {shaft_result.von_mises_stress:.2f} MPa")
    print(f"  Safety Factor: {shaft_result.safety_factor:.2f}")
    print(f"  Deflection: {shaft_result.deflection:.3f} mm")
    print(f"  Angle of Twist: {shaft_result.angle_of_twist:.2f} degrees")
    if shaft_result.notes:
        print(f"  Notes: {', '.join(shaft_result.notes)}")
    print()
    
    # 2. BEARING ANALYSIS
    print("-" * 40)
    print("2. BEARING ANALYSIS")
    print("-" * 40)
    
    # Assuming two identical bearings supporting the shaft
    bearing_result = bearings.analyze_bearing(
        bore_diameter=20.0,      # mm (to fit shaft)
        outer_diameter=47.0,     # mm
        width=14.0,              # mm
        dynamic_load_rating=20000.0,  # N (C)
        static_load_rating=10000.0,   # N (Co)
        limiting_speed=15000.0, # rpm
        radial_load=motor_weight / 2,     # N (radial load per bearing)
        axial_load=motor_torque * 0.1 / 20.0,  # N (approx axial load from torque, assuming 20mm lever arm)
        speed=operating_speed,            # rpm
        bearing_type="ball"
    )
    
    print(f"Bearing Analysis Results (per bearing):")
    print(f"  Passed: {bearing_result.passed}")
    print(f"  Equivalent Dynamic Load: {bearing_result.equivalent_dynamic_load:.2f} N")
    print(f"  Fatigue Life: {bearing_result.fatigue_life_hours:.0f} hours")
    print(f"  Static Safety Factor: {bearing_result.static_safety_factor:.2f}")
    print(f"  Power Loss: {bearing_result.power_loss:.3f} W")
    print(f"  Operating Temperature: {bearing_result.operating_temperature:.1f} °C")
    if bearing_result.notes:
        print(f"  Notes: {', '.join(bearing_result.notes)}")
    print()
    
    # 3. FATIGUE ANALYSIS
    print("-" * 40)
    print("3. FATIGUE ANALYSIS")
    print("-" * 40)
    
    # Extract alternating and mean stress from shaft analysis for fatigue
    # For rotating bending with steady torque:
    # Alternating stress = bending stress (reverses as shaft rotates)
    # Mean stress = torsional stress (steady) + any axial stress
    alternating_stress = shaft_result.max_bending_stress  # Reversing bending stress
    mean_stress = shaft_result.max_shear_stress  # Steady torsional stress (approximation)
    
    fatigue_result = fatigue.analyze_fatigue(
        ultimate_tensile_strength=400.0,  # MPa for mild steel
        yield_strength=250.0,             # MPa
        alternating_stress=alternating_stress,
        mean_stress=mean_stress,
        num_cycles=int(operating_speed * 8 * 3600 * 30),  # 30 days at 8 hours/day
        load_type='bending',
        frequency=operating_speed / 60.0  # Hz (cycles per second)
    )
    
    print(f"Fatigue Analysis Results:")
    print(f"  Passed: {fatigue_result.passed}")
    print(f"  Safety Factor: {fatigue_result.safety_factor:.2f}")
    if fatigue_result.life_cycles == float('inf'):
        print(f"  Life: Infinite cycles (> {fatigue_result.num_cycles if hasattr(fatigue_result, 'num_cycles') else 'design life'} cycles)")
    else:
        print(f"  Life: {fatigue_result.life_cycles:.0f} cycles")
    if fatigue_result.life_hours == float('inf'):
        print(f"  Life: Infinite hours")
    else:
        print(f"  Life: {fatigue_result.life_hours:.0f} hours")
    print(f"  Damage Fraction: {fatigue_result.damage_fraction:.2e}")
    print(f"  Equivalent Alternating Stress: {fatigue_result.equivalent_alternating_stress:.2f} MPa")
    if fatigue_result.notes:
        print(f"  Notes: {', '.join(fatigue_result.notes)}")
    print()
    
    # 4. VIBRATION ANALYSIS
    print("-" * 40)
    print("4. VIBRATION ANALYSIS")
    print("-" * 40)
    
    # Simple vibration model: shaft as rotating mass with bearing support
    shaft_mass = 7.85e-6 * 3.14159 * (shaft_diameter/2)**2 * shaft_length  # kg (volume * density)
    # Equivalent stiffness from bearing support (simplified)
    bearing_stiffness = 100.0 * 2.0  # N/mm * 2 bearings, converted to N/m
    bearing_stiffness_Nm = bearing_stiffness * 1000.0  # N/m
    damping_coefficient = 5.0 * 2.0  # N*s/mm * 2, converted to N*s/m
    damping_coefficient_Nsm = damping_coefficient * 1000.0  # N*s/m
    
    vibration_result = vibration.analyze_vibration(
        mass=shaft_mass,
        stiffness=bearing_stiffness_Nm,
        damping_coefficient=damping_coefficient_Nsm,
        force_amplitude=shaft_result.max_bending_stress * 3.14159 * (shaft_diameter/2)**3 * 0.001,  # N (approx imbalance force)
        force_frequency=operating_speed / 60.0  # Hz
    )
    
    print(f"Vibration Analysis Results:")
    print(f"  Passed: {vibration_result.passed}")
    print(f"  Natural Frequency: {vibration_result.natural_frequency:.2f} Hz")
    print(f"  Damping Ratio: {vibration_result.damping_ratio:.3f}")
    print(f"  Displacement Amplitude: {vibration_result.displacement_amplitude*1000:.3f} mm")
    print(f"  Velocity Amplitude: {vibration_result.velocity_amplitude:.3f} m/s")
    print(f"  Acceleration Amplitude: {vibration_result.acceleration_amplitude:.2f} m/s^2")
    print(f"  Resonance: {vibration_result.resonance}")
    if vibration_result.notes:
        print(f"  Notes: {', '.join(vibration_result.notes)}")
    print()
    
    # OVERALL ASSESSMENT
    print("-" * 40)
    print("OVERALL SYSTEM ASSESSMENT")
    print("-" * 40)
    
    all_passed = (
        shaft_result.passed and 
        bearing_result.passed and 
        fatigue_result.passed and 
        vibration_result.passed
    )
    
    print(f"Overall System Status: {'PASS' if all_passed else 'FAIL'}")
    print()
    print("Key Metrics:")
    print(f"  Shaft Safety Factor: {shaft_result.safety_factor:.2f}")
    print(f"  Bearing Life: {bearing_result.fatigue_life_hours:.0f} hours")
    print(f"  Fatigue Safety Factor: {fatigue_result.safety_factor:.2f}")
    print(f"  Vibration Margin: {'Good' if not vibration_result.resonance else 'RESONANCE DETECTED'}")
    
    if not all_passed:
        print()
        print("Issues Found:")
        if not shaft_result.passed:
            print("  - Shaft stress or deflection excessive")
        if not bearing_result.passed:
            print("  - Bearing life or overload issue")
        if not fatigue_result.passed:
            print("  - Fatigue life insufficient")
        if not vibration_result.passed:
            print("  - Vibration/resonance problem")
    
    print()
    print("=" * 60)
    
    return {
        'shaft': shaft_result,
        'bearing': bearing_result,
        'fatigue': fatigue_result,
        'vibration': vibration_result,
        'overall_passed': all_passed
    }


if __name__ == "__main__":
    # Run the integrated analysis
    results = analyze_motor_shaft_system()
    
    # Exit with error code if overall system failed
    exit(0 if results['overall_passed'] else 1)
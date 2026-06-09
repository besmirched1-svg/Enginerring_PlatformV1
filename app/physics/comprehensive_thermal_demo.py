#!/usr/bin/env python3
"""
Comprehensive demonstration of thermal effects enhancement to the physics engine
for mechanical stress analysis.

This example shows how temperature changes affect:
1. Shaft stress (thermal stress addition)
2. Bearing performance (temperature rise from friction, affecting lubrication and life)
3. Fatigue life (temperature factor reducing endurance limit)

It illustrates the value of thermal effects modeling in predicting real-world
performance and preventing unexpected failures.
"""

import sys
import os
# Add the root directory to the Python path so we can import app.physics
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import app.physics.shafts as shafts
import app.physics.bearings as bearings
import app.physics.fatigue as fatigue

def demonstrate_thermal_effects():
    import math
    print("=" * 80)
    print("COMPREHENSIVE THERMAL EFFECTS DEMONSTRATION")
    print("Physics & FEA Engine for Mechanical Stress Analysis")
    print("=" * 80)
    print()
    
    # System parameters (representative of a motor shaft with bearing)
    shaft_diameter = 25.0      # mm
    shaft_length = 300.0       # mm
    torque = 75.0              # N*m
    bending_moment = 150.0     # N*m
    transverse_force = 300.0   # N
    allowable_stress = 170.0   # MPa (for heat-treated steel)
    
    print(f"SYSTEM PARAMETERS:")
    print(f"  Shaft Diameter: {shaft_diameter} mm")
    print(f"  Shaft Length: {shaft_length} mm")
    print(f"  Applied Torque: {torque} N*m")
    print(f"  Applied Bending Moment: {bending_moment} N*m")
    print(f"  Applied Transverse Force: {transverse_force} N")
    print(f"  Allowable Shaft Stress: {allowable_stress} MPa")
    print()
    
    # Bearing parameters (supporting the shaft)
    bearing_bore = 20.0       # mm
    bearing_outer = 47.0      # mm
    bearing_width = 14.0      # mm
    bearing_dynamic_rating = 15000.0   # N
    bearing_static_rating = 8000.0     # N
    bearing_limiting_speed = 10000.0   # rpm
    bearing_speed = 1500.0    # rpm
    bearing_radial_load = 150.0   # N (from shaft transverse force, simplified)
    bearing_axial_load = 50.0     # N
    
    print(f"BEARING PARAMETERS:")
    print(f"  Bore Diameter: {bearing_bore} mm")
    print(f"  Outer Diameter: {bearing_outer} mm")
    print(f"  Width: {bearing_width} mm")
    print(f"  Dynamic Load Rating: {bearing_dynamic_rating} N")
    print(f"  Static Load Rating: {bearing_static_rating} N")
    print(f"  Limiting Speed: {bearing_limiting_speed} rpm")
    print(f"  Operating Speed: {bearing_speed} rpm")
    print(f"  Radial Load: {bearing_radial_load} N")
    print(f"  Axial Load: {bearing_axial_load} N")
    print()
    
    # Fatigue parameters (for shaft material)
    fatigue_uts = 500.0      # MPa (ultimate tensile strength)
    fatigue_yield = 350.0    # MPa (yield strength)
    # For fatigue, we'll use the alternating stress from shaft bending
    # and mean stress from shaft axial (which we set to 0 for simplicity)
    # We'll extract the alternating and mean stresses from shaft analysis later.
    
    print(f"FATIGUE MATERIAL PARAMETERS:")
    print(f"  Ultimate Tensile Strength: {fatigue_uts} MPa")
    print(f"  Yield Strength: {fatigue_yield} MPa")
    print()
    
    # Temperature scenarios to analyze
    temperature_changes = [0, 20, 50, 80, 100]  # °C change from reference (20°C)
    
    print("=" * 80)
    print("THERMAL EFFECTS ANALYSIS")
    print("=" * 80)
    print(f"{'Temp Change':<12} {'Shaft VM Stress':<18} {'Shaft SF':<12} {'Bearing Temp':<15} {'Bearing Life':<15} {'Fatigue SF':<12} {'Notes'}")
    print(f"{'(°C)':<12} {'(MPa)':<18} {'':<12} {'(°C)':<15} {'(hours)':<15} {'':<12}")
    print("-" * 80)
    
    for delta_T in temperature_changes:
        # 1. Shaft analysis with thermal effects
        shaft_result = shafts.analyze_simple_shaft(
            diameter=shaft_diameter,
            length=shaft_length,
            torque=torque,
            bending_moment=bending_moment,
            transverse_force=transverse_force,
            allowable_stress=allowable_stress,
            temperature_change=delta_T  # Temperature change from reference
        )
        
        # 2. Bearing analysis - note: we need to estimate the temperature rise
        #    from bearing friction, but also the ambient temperature changes
        #    due to operating conditions. For simplicity, we'll assume the
        #    bearing sees the same temperature change as the shaft (or we
        #    can add the bearing's own temperature rise).
        #    We'll calculate the bearing's operating temperature based on
        #    power loss and then add the ambient delta_T.
        bearing_result = bearings.analyze_bearing(
            bore_diameter=bearing_bore,
            outer_diameter=bearing_outer,
            width=bearing_width,
            dynamic_load_rating=bearing_dynamic_rating,
            static_load_rating=bearing_static_rating,
            limiting_speed=bearing_limiting_speed,
            radial_load=bearing_radial_load,
            axial_load=bearing_axial_load,
            speed=bearing_speed,
            bearing_type="ball",
            temperature_rise_per_watt=0.5  # °C/W
        )
        # The bearing result already includes an operating temperature based on
        # ambient (hardcoded 25°C) plus temperature rise from power loss.
        # To simulate ambient temperature change, we adjust the bearing's
        # operating temperature by delta_T (assuming the ambient changes by delta_T).
        # But note: the bearing analysis uses a fixed ambient of 25°C.
        # For simplicity, we'll just note the bearing's operating temperature
        # as reported (which is for 25°C ambient) and then mentally add delta_T.
        # Alternatively, we could modify the bearing analysis to accept ambient,
        # but to keep it simple, we'll just report the bearing's operating
        # temperature as if ambient is 25°C, and note that actual temperature
        # would be higher by delta_T in hot environments.
        bearing_operating_temp = bearing_result.operating_temperature  # This is for 25°C ambient
        
        # 3. Fatigue analysis - we need to extract stresses from shaft
        #    and apply temperature factor to endurance limit.
        #    We'll use the alternating and mean stresses from the shaft
        #    (without thermal effects for the alternating? Actually, thermal
        #    stress is mean stress if constant, or alternating if cycling).
        #    For simplicity, we'll assume the thermal stress is a mean stress
        #    (constant temperature offset) and the mechanical alternating
        #    stress is from bending.
        #    We'll calculate the alternating stress from bending moment
        #    and mean stress from axial force (0) plus thermal stress.
        #    But note: the shaft analysis already combines them.
        # 1. Shaft analysis with thermal effects
        shaft_result = shafts.analyze_simple_shaft(
            diameter=shaft_diameter,
            length=shaft_length,
            torque=torque,
            bending_moment=bending_moment,
            transverse_force=transverse_force,
            allowable_stress=allowable_stress,
            temperature_change=delta_T  # Temperature change from reference
        )
        
        # To get component stresses for fatigue, we'll create an analyzer and compute them
        geometry = shafts.ShaftGeometry(
            diameter=shaft_diameter,
            length=shaft_length
        )
        loads = shafts.ShaftLoads(
            torque=torque,
            bending_moment=bending_moment,
            transverse_force=transverse_force,
            temperature_change=delta_T
        )
        analyzer = shafts.ShaftAnalyzer(geometry)
        tau_torsion = analyzer.calculate_torsional_stress(loads.torque)
        sigma_bending = analyzer.calculate_bending_stress(loads.bending_moment)
        sigma_axial = loads.axial_force / (math.pi * (shaft_diameter/2.0)**2) if loads.axial_force != 0 else 0.0
        sigma_thermal = analyzer.calculate_thermal_stress(loads.temperature_change)
        sigma_x = sigma_bending + sigma_axial + sigma_thermal  # Total normal stress
        tau_xy = tau_torsion  # Simplified
        
        # For fatigue, we consider alternating stress as the bending component
        # (assuming rotating bending) and mean stress as axial + thermal
        # (assuming constant axial and thermal)
        sigma_a_fatigue = abs(sigma_bending)  # Alternating (bending)
        sigma_m_fatigue = sigma_axial + sigma_thermal  # Mean (axial + thermal)
        
        # Fatigue analysis with temperature factor
        # Temperature factor for endurance limit: typically >1 for cold, <1 for hot
        # We'll use a simple linear derating for demonstration: 
        #   For steel, endurance limit decreases as temperature increases above ~200°C
        #   But at lower temperatures (like up to 150°C), the effect is small.
        #   We'll use a factor that decreases from 1.0 at 25°C to 0.9 at 150°C.
        #   This is just for demonstration; real values depend on material.
        temp_for_factor = 25.0 + delta_T  # Assuming reference ambient 25°C
        if temp_for_factor <= 25.0:
            temp_factor = 1.0
        elif temp_for_factor >= 150.0:
            temp_factor = 0.9
        else:
            # Linear interpolation between 25°C and 150°C
            temp_factor = 1.0 - (temp_for_factor - 25.0) * (0.1 / 125.0)
        
        fatigue_result = fatigue.analyze_fatigue(
            ultimate_tensile_strength=fatigue_uts,
            yield_strength=fatigue_yield,
            alternating_stress=sigma_a_fatigue,
            mean_stress=sigma_m_fatigue,
            num_cycles=0,  # We just want safety factor and life
            load_type="bending",
            temperature_factor=temp_factor  # This is the key thermal effect on fatigue
        )
        
        # Format values for printing
        shaft_vm_stress = f"{shaft_result.von_mises_stress:.2f}"
        shaft_sf = f"{shaft_result.safety_factor:.2f}"
        bearing_temp = f"{bearing_operating_temp:.1f}"
        bearing_life = f"{bearing_result.fatigue_life_hours:.0f}" if bearing_result.fatigue_life_hours != float('inf') else "inf"
        fatigue_sf = f"{fatigue_result.safety_factor:.2f}" if fatigue_result.safety_factor != float('inf') else "inf"
        
        # Prepare notes
        notes = []
        if not shaft_result.passed:
            notes.append("Shaft fail")
        if not bearing_result.passed:
            notes.append("Bearing fail")
        if not fatigue_result.passed:
            notes.append("Fatigue fail")
        if delta_T > 0:
            notes.append(f"ΔT={delta_T}°C")
        
        note_str = ", ".join(notes) if notes else "All pass"
        
        print(f"{delta_T:<12} {shaft_vm_stress:<18} {shaft_sf:<12} {bearing_temp:<15} {bearing_life:<15} {fatigue_sf:<12} {note_str}")
    
    print()
    print("=" * 80)
    print("KEY INSIGHTS ON THERMAL EFFECTS VALUE")
    print("=" * 80)
    print()
    print("1. SHAFT STRESS:")
    print("   • Thermal stress adds directly to normal stress, increasing von Mises stress")
    print("   • Even moderate temperature rises (50°C) can significantly reduce safety factor")
    print("   • Mechanical-only analysis is non-conservative for elevated temperature operation")
    print()
    print("2. BEARING PERFORMANCE:")
    print("   • Bearing friction generates heat, increasing operating temperature")
    print("   • High temperatures degrade lubricant viscosity, potentially leading to")
    print("     boundary lubrication, increased wear, and premature failure")
    print("   • Thermal expansion affects internal clearances and preload")
    print()
    print("3. FATIGUE LIFE:")
    print("   • Elevated temperatures reduce material endurance limit (temperature factor < 1)")
    print("   • This decreases fatigue safety factor and predicted life")
    print("   • The combined effect of thermal mean stress and reduced endurance limit")
    print("     can be severe for fatigue-critical components")
    print()
    print("4. SYSTEM-LEVEL IMPACT:")
    print("   • Thermal effects couple multiple failure modes (yield, fatigue, wear)")
    print("   • Ignoring thermal effects can lead to unexpected field failures")
    print("   • Proper thermal modeling enables:")
    print("     - Accurate prediction of operating temperatures")
    print("     - Selection of appropriate materials and cooling strategies")
    print("     - Optimization of maintenance intervals based on actual conditions")
    print("     - Enhanced digital twin accuracy for predictive maintenance")
    print()
    print("=" * 80)

if __name__ == "__main__":
    # Import math here to avoid top-level import if not needed
    import math
    demonstrate_thermal_effects()
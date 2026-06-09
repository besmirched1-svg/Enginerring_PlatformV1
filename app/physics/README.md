# Physics & FEA Engine

This module implements the Physics & Finite Element Analysis (FEA) Engine for the OpenSCAD Autonomous Engineering Platform. It provides comprehensive analysis capabilities for mechanical systems including shafts, bearings, frames, rotors, fatigue, and vibration analysis.

## Modules

### 1. Shaft Analysis (`shafts.py`)
- Torsional stress calculation
- Bending stress calculation
- Combined stress analysis using von Mises criterion
- Deflection calculations for various boundary conditions
- Angle of twist calculation
- Principal stress calculation
- Safety factor evaluation

### 2. Bearing Analysis (`bearings.py`)
- Equivalent dynamic load calculation (ISO 281)
- Equivalent static load calculation
- Fatigue life prediction (L10 life)
- Static safety factor calculation
- Friction torque estimation
- Power loss calculation
- Temperature rise estimation
- Lubrication regime assessment

### 3. Frame Analysis (`frames.py`)
- Axial stress calculation
- Shear stress calculation
- Bending stress calculation
- Torsional stress calculation
- Combined stress analysis (von Mises)
- Euler buckling load calculation
- Deflection calculations for various boundary conditions
- Angle of twist calculation
- Safety factor evaluation for all stress modes
- Buckling safety factor

### 4. Rotor Analysis (`rotors.py`)
- Polar moment of inertia calculation
- Mass moment of inertia calculation
- First and higher critical speed calculation
- Imbalance force calculation
- Vibration response due to imbalance
- Twist due to applied torque
- Natural frequency calculation
- Stability assessment

### 5. Fatigue Analysis (`fatigue.py`)
- Endurance limit calculation (Marin factors)
- Mean stress correction (Goodman, Gerber, Soderberg, Elliptic)
- Fatigue life prediction using Basquin's equation
- Fatigue life prediction using endurance limit approach
- Cumulative damage calculation using Miner's rule
- Variable amplitude fatigue analysis
- Safety factor evaluation

### 6. Vibration Analysis (`vibration.py`)
- Natural frequency calculation
- Damping ratio calculation
- Critical damping calculation
- Damped natural frequency calculation
- Magnification factor for forced vibration
- Displacement, velocity, and acceleration amplitude calculation
- Phase angle calculation
- Transmissibility for base excitation
- Forced vibration response analysis
- Resonance detection

## Usage

Each module can be used independently or together for comprehensive mechanical analysis:

```python
import app.physics.shafts as shafts
import app.physics.bearings as bearings
import app.physics.frames as frames
import app.physics.rotors as rotors
import app.physics.fatigue as fatigue
import app.physics.vibration as vibration

# Example: Shaft analysis
shaft_result = shafts.analyze_simple_shaft(
    diameter=25.0,      # mm
    length=200.0,       # mm
    torque=50.0,        # N*m
    bending_moment=100.0, # N*m
    allowable_stress=150.0 # MPa
)

# Example: Bearing analysis
bearing_result = bearings.analyze_bearing(
    bore_diameter=20.0,
    outer_diameter=47.0,
    width=14.0,
    dynamic_load_rating=20000.0,  # N
    static_load_rating=10000.0,   # N
    limiting_speed=15000.0,       # rpm
    radial_load=500.0,            # N
    axial_load=200.0,             # N
    speed=1000.0                  # rpm
)

# Example: Combined analysis
# Analyze a shaft supported by bearings
```

## Design Philosophy

1. **Engineering Accuracy**: Based on established engineering formulas and standards (ISO, AGMA, etc.)
2. **Conservative Assumptions**: Where simplifications are made, they err on the side of safety
3. **Clear Documentation**: Each function includes references to the engineering basis
4. **Extensible Design**: Modular architecture allows for easy enhancement
5. **Integration Ready**: Designed to work with the existing platform's geometry and load systems

## Future Enhancements

1. **Complex Geometry Support**: Move beyond simple shapes to arbitrary cross-sections
2. **Advanced FEA Integration**: Hook into actual FEA solvers (CalculiX, etc.)
3. **Temperature Effects**: Thermal stress and deformation analysis
4. **Contact Analysis**: Hertzian contact stress for gears and cams
5. **Nonlinear Materials**: Plasticity, creep, and viscoelastic behavior
6. **Modal Analysis**: Full modal analysis for complex structures
7. **Random Vibration**: PSD-based vibration analysis
8. **Optimization Integration**: Couple with topology optimization algorithms

## References

- Shigley's Mechanical Engineering Design
- Marks' Standard Handbook for Mechanical Engineers
- ISO 281: Rolling bearings - Dynamic load ratings and rating life
- ASME Boiler and Pressure Vessel Code
- API Standards for rotating equipment
- Various academic papers and industry standards
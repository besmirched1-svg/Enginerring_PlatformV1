# Digital Twin Package

This package implements a Digital Twin simulation system for mechanical machines, enabling time-domain operation simulation, wear and fatigue modeling, and reliability prediction.

## Overview

The Digital Twin creates a virtual counterpart of a physical machine that can simulate its behavior over operational time. It predicts maintenance needs, estimates remaining useful life, and forecasts potential failures based on physics-based models of wear and fatigue.

## Key Features

- **Machine Representation**: Structured representation of machine components (spindle, drum, frame, compression rollers)
- **Wear Modeling**: Archard wear equation and other wear mechanisms (adhesive, abrasive)
- **Fatigue Analysis**: Stress-life (S-N) approach with Miner's rule for damage accumulation
- **Reliability Prediction**: Maintenance forecasting and failure prediction based on wear and fatigue
- **Time-Domain Simulation**: Operate machine for specified hours and predict outcomes
- **Integration Ready**: Compatible with existing platform's machine configuration format

## Components

### Core Modules

1. **`digital_twin.py`** - Main Digital Twin class orchestrating simulation
2. **`machine_representation.py`** - Machine configuration and component definitions
3. **`wear_model.py`** - Wear simulation using Archard and other models
4. **`fatigue_model.py`** - Fatigue life consumption modeling
5. **`reliability_predictor.py`** - Maintenance and failure prediction

### Data Classes

- `MachineConfiguration` - Complete machine specification
- `SpindleComponent`, `DrumComponent`, `FrameComponent`, `CompressionRollerComponent` - Individual components
- `WearState`, `FatigueState` - Component degradation states
- `MaintenanceAlert`, `FailurePrediction` - Predictive maintenance outputs
- `ReliabilityAssessment` - Overall system reliability evaluation
- `SimulationResult` - Complete simulation output

## Usage

### Basic Usage

```python
from app.digital_twin import create_default_digital_twin, create_example_hemp_decotitator_config
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)

# Create digital twin
dt = create_default_digital_twin()

# Create or load machine configuration
machine_config = create_example_hemp_decotitator_config()
# Or load your own configuration:
# machine_config = MachineConfiguration.from_dict(your_config_dict)

# Load machine into digital twin
dt.load_machine_configuration(machine_config)

# Simulate operation for 1000 hours
result = dt.simulate_operation("your_machine_id", 1000.0)

# Access results
print(f"Reliability: {result.reliability_assessment.overall_reliability:.3f}")
print(f"MTBF: {result.reliability_assessment.mtbf_hours:.0f} hours")

# Check for maintenance alerts
for alert in result.reliability_assessment.maintenance_alerts:
    if alert.is_urgent():
        print(f"URGENT: {alert.description}")

# Check failure predictions
for prediction in result.reliability_assessment.failure_predictions:
    if prediction.is_imminent(168):  # Within 1 week
        print(f"FAILURE RISK: {prediction.component} may fail in {prediction.predicted_failure_time_hours:.1f} hours")
```

### Advanced Usage

```python
# Simulate until maintenance is needed
result = dt.simulate_until_maintenance(
    machine_id="your_machine_id",
    max_hours=8760.0  # 1 year maximum
)

# Compare different operating conditions
base_params = {"rotational_speed": 100.0, "feed_rate": 1500.0}
high_speed_params = {"rotational_speed": 180.0, "feed_rate": 1500.0}
high_feed_params = {"rotational_speed": 100.0, "feed_rate": 2500.0}

results = dt.compare_simulations(
    machine_id="your_machine_id",
    hours_list=[500, 1000, 2000],
    operational_params=high_speed_params
)
```

## Wear Modeling

The wear model implements:

- **Archard Wear Equation**: V = k × F × s / H
  - V: Wear volume (mm³)
  - k: Wear coefficient (dimensionless)
  - F: Normal force (N)
  - s: Sliding distance (m)
  - H: Material hardness (Pa)

- **Adhesive Wear**: Material transfer due to bonding
- **Abrasive Wear**: Wear from hard particles or surface asperities

### Wear States Tracked

- Volume loss (mm³)
- Wear depth (mm)
- Surface roughness evolution (μm Ra)
- Equivalent strain accumulation

## Fatigue Modeling

The fatigue model uses:

- **Stress-Life (S-N) Approach**: Based on material S-N curves
- **Mean Stress Correction**: Goodman, Gerber, and Soderberg methods
- **Miner's Rule**: Linear damage accumulation for variable amplitude loading
- **Fatigue Limit**: Endurance limit for steels

### Fatigue States Tracked

- Cycles accumulated
- Damage accumulated (D = Σ ni/Ni)
- Remaining life fraction (1-D)
- Safety status (D < 1.0)

## Reliability Prediction

The predictor combines wear and fatigue data to:

- **Forecast Maintenance**: Recommend inspection/maintenance based on degradation thresholds
- **Predict Failures**: Estimate time to failure for different failure modes
- **Assess System Reliability**: Calculate probability of survival
- **Estimate MTBF**: Mean Time Between Failures based on degradation rates

### Alert Levels

- **Low**: Informational, monitor trend
- **Medium**: Schedule inspection within planned maintenance
- **High**: Recommend action soon, possible performance impact
- **Critical**: Immediate action required to prevent failure

## Integration with Existing Platform

The Digital Twin is designed to work seamlessly with the existing OpenSCAD Autonomous Engineering Platform:

- Uses the same machine configuration format as `app/core/evaluation.py`
- Can consume configurations generated by the platform's design systems
- Outputs can feed back into the planning engine for design improvement
- Compatible with the knowledge system for learning from operational data

### Configuration Format

Machine configurations use dictionaries with the following structure:

```python
config = {
    "spindle": {
        "flight_od": 300.0,        # mm
        "flight_thickness": 12.0,  # mm
        "flight_pitch": 150.0,     # mm
        "shaft_od": 75.0           # mm
    },
    "drum": {
        "drum_id": 1200.0,         # mm
        "wall_thickness": 15.0,    # mm
        "drum_length": 3000.0      # mm
    },
    "frame": {
        "skid_width": 2000.0,      # mm
        "rail_a": 250.0,           # mm
        "rail_b": 150.0,           # mm
        "rail_t": 16.0,            # mm
        "rail_length": 4000.0,     # mm
        "cross_a": 200.0,          # mm
        "cross_b": 100.0,          # mm
        "cross_t": 12.0            # mm
    },
    "compression_rollers": {
        "compression_gap": 25.0,   # mm
        "alignment_tolerance": 0.5 # mm
    },
    "rotational_speed": 120.0,     # rpm
    "feed_rate": 2000.0,           # kg/hr
    "moisture_content": 15.0       # %
}
```

## Physics and Engineering Basis

### Wear Models

- **Archard Wear**: Widely accepted adhesive wear model
- **Hardness Values**: Converts Vickers hardness (HV) to Pascals (1 HV ≈ 9.807 MPa)
- **Surface Evolution**: Models roughness growth with operating time
- **Contact Mechanics**: Simplified contact area estimates for different components

### Fatigue Models

- **S-N Curves**: Basquin's equation for life estimation
- **Mean Stress Correction**: Multiple methods (Goodman conservative, Gerber ductile, Soderberg yield)
- **Cycle Counting**: Simple harmonic assumption (1x per revolution for rotating parts)
- **Damage Accumulation**: Linear Miner's rule for proportional loading

### Reliability Models

- **Component Criticality**: Weighted contribution to system reliability
- **Threshold-Based Alerts**: Engineering judgment based thresholds
- **Failure Rate Prediction**: Based on current degradation rates
- **System Reliability**: Series system assumption (weakest link)

## Limitations and Assumptions

### Current Limitations

1. **Simplified Geometry**: Uses representative dimensions rather than detailed CAD geometry
2. **Homogeneous Materials**: Assumes uniform material properties
3. **Linear Damage**: Uses Miner's rule which has limitations for variable amplitude loading
4. **Isotropic Wear**: Assumes uniform wear distribution
5. **Constant Operating Conditions**: Assumes steady-state operation during simulation periods

### Assumptions Made

1. **Material Properties**: Uses typical steel values when not specified
2. **Loading Conditions**: Simplified force estimates based on operational parameters
3. **Wear Coefficients**: Conservative estimates for poorly lubricated conditions
4. **Surface Finish**: Evolution based on time-based roughness growth
5. **Temperature Effects**: Not currently modeled (isothermal assumption)

## Future Enhancements

### Planned Improvements

1. **Advanced Geometry Integration**: Direct CAD/FEA coupling for accurate stress calculation
2. **Multi-Axial Wear**: More sophisticated wear models for complex contact conditions
3. **Variable Loading History**: Rainflow counting for realistic fatigue damage
4. **Temperature Effects**: Thermal expansion and property variation with temperature
5. **Corrosion Modeling**: Environmental degradation mechanisms
6. **Lubrication Models**: Fluid film lubrication and wear reduction
7. **Uncertainty Quantification**: Probabilistic approaches for confidence bounds
8. **Machine Learning Integration**: Learn wear/fatigue coefficients from operational data

### Integration Roadmap

1. **Phase 1**: Basic Digital Twin with wear/fatigue (Current)
2. **Phase 2**: Integration with planning engine for physics-informed design
3. **Phase 3**: Closed-loop learning from knowledge system
4. **Phase 4**: Real-time synchronization with physical machines
5. **Phase 5**: Fleet-level digital twins for factory-wide optimization

## Validation and Testing

The models are based on established engineering principles:

- **Wear**: Archard wear equation validated across numerous material combinations
- **Fatigue**: S-N curve methods are standard in mechanical design (ISO 6336, etc.)
- **Reliability**: Threshold-based approaches common in condition-based maintenance

Unit tests verify:
- Mathematical correctness of wear/fatigue calculations
- Boundary condition handling (zero loads, infinite life)
- Monotonic degradation with time
- Reasonable numerical ranges for outputs

## Configuration and Customization

### Adjusting Model Parameters

```python
from app.digital_twin import create_default_wear_model, WearParameters

# Create wear model with custom parameters
custom_wear_params = WearParameters(
    k=5e-7,              # Lower wear coefficient (better lubrication)
    H=4e9,               # Harder material (4 GPa)
    adhesive_coefficient=0.03,
    abrasive_coefficient=0.02,
    initial_roughness=0.2,
    roughness_growth_rate=0.0002
)
custom_wear_model = create_default_wear_model(custom_wear_params)

# Use in digital twin
dt = DigitalTwin(wear_model=custom_wear_model)
```

### Material Properties

Specify material properties for fatigue analysis:

```python
material_properties = {
    "spindle_shaft": (600.0, 450.0),   # High strength steel: SUT=600 MPa, SY=450 MPa
    "drum_support": (450.0, 300.0),    # Medium steel
    "frame_member": (500.0, 320.0),    # Structural steel
}
```

## Example Output

After running a simulation, you might see output like:

```
=== SIMULATION RESULTS ===
machine_id: hemp_decorticator_001
simulation_hours: 1000.0
final_reliability: 0.847
mtbf_hours: 3200
critical_components_count: 2
maintenance_alerts_count: 3
urgent_maintenance_count: 0
failure_predictions_count: 1
imminent_failure_count: 0
timestamp: 2026-06-08T14:30:00
success: True

=== RELIABILITY ASSESSMENT ===
Overall Reliability: 0.847
MTBF: 3200 hours
Critical Components: spindle_shaft, drum_inner
Maintenance Alerts: 3
Failure Predictions: 1

Top Maintenance Alerts:
  - [medium] spindle_flights: spindle_flights wear depth: 1.24mm (threshold: 2.00mm)
    Action: Inspect spindle_flights for wear, consider replacement if >2.0mm
    In: 432.5 hours
  - [low] drum_inner: drum_inner wear depth: 0.87mm (threshold: 3.00mm)
    Action: Inspect drum_inner for wear, consider replacement if >3.0mm
    In: 1456.2 hours
  - [medium] frame_member: frame_member fatigue damage: 0.623 (D=0.623)
    Action: Inspect frame_member for cracks, consider design review
    In: 287.3 hours

Failure Predictions:
  - [low] spindle_shaft: spindle_shaft fatigue_failure
    In: 1850.3 hours (prob: 0.423)
```

## API Reference

See the individual module files for detailed API documentation:
- `digital_twin.py` - Main simulation interface
- `machine_representation.py` - Machine configuration APIs
- `wear_model.py` - Wear simulation functions
- `fatigue_model.py` - Fatigue analysis functions
- `reliability_predictor.py` - Prediction and assessment functions

## Dependencies

- Python 3.8+
- Standard library only (math, dataclasses, typing, datetime, logging, copy)
- Compatible with existing platform components:
  - app.core.evaluation (for configuration format)
  - app.physics.* (for detailed physics calculations - future integration)

## License

This component is part of the OpenSCAD Autonomous Engineering Platform.
See the main repository for licensing information.
# app/digital_twin/digital_twin.py
# Main Digital Twin class for time-domain operation simulation

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import copy

# Import our digital twin modules
from .machine_representation import MachineConfiguration, MachineGraph, SpindleComponent, DrumComponent, FrameComponent, CompressionRollerComponent
from .wear_model import WearModel, create_default_wear_model
from .fatigue_model import FatigueModel, create_default_fatigue_model
from .reliability_predictor import ReliabilityPredictor, create_default_reliability_predictor, ReliabilityAssessment

logger = logging.getLogger("engine.digital_twin.digital_twin")


@dataclass
class SimulationResult:
    """Results from a Digital Twin simulation run."""
    machine_id: str
    simulation_hours: float
    final_configuration: MachineConfiguration
    wear_states: Dict[str, Any]
    fatigue_results: Dict[str, Tuple[Any, Any]]
    reliability_assessment: ReliabilityAssessment
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    error_message: Optional[str] = None
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the simulation results."""
        return {
            "machine_id": self.machine_id,
            "simulation_hours": self.simulation_hours,
            "final_reliability": self.reliability_assessment.overall_reliability,
            "mtbf_hours": self.reliability_assessment.mtbf_hours,
            "critical_components_count": len(self.reliability_assessment.critical_components),
            "maintenance_alerts_count": len(self.reliability_assessment.maintenance_alerts),
            "urgent_maintenance_count": len([a for a in self.reliability_assessment.maintenance_alerts if a.is_urgent()]),
            "failure_predictions_count": len(self.reliability_assessment.failure_predictions),
            "imminent_failure_count": len([f for f in self.reliability_assessment.failure_predictions if f.is_imminent()]),
            "timestamp": self.timestamp.isoformat(),
            "success": self.success
        }


class DigitalTwin:
    """
    Digital Twin for simulating machine operation over time.
    Combines machine representation, wear modeling, fatigue analysis, and reliability prediction.
    """
    
    def __init__(
        self,
        machine_graph: Optional[MachineGraph] = None,
        wear_model: Optional[WearModel] = None,
        fatigue_model: Optional[FatigueModel] = None,
        reliability_predictor: Optional[ReliabilityPredictor] = None
    ):
        """
        Initialize the Digital Twin.
        
        Args:
            machine_graph: Machine graph containing configurations
            wear_model: Wear model instance
            fatigue_model: Fatigue model instance  
            reliability_predictor: Reliability predictor instance
        """
        self.machine_graph = machine_graph or MachineGraph()
        self.wear_model = wear_model or create_default_wear_model()
        self.fatigue_model = fatigue_model or create_default_fatigue_model()
        self.reliability_predictor = reliability_predictor or create_default_reliability_predictor()
        
        # Simulation history
        self.simulation_history: List[SimulationResult] = []
        
        logger.info("Initialized DigitalTwin")
    
    def load_machine_configuration(self, config: MachineConfiguration) -> None:
        """
        Load a machine configuration into the Digital Twin.
        """
        self.machine_graph.add_configuration(config)
        logger.info(f"Loaded machine configuration: {config.machine_id}")
    
    def get_machine_configuration(self, machine_id: str) -> Optional[MachineConfiguration]:
        """
        Retrieve a machine configuration by ID.
        """
        return self.machine_graph.get_configuration(machine_id)
    
    def simulate_operation(
        self,
        machine_id: str,
        operating_hours: float,
        operational_params: Optional[Dict[str, Any]] = None,
        material_properties: Optional[Dict[str, Tuple[float, float]]] = None
    ) -> SimulationResult:
        """
        Simulate machine operation for specified hours.
        
        Args:
            machine_id: ID of machine configuration to simulate
            operating_hours: Number of hours to simulate
            operational_params: Optional operational parameters to override (speed, feed rate, etc.)
            material_properties: Optional material properties for components (SUT, SY pairs)
            
        Returns:
            SimulationResult containing wear, fatigue, and reliability analysis
        """
        try:
            logger.info(f"Starting simulation for machine {machine_id} for {operating_hours} hours")
            
            # Get the machine configuration
            base_config = self.get_machine_configuration(machine_id)
            if base_config is None:
                raise ValueError(f"Machine configuration {machine_id} not found")
            
            # Create a working copy of the configuration
            working_config = copy.deepcopy(base_config)
            
            # Apply operational parameters if provided
            if operational_params:
                self.machine_graph.update_configuration(
                    working_config.machine_id, 
                    operational_params
                )
                # Update the working config object
                for key, value in operational_params.items():
                    if hasattr(working_config, key):
                        setattr(working_config, key, value)
                    elif key == "spindle" and isinstance(value, dict):
                        for sk, sv in value.items():
                            if hasattr(working_config.spindle, sk):
                                setattr(working_config.spindle, sk, sv)
                    elif key == "drum" and isinstance(value, dict):
                        for dk, dv in value.items():
                            if hasattr(working_config.drum, dk):
                                setattr(working_config.drum, dk, dv)
                    elif key == "frame" and isinstance(value, dict):
                        for fk, fv in value.items():
                            if hasattr(working_config.frame, fk):
                                setattr(working_config.frame, fk, fv)
                    elif key == "compression_rollers" and isinstance(value, dict):
                        for crk, crv in value.items():
                            if hasattr(working_config.compression_rollers, crk):
                                setattr(working_config.compression_rollers, crk, crv)
            
            # Convert configuration to dictionary for analysis models
            config_dict = working_config.to_dict()
            
            # Add operational parameters to config dict for models
            config_dict.update({
                "rotational_speed": working_config.rotational_speed,
                "feed_rate": working_config.feed_rate,
                "moisture_content": working_config.moisture_content
            })
            
            logger.debug(f"Simulating with config: {config_dict}")
            
            # Simulate wear accumulation
            logger.debug("Simulating wear...")
            spindle_wear = self.wear_model.simulate_spindle_wear(config_dict, operating_hours)
            drum_wear = self.wear_model.simulate_drum_wear(config_dict, operating_hours)
            bearing_wear = self.wear_model.simulate_bearing_wear(config_dict, operating_hours)
            
            # Combine wear states
            wear_states = {
                **spindle_wear,
                **drum_wear,
                **bearing_wear
            }
            
            # Simulate fatigue accumulation
            logger.debug("Simulating fatigue...")
            fatigue_results = self.fatigue_model.simulate_machine_fatigue(
                config_dict, operating_hours, material_properties
            )
            
            # Generate reliability assessment
            logger.debug("Generating reliability assessment...")
            reliability_assessment = self.reliability_predictor.generate_reliability_assessment(
                config_dict, wear_states, fatigue_results, operating_hours
            )
            
            # Create simulation result
            result = SimulationResult(
                machine_id=machine_id,
                simulation_hours=operating_hours,
                final_configuration=working_config,
                wear_states=wear_states,
                fatigue_results=fatigue_results,
                reliability_assessment=reliability_assessment,
                success=True
            )
            
            # Add to history
            self.simulation_history.append(result)
            
            logger.info(f"Simulation completed for {machine_id}. "
                       f"Reliability: {reliability_assessment.overall_reliability:.3f}, "
                       f"MTBF: {reliability_assessment.mtbf_hours:.0f} hours")
            
            return result
            
        except Exception as e:
            logger.error(f"Simulation failed for machine {machine_id}: {e}")
            # Return failed simulation result
            base_config = self.get_machine_configuration(machine_id) or MachineConfiguration(machine_id=machine_id)
            return SimulationResult(
                machine_id=machine_id,
                simulation_hours=operating_hours,
                final_configuration=base_config,
                wear_states={},
                fatigue_results={},
                reliability_assessment=ReliabilityAssessment(
                    overall_reliability=0.0,
                    mtbf_hours=0.0,
                    critical_components=[],
                    maintenance_alerts=[],
                    failure_predictions=[],
                    recommended_maintenance_window=(0.0, 0.0)
                ),
                success=False,
                error_message=str(e)
            )
    
    def simulate_until_maintenance(
        self,
        machine_id: str,
        max_hours: float = 8760.0,  # 1 year default
        operational_params: Optional[Dict[str, Any]] = None,
        material_properties: Optional[Dict[str, Tuple[float, float]]] = None
    ) -> SimulationResult:
        """
        Simulate operation until maintenance is recommended or max hours reached.
        """
        logger.info(f"Simulating {machine_id} until maintenance or {max_hours} hours")
        
        # Start with smaller increments to catch early maintenance needs
        hours_increment = min(100.0, max_hours / 10.0)  # Start with 10% or 100 hours
        hours_simulated = 0.0
        
        while hours_simulated < max_hours:
            # Calculate next increment
            remaining_hours = max_hours - hours_simulated
            current_increment = min(hours_increment, remaining_hours)
            
            # Simulate this increment
            result = self.simulate_operation(
                machine_id, 
                current_increment,
                operational_params,
                material_properties
            )
            
            if not result.success:
                return result
            
            hours_simulated += current_increment
            
            # Check if maintenance is recommended soon
            next_alert = result.reliability_assessment.get_next_maintenance_alert()
            if next_alert and next_alert.estimated_hours_to_action <= 24:  # Within 24 hours
                logger.info(f"Maintenance recommended in {next_alert.estimated_hours_to_action:.1f} hours")
                # Simulate just enough to reach maintenance point
                if next_alert.estimated_hours_to_action > 0:
                    maintenance_result = self.simulate_operation(
                        machine_id,
                        next_alert.estimated_hours_to_action,
                        operational_params,
                        material_properties
                    )
                    return maintenance_result
                break
            
            # Check for imminent failure
            imminent_failure = result.reliability_assessment.get_most_imminent_failure()
            if imminent_failure and imminent_failure.is_imminent(24):  # Within 24 hours
                logger.warning(f"Imminent failure predicted in {imminent_failure.predicted_failure_time_hours:.1f} hours")
                # Simulate to failure point
                if imminent_failure.predicted_failure_time_hours > 0:
                    failure_result = self.simulate_operation(
                        machine_id,
                        imminent_failure.predicted_failure_time_hours,
                        operational_params,
                        material_properties
                    )
                    return failure_result
                break
            
            # If no urgent actions needed, continue with normal increment
            # But reduce increment if we're getting close to limits
            if hours_simolated >= max_hours * 0.8:  # Last 20%
                hours_increment = min(50.0, hours_increment * 0.5)  # Smaller steps near end
        
        # Return final result if we completed all hours
        final_result = self.simulate_operation(
            machine_id,
            max_hours - hours_simulated,
            operational_params,
            material_properties
        ) if hours_simulated < max_hours else self.simulation_history[-1] if self.simulation_history else None
        
        return final_result or self.simulate_operation(machine_id, 0.0, operational_params, material_properties)
    
    def get_simulation_history(self, machine_id: Optional[str] = None) -> List[SimulationResult]:
        """
        Get simulation history, optionally filtered by machine ID.
        """
        if machine_id is None:
            return self.simulation_history.copy()
        return [result for result in self.simulation_history if result.machine_id == machine_id]
    
    def compare_simulations(
        self,
        machine_id: str,
        hours_list: List[float],
        operational_params: Optional[Dict[str, Any]] = None,
        material_properties: Optional[Dict[str, Tuple[float, float]]] = None
    ) -> List[SimulationResult]:
        """
        Run multiple simulations with different operating times for comparison.
        """
        results = []
        for hours in hours_list:
            logger.info(f"Running comparison simulation for {hours} hours")
            result = self.simulate_operation(
                machine_id, hours, operational_params, material_properties
            )
            results.append(result)
        return results
    
    def export_simulation_summary(self, machine_id: str) -> Dict[str, Any]:
        """
        Export a summary of all simulations for a machine.
        """
        history = self.get_simulation_history(machine_id)
        if not history:
            return {"machine_id": machine_id, "simulations": []}
        
        latest = history[-1]
        summary = {
            "machine_id": machine_id,
            "total_simulations": len(history),
            "latest_simulation": latest.get_summary(),
            "reliability_trend": [r.reliability_assessment.overall_reliability for r in history],
            "hours_trend": [r.simulation_hours for r in history],
            "mtbf_trend": [r.reliability_assessment.mtbf_hours for r in history],
        }
        
        return summary


def create_default_digital_twin() -> DigitalTwin:
    """
    Create a Digital Twin with default component models.
    Convenience function for easy instantiation.
    """
    return DigitalTwin(
        machine_graph=MachineGraph(),
        wear_model=create_default_wear_model(),
        fatigue_model=create_default_fatigue_model(),
        reliability_predictor=create_default_reliability_predictor()
    )


# Example usage and testing functions
def create_example_hemp_decotitator_config() -> MachineConfiguration:
    """
    Create an example hemp decorticator configuration for testing.
    Based on typical values from the evaluation system.
    """
    return MachineConfiguration(
        machine_id="hemp_decorticator_001",
        spindle=SpindleComponent(
            flight_od=300.0,      # mm
            flight_thickness=12.0, # mm
            flight_pitch=150.0,   # mm
            shaft_od=75.0,        # mm
            material="steel"
        ),
        drum=DrumComponent(
            drum_id=1200.0,       # mm
            wall_thickness=15.0,  # mm
            drum_length=3000.0,   # mm
            material="steel"
        ),
        frame=FrameComponent(
            skid_width=2000.0,    # mm
            rail_a=250.0,         # mm
            rail_b=150.0,         # mm
            rail_t=16.0,          # mm
            rail_length=4000.0,   # mm
            cross_a=200.0,        # mm
            cross_b=100.0,        # mm
            cross_t=12.0,         # mm
            material="steel"
        ),
        compression_rollers=CompressionRollerComponent(
            compression_gap=25.0, # mm
            alignment_tolerance=0.5, # mm
            roller_diameter=200.0, # mm
            roller_length=1500.0,  # mm
            material="steel"
        ),
        # Operational parameters
        rotational_speed=120.0,   # rpm
        feed_rate=2000.0,         # kg/hr
        moisture_content=15.0,    # percentage
    )


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    # Create digital twin
    dt = create_default_digital_twin()
    
    # Create example machine
    machine_config = create_example_hemp_decotitator_config()
    
    # Load machine into digital twin
    dt.load_machine_configuration(machine_config)
    
    # Run simulation for 1000 hours
    print("Running 1000-hour simulation...")
    result = dt.simulate_operation("hemp_decorticator_001", 1000.0)
    
    # Print summary
    summary = result.get_summary()
    print("\n=== SIMULATION RESULTS ===")
    for key, value in summary.items():
        print(f"{key}: {value}")
    
    # Print reliability assessment details
    print("\n=== RELIABILITY ASSESSMENT ===")
    print(f"Overall Reliability: {result.reliability_assessment.overall_reliability:.3f}")
    print(f"MTBF: {result.reliability_assessment.mtbf_hours:.0f} hours")
    print(f"Critical Components: {', '.join(result.reliability_assessment.critical_components)}")
    print(f"Maintenance Alerts: {len(result.reliability_assessment.maintenance_alerts)}")
    print(f"Failure Predictions: {len(result.reliability_assessment.failure_predictions)}")
    
    if result.reliability_assessment.maintenance_alerts:
        print("\nTop Maintenance Alerts:")
        sorted_alerts = sorted(
            result.reliability_assessment.maintenance_alerts,
            key=lambda a: a.estimated_hours_to_action
        )
        for alert in sorted_alerts[:3]:  # Show top 3
            print(f"  - [{alert.severity}] {alert.component}: {alert.description}")
            print(f"    Action: {alert.recommended_action}")
            print(f"    In: {alert.estimated_hours_to_action:.1f} hours")
    
    if result.reliability_assessment.failure_predictions:
        print("\nFailure Predictions:")
        sorted_predictions = sorted(
            result.reliability_assessment.failure_predictions,
            key=lambda f: f.predicted_failure_time_hours
        )
        for pred in sorted_predictions[:3]:  # Show top 3
            print(f"  - {pred.component}: {pred.failure_mode}")
            print(f"    In: {pred.predicted_failure_time_hours:.1f} hours (prob: {pred.probability:.2f})")
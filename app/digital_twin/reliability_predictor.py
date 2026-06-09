# app/digital_twin/reliability_predictor.py
# Reliability prediction and maintenance forecasting for Digital Twin

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("engine.digital_twin.reliability_predictor")


@dataclass
class MaintenanceAlert:
    """Represents a maintenance alert or recommendation."""
    component: str
    alert_type: str  # "wear", "fatigue", "failure_imminent", "routine"
    severity: str    # "low", "medium", "high", "critical"
    description: str
    recommended_action: str
    estimated_hours_to_action: float
    timestamp: datetime = field(default_factory=datetime.now)
    
    def is_urgent(self) -> bool:
        """Check if alert requires immediate attention."""
        return self.severity in ["high", "critical"] and self.estimated_hours_to_action < 24


@dataclass
class FailurePrediction:
    """Prediction of when a component might fail."""
    component: str
    failure_mode: str  # "wear", "fatigue", "yield", "buckling"
    predicted_failure_time_hours: float  # Hours from now
    probability: float  # 0.0 to 1.0
    confidence: str   # "low", "medium", "high"
    contributing_factors: List[str] = field(default_factory=list)
    
    def is_imminent(self, threshold_hours: float = 168) -> bool:  # 1 week default
        """Check if failure is predicted within threshold hours."""
        return self.predicted_failure_time_hours <= threshold_hours
    
    def severity_level(self) -> str:
        """Get severity based on time to failure."""
        if self.predicted_failure_time_hours <= 24:
            return "critical"
        elif self.predicted_failure_time_hours <= 168:  # 1 week
            return "high"
        elif self.predicted_failure_time_hours <= 720:  # 1 month
            return "medium"
        else:
            return "low"


@dataclass
class ReliabilityAssessment:
    """Overall reliability assessment of a machine."""
    overall_reliability: float  # 0.0 to 1.0 (probability of survival)
    mtbf_hours: float          # Mean Time Between Failures
    critical_components: List[str]
    maintenance_alerts: List[MaintenanceAlert]
    failure_predictions: List[FailurePrediction]
    recommended_maintenance_window: Tuple[float, float]  # (start_hours, end_hours)
    
    def get_next_maintenance_alert(self) -> Optional[MaintenanceAlert]:
        """Get the most urgent maintenance alert."""
        if not self.maintenance_alerts:
            return None
        return min(self.maintenance_alerts, key=lambda a: a.estimated_hours_to_action)
    
    def get_most_imminent_failure(self) -> Optional[FailurePrediction]:
        """Get the failure predicted to occur soonest."""
        if not self.failure_predictions:
            return None
        return min(self.failure_predictions, key=lambda f: f.predicted_failure_time_hours)


class ReliabilityPredictor:
    """
    Predicts reliability, maintenance needs, and failure times for machine components
    based on wear and fatigue accumulation.
    """
    
    def __init__(self):
        logger.debug("Initialized ReliabilityPredictor")
        
        # Wear thresholds (mm) - when maintenance is recommended
        self.wear_thresholds = {
            "spindle_flights": 2.0,      # mm wear depth
            "spindle_shaft": 1.0,
            "drum_inner": 3.0,
            "bearing": 0.5,
        }
        
        # Fatigue damage thresholds
        self.fatigue_thresholds = {
            "maintenance": 0.6,   # Schedule maintenance at 60% damage
            "inspect": 0.8,       # Inspect at 80% damage
            "replace": 0.95,      # Prepare to replace at 95% damage
        }
        
        # Component criticality weights
        self.component_weights = {
            "spindle_shaft": 0.25,
            "spindle_flights": 0.20,
            "drum_support": 0.15,
            "frame_member": 0.15,
            "bearing": 0.10,
            "compression_roller": 0.10,
            "other": 0.05,
        }
    
    def assess_wear_reliability(
        self,
        wear_states: Dict[str, Any],
        operating_hours: float
    ) -> Tuple[List[MaintenanceAlert], List[FailurePrediction]]:
        """
        Assess reliability based on wear states.
        Returns maintenance alerts and failure predictions.
        """
        alerts = []
        predictions = []
        
        # Map wear states to component names
        wear_component_map = {
            "flights": "spindle_flights",
            "shaft": "spindle_shaft",
            "inner_surface": "drum_inner",
            "bearing": "bearing",
        }
        
        for wear_key, wear_state in wear_states.items():
            component_name = wear_component_map.get(wear_key, f"unknown_{wear_key}")
            
            if hasattr(wear_state, 'depth'):
                wear_depth = wear_state.depth
                threshold = self.wear_thresholds.get(component_name, 5.0)  # Default 5mm
                
                # Calculate wear rate (mm/hour)
                if operating_hours > 0:
                    wear_rate = wear_depth / operating_hours
                else:
                    wear_rate = 0.0
                
                # Predict time to reach threshold
                if wear_rate > 0:
                    hours_to_threshold = max(0, (threshold - wear_depth) / wear_rate)
                else:
                    hours_to_threshold = float('inf') if wear_depth < threshold else 0
                
                # Generate maintenance alert if approaching threshold
                if wear_depth > threshold * 0.5:  # Alert at 50% of threshold
                    severity = "low"
                    if wear_depth > threshold * 0.8:
                        severity = "medium"
                    if wear_depth > threshold:
                        severity = "high"
                    
                    alert = MaintenanceAlert(
                        component=component_name,
                        alert_type="wear",
                        severity=severity,
                        description=f"{component_name} wear depth: {wear_depth:.2f}mm (threshold: {threshold:.2f}mm)",
                        recommended_action=f"Inspect {component_name} for wear, consider replacement if >{threshold:.1f}mm",
                        estimated_hours_to_action=max(0, hours_to_threshold - 10),  # Alert 10 hours before threshold
                    )
                    alerts.append(alert)
                
                # Generate failure prediction if wear will cause failure
                if wear_depth >= threshold:
                    # Already exceeded threshold - imminent failure
                    failure_pred = FailurePrediction(
                        component=component_name,
                        failure_mode="excessive_wear",
                        predicted_failure_time_hours=0.0,
                        probability=0.9,
                        confidence="high",
                        contributing_factors=[f"Wear depth {wear_depth:.2f}mm exceeds threshold {threshold:.2f}mm"]
                    )
                    predictions.append(failure_pred)
                elif wear_rate > 0 and hours_to_threshold < 1000:  # Reasonable prediction horizon
                    # Probability increases as we approach threshold
                    prob = min(0.9, wear_depth / threshold) if threshold > 0 else 0.5
                    
                    failure_pred = FailurePrediction(
                        component=component_name,
                        failure_mode="excessive_wear",
                        predicted_failure_time_hours=hours_to_threshold,
                        probability=prob,
                        confidence="medium" if hours_to_threshold < 500 else "low",
                        contributing_factors=[f"Wear rate: {wear_rate:.4f}mm/hour"]
                    )
                    predictions.append(failure_pred)
        
        return alerts, predictions
    
    def assess_fatigue_reliability(
        self,
        fatigue_results: Dict[str, Tuple[Any, Any]],  # (FatigueState, FatigueResult)
        operating_hours: float
    ) -> Tuple[List[MaintenanceAlert], List[FailurePrediction]]:
        """
        Assess reliability based on fatigue states.
        Returns maintenance alerts and failure predictions.
        """
        alerts = []
        predictions = []
        
        for component_name, (fatigue_state, fatigue_result) in fatigue_results.items():
            if fatigue_state is None:
                continue
                
            damage = fatigue_state.damage_accumulated
            
            # Generate maintenance alerts based on damage thresholds
            if damage > self.fatigue_thresholds["maintenance"]:
                severity = "low"
                if damage > self.fatigue_thresholds["inspect"]:
                    severity = "medium"
                if damage > self.fatigue_thresholds["replace"]:
                    severity = "high"
                
                alert = MaintenanceAlert(
                    component=component_name,
                    alert_type="fatigue",
                    severity=severity,
                    description=f"{component_name} fatigue damage: {damage:.3f} (D={damage:.3f})",
                    recommended_action=f"Inspect {component_name} for cracks, consider design review",
                    estimated_hours_to_action=max(0, (self.fatigue_thresholds["replace"] - damage) / max(damage/operating_hours, 0.001)) if operating_hours > 0 else 100,
                )
                alerts.append(alert)
            
            # Generate failure prediction if approaching fatigue limit
            if damage >= self.fatigue_thresholds["replace"]:
                # High probability of fatigue failure
                hours_to_failure = fatigue_state.time_to_failure_at_current_rate(
                    operating_hours / max(damage, 0.001) if damage > 0 else float('inf')
                )
                
                failure_pred = FailurePrediction(
                    component=component_name,
                    failure_mode="fatigue_failure",
                    predicted_failure_time_hours=max(0, hours_to_failure),
                    probability=min(0.95, damage),
                    confidence="high" if damage > 0.9 else "medium",
                    contributing_factors=[f"Fatigue damage D={damage:.3f} approaching limit"]
                )
                predictions.append(failure_pred)
            elif damage > 0.1 and operating_hours > 0:  # Only predict if we have measurable damage
                # Estimate time to failure based on current damage rate
                damage_per_hour = damage / operating_hours
                if damage_per_hour > 0:
                    hours_to_damage_1 = (1.0 - damage) / damage_per_hour
                    
                    # Probability Weibull-like distribution
                    prob = 1.0 - math.exp(-(damage/0.8)**2)  # Increases with damage
                    
                    failure_pred = FailurePrediction(
                        component=component_name,
                        failure_mode="fatigue_failure",
                        predicted_failure_time_hours=max(0, hours_to_damage_1),
                        probability=min(0.9, prob),
                        confidence="medium" if hours_to_damage_1 < 2000 else "low",
                        contributing_factors=[f"Fatigue damage rate: {damage_per_hour:.6f}/hour"]
                    )
                    predictions.append(failure_pred)
        
        return alerts, predictions
    
    def calculate_overall_reliability(
        self,
        wear_states: Dict[str, Any],
        fatigue_results: Dict[str, Tuple[Any, Any]]
    ) -> float:
        """
        Calculate overall system reliability based on component states.
        Returns probability that system survives next operational cycle.
        """
        reliability_factors = []
        
        # Wear-based reliability
        for component_name, wear_state in wear_states.items():
            if hasattr(wear_state, 'depth'):
                # Map to standard component names
                std_name = component_name
                if component_name == "flights":
                    std_name = "spindle_flights"
                elif component_name == "shaft":
                    std_name = "spindle_shaft"
                elif component_name == "inner_surface":
                    std_name = "drum_inner"
                elif component_name == "bearing":
                    std_name = "bearing"
                
                weight = self.component_weights.get(std_name, 0.05)
                threshold = self.wear_thresholds.get(std_name, 5.0)
                
                if threshold > 0:
                    wear_factor = max(0.0, 1.0 - (wear_state.depth / threshold))
                    reliability_factors.append(wear_factor ** weight)  # Weighted contribution
        
        # Fatigue-based reliability
        for component_name, (fatigue_state, _) in fatigue_results.items():
            if fatigue_state is not None:
                weight = self.component_weights.get(component_name, 0.05)
                fatigue_factor = max(0.0, 1.0 - fatigue_state.damage_accumulated)
                reliability_factors.append(fatigue_factor ** weight)
        
        # System reliability is product of component reliabilities (series system)
        if reliability_factors:
            overall_reliability = math.prod(reliability_factors)
        else:
            overall_reliability = 1.0
        
        return max(0.0, min(1.0, overall_reliability))
    
    def estimate_mtbf(
        self,
        wear_states: Dict[str, Any],
        fatigue_results: Dict[str, Tuple[Any, Any]],
        operating_hours: float
    ) -> float:
        """
        Estimate Mean Time Between Failures based on current degradation rates.
        """
        # Collect all failure predictions and calculate weighted MTBF
        wear_alerts, wear_predictions = self.assess_wear_reliability(wear_states, operating_hours)
        fatigue_alerts, fatigue_predictions = self.assess_fatigue_reliability(fatigue_results, operating_hours)
        
        all_predictions = wear_predictions + fatigue_predictions
        
        if not all_predictions:
            # No failures predicted - return high MTBF
            return operating_hours * 10 if operating_hours > 0 else 8760.0  # 1 year if no hours yet
        
        # Calculate harmonic mean of MTBF estimates (conservative)
        failure_rates = []
        for pred in all_predictions:
            if pred.predicted_failure_time_hours > 0 and pred.probability > 0.1:
                # Convert to failure rate (failures per hour)
                # Adjust rate by probability
                adjusted_time = pred.predicted_failure_time_hours / max(pred.probability, 0.1)
                failure_rate = 1.0 / adjusted_time if adjusted_time > 0 else 0
                failure_rates.append(failure_rate)
        
        if failure_rates:
            # System failure rate is sum of component failure rates
            system_failure_rate = sum(failure_rates)
            mtbf = 1.0 / system_failure_rate if system_failure_rate > 0 else float('inf')
            return min(mtbf, 100000.0)  # Cap at reasonable value
        else:
            return 8760.0  # Default 1 year
    
    def generate_reliability_assessment(
        self,
        config_dict: Dict[str, Any],
        wear_states: Dict[str, Any],
        fatigue_results: Dict[str, Tuple[Any, Any]],
        operating_hours: float
    ) -> ReliabilityAssessment:
        """
        Generate a complete reliability assessment for the machine.
        """
        # Get wear-based assessments
        wear_alerts, wear_predictions = self.assess_wear_reliability(wear_states, operating_hours)
        
        # Get fatigue-based assessments
        fatigue_alerts, fatigue_predictions = self.assess_fatigue_reliability(fatigue_results, operating_hours)
        
        # Combine all alerts and predictions
        all_alerts = wear_alerts + fatigue_alerts
        all_predictions = wear_predictions + fatigue_predictions
        
        # Calculate overall reliability
        overall_reliability = self.calculate_overall_reliability(wear_states, fatigue_results)
        
        # Estimate MTBF
        mtbf_hours = self.estimate_mtbf(wear_states, fatigue_results, operating_hours)
        
        # Identify critical components (those with alerts or high predictions)
        critical_components = set()
        for alert in all_alerts:
            if alert.severity in ["high", "critical"]:
                critical_components.add(alert.component)
        for pred in all_predictions:
            if pred.severity_level() in ["high", "critical"]:
                critical_components.add(pred.component)
        
        # Determine recommended maintenance window
        # Look for clusters of maintenance needs in near future
        maintenance_hours = [alert.estimated_hours_to_action for alert in all_alerts if alert.alert_type in ["wear", "fatigue"]]
        if maintenance_hours:
            # Find optimal window - start when first maintenance needed, end when last urgent maintenance needed
            maintenance_hours.sort()
            start_time = max(0, maintenance_hours[0] - 10)  # Start 10 hours before first
            # Find window covering alerts within 100 hours
            end_candidates = [h for h in maintenance_hours if h <= start_time + 100]
            end_time = max(end_candidates) if end_candidates else start_time + 50
        else:
            # No specific maintenance needs - suggest routine check
            start_time = max(100, operating_hours + 50)  # In 50 hours or at 100 hours
            end_time = start_time + 100
        
        return ReliabilityAssessment(
            overall_reliability=overall_reliability,
            mtbf_hours=mtbf_hours,
            critical_components=list(critical_components),
            maintenance_alerts=all_alerts,
            failure_predictions=all_predictions,
            recommended_maintenance_window=(start_time, end_time)
        )


def create_default_reliability_predictor() -> ReliabilityPredictor:
    """Create a reliability predictor with default settings."""
    return ReliabilityPredictor()
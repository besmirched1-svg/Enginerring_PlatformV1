# app/digital_twin/machine_representation.py
# Machine representation and manipulation for Digital Twin

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("engine.digital_twin.machine_representation")


@dataclass
class SpindleComponent:
    """Spindle component representation."""
    flight_od: float = 0.0          # mm - outer diameter of flights
    flight_thickness: float = 0.0   # mm - thickness of flight plate
    flight_pitch: float = 0.0       # mm - distance between flights
    shaft_od: float = 0.0           # mm - outer diameter of shaft
    material: str = "steel"


@dataclass
class DrumComponent:
    """Drum component representation."""
    drum_id: float = 0.0            # mm - inner diameter of drum
    wall_thickness: float = 0.0     # mm - thickness of drum wall
    drum_length: float = 0.0        # mm - length of drum
    material: str = "steel"


@dataclass
class FrameComponent:
    """Frame component representation."""
    skid_width: float = 0.0         # mm - width of skid
    rail_a: float = 0.0             # mm - height of rail rectangle
    rail_b: float = 0.0             # mm - width of rail rectangle  
    rail_t: float = 0.0             # mm - thickness of rail
    rail_length: float = 0.0        # mm - length of rail
    cross_a: float = 0.0            # mm - height of cross-member
    cross_b: float = 0.0            # mm - width of cross-member
    cross_t: float = 0.0            # mm - thickness of cross-member
    material: str = "steel"


@dataclass
class CompressionRollerComponent:
    """Compression roller component representation."""
    compression_gap: float = 0.0    # mm - gap between rollers
    alignment_tolerance: float = 0.0 # mm - alignment tolerance
    roller_diameter: float = 0.0    # mm - diameter of rollers
    roller_length: float = 0.0      # mm - length of rollers
    material: str = "steel"


@dataclass
class MachineConfiguration:
    """Complete machine configuration representing the 'Machine Graph'."""
    spindle: SpindleComponent = field(default_factory=SpindleComponent)
    drum: DrumComponent = field(default_factory=DrumComponent)
    frame: FrameComponent = field(default_factory=FrameComponent)
    compression_rollers: CompressionRollerComponent = field(default_factory=CompressionRollerComponent)
    
    # Operational parameters
    rotational_speed: float = 0.0   # rpm
    feed_rate: float = 0.0          # kg/hr
    moisture_content: float = 0.0   # percentage
    
    # Metadata
    machine_id: str = ""
    timestamp: float = 0.0
    version: str = "1.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format compatible with existing evaluation system."""
        return {
            "spindle": {
                "flight_od": self.spindle.flight_od,
                "flight_thickness": self.spindle.flight_thickness,
                "flight_pitch": self.spindle.flight_pitch,
                "shaft_od": self.spindle.shaft_od,
            },
            "drum": {
                "drum_id": self.drum.drum_id,
                "wall_thickness": self.drum.wall_thickness,
                "drum_length": self.drum.drum_length,
            },
            "frame": {
                "skid_width": self.frame.skid_width,
                "rail_a": self.frame.rail_a,
                "rail_b": self.frame.rail_b,
                "rail_t": self.frame.rail_t,
                "rail_length": self.frame.rail_length,
                "cross_a": self.frame.cross_a,
                "cross_b": self.frame.cross_b,
                "cross_t": self.frame.cross_t,
            },
            "compression_rollers": {
                "compression_gap": self.compression_rollers.compression_gap,
                "alignment_tolerance": self.compression_rollers.alignment_tolerance,
            }
        }
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'MachineConfiguration':
        """Create from dictionary format (e.g., from evaluation system)."""
        spindle_data = config_dict.get("spindle", {})
        drum_data = config_dict.get("drum", {})
        frame_data = config_dict.get("frame", {})
        comp_data = config_dict.get("compression_rollers", {})
        
        return cls(
            spindle=SpindleComponent(
                flight_od=spindle_data.get("flight_od", 0.0),
                flight_thickness=spindle_data.get("flight_thickness", 0.0),
                flight_pitch=spindle_data.get("flight_pitch", 0.0),
                shaft_od=spindle_data.get("shaft_od", 0.0),
            ),
            drum=DrumComponent(
                drum_id=drum_data.get("drum_id", 0.0),
                wall_thickness=drum_data.get("wall_thickness", 0.0),
                drum_length=drum_data.get("drum_length", 0.0),
            ),
            frame=FrameComponent(
                skid_width=frame_data.get("skid_width", 0.0),
                rail_a=frame_data.get("rail_a", 0.0),
                rail_b=frame_data.get("rail_b", 0.0),
                rail_t=frame_data.get("rail_t", 0.0),
                rail_length=frame_data.get("rail_length", 0.0),
                cross_a=frame_data.get("cross_a", 0.0),
                cross_b=frame_data.get("cross_b", 0.0),
                cross_t=frame_data.get("cross_t", 0.0),
            ),
            compression_rollers=CompressionRollerComponent(
                compression_gap=comp_data.get("compression_gap", 0.0),
                alignment_tolerance=comp_data.get("alignment_tolerance", 0.0),
            ),
            rotational_speed=config_dict.get("rotational_speed", 0.0),
            feed_rate=config_dict.get("feed_rate", 0.0),
            moisture_content=config_dict.get("moisture_content", 0.0),
        )


class MachineGraph:
    """
    Represents and manipulates machine configurations (the 'Machine Graph').
    Provides methods for comparing, evolving, and analyzing machine designs.
    """
    
    def __init__(self):
        self.configurations: Dict[str, MachineConfiguration] = {}
        logger.debug("Initialized MachineGraph")
    
    def add_configuration(self, config: MachineConfiguration) -> None:
        """Add a machine configuration to the graph."""
        if not config.machine_id:
            config.machine_id = f"machine_{len(self.configurations)}"
        self.configurations[config.machine_id] = config
        logger.debug(f"Added configuration: {config.machine_id}")
    
    def get_configuration(self, machine_id: str) -> Optional[MachineConfiguration]:
        """Retrieve a machine configuration by ID."""
        return self.configurations.get(machine_id)
    
    def update_configuration(self, machine_id: str, updates: Dict[str, Any]) -> bool:
        """Update a configuration with new values."""
        config = self.get_configuration(machine_id)
        if not config:
            logger.warning(f"Configuration {machine_id} not found")
            return False
            
        # Update simple attributes
        for key, value in updates.items():
            if hasattr(config, key):
                setattr(config, key, value)
            elif key == "spindle" and isinstance(value, dict):
                for sk, sv in value.items():
                    if hasattr(config.spindle, sk):
                        setattr(config.spindle, sk, sv)
            elif key == "drum" and isinstance(value, dict):
                for dk, dv in value.items():
                    if hasattr(config.drum, dk):
                        setattr(config.drum, dk, dv)
            elif key == "frame" and isinstance(value, dict):
                for fk, fv in value.items():
                    if hasattr(config.frame, fk):
                        setattr(config.frame, fk, fv)
            elif key == "compression_rollers" and isinstance(value, dict):
                for crk, crv in value.items():
                    if hasattr(config.compression_rollers, crk):
                        setattr(config.compression_rollers, crk, crv)
        
        logger.debug(f"Updated configuration: {machine_id}")
        return True
    
    def compare_configurations(self, id1: str, id2: str) -> List[str]:
        """Compare two configurations and return list of differences."""
        config1 = self.get_configuration(id1)
        config2 = self.get_configuration(id2)
        
        if not config1 or not config2:
            return ["One or both configurations not found"]
            
        differences = []
        
        # Compare spindle
        spindle_attrs = ["flight_od", "flight_thickness", "flight_pitch", "shaft_od"]
        for attr in spindle_attrs:
            v1 = getattr(config1.spindle, attr)
            v2 = getattr(config2.spindle, attr)
            if abs(v1 - v2) > 0.001:  # Small tolerance for floating point
                differences.append(f"Spindle.{attr}: {v1} vs {v2}")
        
        # Compare drum
        drum_attrs = ["drum_id", "wall_thickness", "drum_length"]
        for attr in drum_attrs:
            v1 = getattr(config1.drum, attr)
            v2 = getattr(config2.drum, attr)
            if abs(v1 - v2) > 0.001:
                differences.append(f"Drum.{attr}: {v1} vs {v2}")
        
        # Compare frame (key attributes)
        frame_attrs = ["skid_width", "rail_a", "rail_b", "rail_t", "rail_length"]
        for attr in frame_attrs:
            v1 = getattr(config1.frame, attr)
            v2 = getattr(config2.frame, attr)
            if abs(v1 - v2) > 0.001:
                differences.append(f"Frame.{attr}: {v1} vs {v2}")
        
        # Compare compression rollers
        comp_attrs = ["compression_gap", "alignment_tolerance"]
        for attr in comp_attrs:
            v1 = getattr(config1.compression_rollers, attr)
            v2 = getattr(config2.compression_rollers, attr)
            if abs(v1 - v2) > 0.001:
                differences.append(f"Compression_Rollers.{attr}: {v1} vs {v2}")
        
        # Compare operational parameters
        op_attrs = ["rotational_speed", "feed_rate", "moisture_content"]
        for attr in op_attrs:
            v1 = getattr(config1, attr)
            v2 = getattr(config2, attr)
            if abs(v1 - v2) > 0.001:
                differences.append(f"Operational.{attr}: {v1} vs {v2}")
                
        return differences
    
    def get_operational_parameters(self, machine_id: str) -> Optional[Dict[str, float]]:
        """Get operational parameters for a machine configuration."""
        config = self.get_configuration(machine_id)
        if not config:
            return None
            
        return {
            "rotational_speed": config.rotational_speed,
            "feed_rate": config.feed_rate,
            "moisture_content": config.moisture_content
        }
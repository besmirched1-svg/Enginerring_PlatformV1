# app/physics/__init__.py
# Physics package initialization

# Import main classes for easy access
from .shafts import ShaftAnalyzer, ShaftGeometry, ShaftLoads, ShaftResults
from .bearings import BearingAnalyzer, BearingGeometry, BearingLoads, BearingResults
from .frames import FrameAnalyzer, FrameMaterial, FrameGeometry, FrameLoads, FrameResults
from .rotors import RotorAnalyzer, RotorGeometry, RotorLoads, RotorResults
from .fatigue import FatigueAnalyzer, FatigueMaterialProperties, FatigueLoading, FatigueResults
from .vibration import VibrationAnalyzer, VibrationSystem, VibrationLoading, VibrationResults

__all__ = [
    # Shafts
    "ShaftAnalyzer",
    "ShaftGeometry", 
    "ShaftLoads",
    "ShaftResults",
    # Bearings
    "BearingAnalyzer",
    "BearingGeometry",
    "BearingLoads",
    "BearingResults",
    # Frames
    "FrameAnalyzer",
    "FrameMaterial",
    "FrameGeometry",
    "FrameLoads",
    "FrameResults",
    # Rotors
    "RotorAnalyzer",
    "RotorGeometry",
    "RotorLoads",
    "RotorResults",
    # Fatigue
    "FatigueAnalyzer",
    "FatigueMaterialProperties",
    "FatigueLoading",
    "FatigueResults",
    # Vibration
    "VibrationAnalyzer",
    "VibrationSystem",
    "VibrationLoading",
    "VibrationResults"
]
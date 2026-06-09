from __future__ import annotations

import itertools
import logging
import math
import random
from typing import Any, Dict, List, Optional

from .models import ExperimentDefinition, ParameterRange, SampleMethod

logger = logging.getLogger("engine.experiment.design_generator")

# Mapping from flat experiment parameter names to nested machine_config paths.
# Each entry: flat_name -> (component, key) where component is the top-level key
# in the nested config, and key is the field within that component.
# For top-level fields, component is None.
FLAT_TO_CONFIG_MAP: Dict[str, tuple] = {
    "drum_diameter":       ("drum", "drum_id"),
    "drum_length":         ("drum", "drum_length"),
    "wall_thickness":      ("drum", "wall_thickness"),
    "flight_thickness":    ("spindle", "flight_thickness"),
    "flight_pitch":        ("spindle", "flight_pitch"),
    "shaft_diameter":      ("spindle", "shaft_od"),
    "shaft_length":        ("spindle", "shaft_length"),
    "number_of_flights":   ("spindle", "number_of_flights"),
    "rotational_speed":    (None, "speed_rpm"),
    "feed_rate":           (None, "feed_rate"),
    "moisture_content":    (None, "moisture_pct"),
    "steel_grade_uts":     (None, "steel_grade_uts"),
    "steel_grade_ys":      (None, "steel_grade_ys"),
    "roller_radius":       (None, "roller_radius"),
    "clearance":           (None, "clearance"),
    "compression_gap":     ("compression_rollers", "compression_gap"),
}

# Default parameter bounds (from multi_objective_optimizer.py)
DEFAULT_PARAM_BOUNDS: Dict[str, tuple] = {
    "drum_diameter":     (800.0, 2000.0),
    "drum_length":       (1000.0, 5000.0),
    "flight_thickness":  (8.0, 25.0),
    "flight_pitch":      (50.0, 300.0),
    "shaft_diameter":    (30.0, 150.0),
    "number_of_flights": (2.0, 12.0),
    "rotational_speed":  (20.0, 200.0),
    "feed_rate":         (500.0, 5000.0),
    "moisture_content":  (5.0, 30.0),
    "steel_grade_uts":   (300.0, 800.0),
    "steel_grade_ys":    (200.0, 500.0),
}


def _latin_hypercube_sample(bounds: Dict[str, tuple], n: int, seed: int = 42) -> List[Dict[str, float]]:
    """Latin Hypercube Sampling over the parameter bounds."""
    rng = random.Random(seed)
    param_names = list(bounds.keys())
    n_params = len(param_names)
    samples = []
    for i in range(n):
        point = {}
        for j, name in enumerate(param_names):
            lo, hi = bounds[name]
            # Stratified sampling: divide [0,1] into n strata
            stratum = (i + rng.random()) / n
            # Shuffle strata per parameter for decorrelation
            shuffled = (j + i * n_params) % n
            val = lo + (hi - lo) * ((shuffled + rng.random()) / n)
            point[name] = round(val, 2)
        samples.append(point)
    return samples


def _sobol_sample(bounds: Dict[str, tuple], n: int) -> List[Dict[str, float]]:
    """Sobol sequence sampling (approximate using Owen-scrambled stratified)."""
    rng = random.Random(42)
    param_names = list(bounds.keys())
    n_params = len(param_names)
    samples = []
    for i in range(n):
        point = {}
        for j, name in enumerate(param_names):
            lo, hi = bounds[name]
            # Simple scrambled Sobol approximation using bit-reversal
            gray = i ^ (i >> 1)
            sobol_frac = ((gray * (j + 1)) % 1000) / 1000.0
            val = lo + (hi - lo) * sobol_frac
            point[name] = round(val, 2)
        samples.append(point)
    return samples


def _grid_sample(bounds: Dict[str, tuple], n: int) -> List[Dict[str, float]]:
    """Grid sampling: distribute n samples as evenly as possible."""
    param_names = list(bounds.keys())
    n_params = len(param_names)
    if n_params == 0:
        return []
    points_per = max(1, int(round(n ** (1.0 / n_params))))
    axes = []
    for name in param_names:
        lo, hi = bounds[name]
        axes.append([round(lo + (hi - lo) * i / max(1, points_per - 1), 2) for i in range(points_per)])
    samples = []
    for combo in itertools.product(*axes):
        samples.append(dict(zip(param_names, combo)))
        if len(samples) >= n:
            break
    return samples


def _random_sample(bounds: Dict[str, tuple], n: int, seed: int = 42) -> List[Dict[str, float]]:
    """Random uniform sampling."""
    rng = random.Random(seed)
    samples = []
    param_names = list(bounds.keys())
    for _ in range(n):
        point = {}
        for name in param_names:
            lo, hi = bounds[name]
            point[name] = round(lo + rng.random() * (hi - lo), 2)
        samples.append(point)
    return samples


def generate_samples(definition: ExperimentDefinition) -> List[Dict[str, float]]:
    """Generate parameter samples according to the experiment definition."""
    bounds: Dict[str, tuple] = {}
    for pr in definition.parameter_ranges:
        bounds[pr.name] = (pr.min_value, pr.max_value)

    if not bounds:
        bounds = dict(DEFAULT_PARAM_BOUNDS)

    n = definition.sample_count

    method = definition.sample_method
    if method == SampleMethod.LATIN_HYPERCUBE:
        return _latin_hypercube_sample(bounds, n)
    elif method == SampleMethod.SOBOL:
        return _sobol_sample(bounds, n)
    elif method == SampleMethod.GRID:
        return _grid_sample(bounds, n)
    else:
        return _random_sample(bounds, n)


def flat_to_nested_config(flat_params: Dict[str, float], machine_type: str = "hemp_roller") -> Dict[str, Any]:
    """Convert flat parameter dict to the nested config structure used by Director.

    Args:
        flat_params: Flat dict of parameter_name -> value
        machine_type: Machine type string

    Returns:
        Nested config dict matching the Director pipeline format.
    """
    config: Dict[str, Any] = {
        "type": machine_type,
        "temperature_c": 20.0,
    }

    # Default sub-structures
    config.setdefault("spindle", {})
    config.setdefault("drum", {})
    config.setdefault("frame", {})
    config.setdefault("compression_rollers", {})

    for flat_name, value in flat_params.items():
        mapping = FLAT_TO_CONFIG_MAP.get(flat_name)
        if mapping is None:
            config[flat_name] = value
        else:
            component, key = mapping
            if component is None:
                config[key] = value
            else:
                if component not in config:
                    config[component] = {}
                config[component][key] = value

    # Fill in sensible defaults for any missing frame fields
    drum_id = config.get("drum", {}).get("drum_id", 1000)
    config["frame"].setdefault("skid_width", drum_id * 3)
    config["frame"].setdefault("rail_length", config.get("drum", {}).get("drum_length", 4000))
    config["frame"].setdefault("rail_a", 200)
    config["frame"].setdefault("rail_b", 100)
    config["frame"].setdefault("rail_t", 9)

    return config

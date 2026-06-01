import pytest
from app.core.mutation import propose_next_config, PARAMETER_BOUNDS, _validate_bounds


class TestParameterValidation:
    """Test the _validate_bounds() helper function."""
    
    def test_validate_bounds_within_range(self):
        """Value within bounds should return unchanged."""
        value, was_clamped = _validate_bounds("wall_thickness", 5.0)
        assert value == 5.0
        assert was_clamped == False
    
    def test_validate_bounds_below_minimum(self):
        """Value below minimum should be clamped to min."""
        value, was_clamped = _validate_bounds("wall_thickness", 0.5)
        assert value == PARAMETER_BOUNDS["wall_thickness"]["min"]
        assert was_clamped == True
    
    def test_validate_bounds_above_maximum(self):
        """Value above maximum should be clamped to max."""
        value, was_clamped = _validate_bounds("wall_thickness", 20.0)
        assert value == PARAMETER_BOUNDS["wall_thickness"]["max"]
        assert was_clamped == True
    
    def test_validate_bounds_unknown_parameter(self):
        """Unknown parameter should return value unchanged."""
        value, was_clamped = _validate_bounds("unknown_param", 100.0)
        assert value == 100.0
        assert was_clamped == False


class TestMutationEdgeCases:
    """Test mutation engine with extreme and edge case inputs."""
    
    def test_mutation_with_zero_score(self):
        """Mutation should handle zero score (maximum error)."""
        config = {"wall_thickness": 3.0, "roller_radius": 30.0, "clearance": 0.5}
        eval_result = {
            "issues": ["wall_thickness_insufficient"],
            "metrics": {"structural_stability": 0.1},
            "score": 0.0,
        }
        
        next_config = propose_next_config(config, eval_result)
        
        # Should produce valid output
        assert next_config is not None
        assert isinstance(next_config, dict)
        # Should increase thickness (zero score = critical failure)
        assert next_config["wall_thickness"] > config["wall_thickness"]
    
    def test_mutation_with_perfect_score(self):
        """Mutation should handle perfect score (no improvement needed)."""
        config = {"wall_thickness": 5.0, "roller_radius": 35.0, "clearance": 0.8}
        eval_result = {
            "issues": [],
            "metrics": {"structural_stability": 1.0, "material_efficiency": 1.0},
            "score": 1.0,
        }
        
        next_config = propose_next_config(config, eval_result)
        
        # Should produce output (even if minimal changes)
        assert next_config is not None
        assert isinstance(next_config, dict)
    
    def test_mutation_all_signals_active(self):
        """Mutation should handle all failure signals simultaneously."""
        config = {"wall_thickness": 3.0, "roller_radius": 30.0, "clearance": 0.5}
        eval_result = {
            "issues": [
                "wall_thickness_insufficient",
                "material_inefficient",
                "clearance_binding",
            ],
            "metrics": {
                "structural_stability": 0.3,
                "material_efficiency": 0.2,
            },
            "score": 0.25,
        }
        
        next_config = propose_next_config(config, eval_result)
        
        # Should process first applicable signal (wall_thickness_insufficient takes precedence)
        assert next_config is not None
        # Should increase thickness due to structural issue
        assert next_config["wall_thickness"] > config["wall_thickness"]
    
    def test_mutation_never_escapes_min_bounds(self):
        """Even extreme inputs shouldn't violate minimum bounds."""
        config = {
            "wall_thickness": 1.5,  # At minimum
            "roller_radius": 15.0,  # At minimum
            "clearance": 0.2,       # At minimum
        }
        eval_result = {
            "issues": ["material_inefficient"],  # Try to reduce further
            "metrics": {"material_efficiency": 0.1},
            "score": 0.1,
        }
        
        next_config = propose_next_config(config, eval_result)
        
        # Should never go below bounds
        assert next_config["wall_thickness"] >= PARAMETER_BOUNDS["wall_thickness"]["min"]
        assert next_config["roller_radius"] >= PARAMETER_BOUNDS["roller_radius"]["min"]
        assert next_config["clearance"] >= PARAMETER_BOUNDS["clearance"]["min"]
    
    def test_mutation_never_escapes_max_bounds(self):
        """Even extreme inputs shouldn't violate maximum bounds."""
        config = {
            "wall_thickness": 15.0,  # At maximum
            "roller_radius": 80.0,   # At maximum
            "clearance": 3.0,        # At maximum
        }
        eval_result = {
            "issues": ["wall_thickness_insufficient"],  # Try to increase further
            "metrics": {"structural_stability": 0.1},
            "score": 0.1,
        }
        
        next_config = propose_next_config(config, eval_result)
        
        # Should never exceed bounds
        assert next_config["wall_thickness"] <= PARAMETER_BOUNDS["wall_thickness"]["max"]
        assert next_config["roller_radius"] <= PARAMETER_BOUNDS["roller_radius"]["max"]
        assert next_config["clearance"] <= PARAMETER_BOUNDS["clearance"]["max"]
    
    def test_mutation_with_invalid_score_above_one(self):
        """Mutation should handle invalid score values gracefully."""
        config = {"wall_thickness": 3.0, "roller_radius": 30.0, "clearance": 0.5}
        eval_result = {
            "issues": [],
            "metrics": {},
            "score": 1.5,  # Invalid: exceeds 1.0
        }
        
        # Should not raise; should clamp internally
        next_config = propose_next_config(config, eval_result)
        assert next_config is not None
    
    def test_mutation_with_invalid_score_negative(self):
        """Mutation should handle negative scores gracefully."""
        config = {"wall_thickness": 3.0, "roller_radius": 30.0, "clearance": 0.5}
        eval_result = {
            "issues": [],
            "metrics": {},
            "score": -0.5,  # Invalid: negative
        }
        
        # Should not raise; should clamp internally
        next_config = propose_next_config(config, eval_result)
        assert next_config is not None
    
    def test_mutation_preserves_unmodified_keys(self):
        """Mutation should not lose config keys."""
        config = {
            "wall_thickness": 3.0,
            "roller_radius": 30.0,
            "clearance": 0.5,
            "custom_key": "custom_value",
        }
        eval_result = {
            "issues": ["wall_thickness_insufficient"],
            "metrics": {"structural_stability": 0.3},
            "score": 0.25,
        }
        
        next_config = propose_next_config(config, eval_result)
        
        # Should keep standard keys
        assert "wall_thickness" in next_config
        assert "roller_radius" in next_config
        assert "clearance" in next_config


class TestMutationDeterminism:
    """Test that mutations are deterministic."""
    
    def test_mutation_is_deterministic(self):
        """Same input should produce same output."""
        config = {"wall_thickness": 3.0, "roller_radius": 30.0, "clearance": 0.5}
        eval_result = {
            "issues": ["wall_thickness_insufficient"],
            "metrics": {"structural_stability": 0.3},
            "score": 0.25,
        }
        
        result1 = propose_next_config(config, eval_result)
        result2 = propose_next_config(config, eval_result)
        
        # Both results should be identical
        assert result1 == result2


class TestParameterBounds:
    """Test that PARAMETER_BOUNDS constant is properly defined."""
    
    def test_parameter_bounds_defined(self):
        """All critical parameters should have bounds defined."""
        critical_params = ["wall_thickness", "roller_radius", "clearance"]
        for param in critical_params:
            assert param in PARAMETER_BOUNDS
            assert "min" in PARAMETER_BOUNDS[param]
            assert "max" in PARAMETER_BOUNDS[param]
    
    def test_parameter_bounds_min_less_than_max(self):
        """For each parameter, min should be less than max."""
        for param_name, bounds in PARAMETER_BOUNDS.items():
            assert bounds["min"] < bounds["max"], \
                f"{param_name}: min ({bounds['min']}) >= max ({bounds['max']})"
    
    def test_parameter_bounds_are_positive(self):
        """All bounds should be positive (physical measurements)."""
        for param_name, bounds in PARAMETER_BOUNDS.items():
            assert bounds["min"] > 0, f"{param_name}: min bound must be positive"
            assert bounds["max"] > 0, f"{param_name}: max bound must be positive"

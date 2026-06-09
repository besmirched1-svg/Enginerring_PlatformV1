"""Tests for app/core/evaluation.py — the 6-metric scoring engine."""
import pytest
from app.core.evaluation import (
    evaluate_build,
    total_mass_from_bom_rows,
    IMPROVEMENT_THRESHOLD,
    _design_cache,
    _make_cache_key,
)


class TestEvaluateBuild:
    """evaluate_build() returns a well-formed result dict."""

    def _run(self, config=None, mass=None):
        return evaluate_build(config or {}, mass)

    def test_returns_required_keys(self):
        result = self._run()
        assert "composite" in result
        assert "needs_improvement" in result
        assert "metrics" in result
        assert "all_issues" in result

    def test_composite_in_range(self):
        result = self._run()
        assert 0.0 <= result["composite"] <= 1.0

    def test_needs_improvement_flag_below_threshold(self):
        # Empty config → low scores → needs_improvement should be True
        result = self._run()
        assert result["needs_improvement"] == (result["composite"] < IMPROVEMENT_THRESHOLD)

    def test_six_metrics_present(self):
        result = self._run()
        expected = {
            "structural_validity",
            "manufacturability",
            "material_efficiency",
            "performance_heuristics",
            "failure_risk",
            "constraint_compliance",
        }
        assert expected == set(result["metrics"].keys())

    def test_each_metric_has_score_and_issues(self):
        result = self._run()
        for name, m in result["metrics"].items():
            assert "score" in m, f"{name} missing score"
            assert "issues" in m, f"{name} missing issues"
            assert 0.0 <= m["score"] <= 1.0, f"{name} score out of range"

    def test_deterministic(self):
        config = {
            "drum": {"drum_id": 1500, "drum_length": 4000, "wall_thickness": 8},
            "spindle": {"shaft_od": 260, "flight_od": 600},
        }
        r1 = evaluate_build(config, 5000.0)
        r2 = evaluate_build(config, 5000.0)
        assert r1["composite"] == r2["composite"]

    def test_spindle_drum_interference_penalised(self):
        """flight_od > drum_id should tank structural_validity."""
        config = {
            "drum": {"drum_id": 500, "wall_thickness": 8},
            "spindle": {"flight_od": 600, "shaft_od": 260},
        }
        result = evaluate_build(config)
        sv = result["metrics"]["structural_validity"]["score"]
        assert sv < 0.5, "Interference should heavily penalise structural_validity"

    def test_good_htds_config_scores_well(self):
        """A well-proportioned HTDS-P2 config should score above threshold."""
        config = {
            "drum": {
                "drum_id": 1500,
                "drum_length": 4500,   # L/D = 3.0 — ideal
                "wall_thickness": 8,
            },
            "spindle": {
                "shaft_od": 260,
                "flight_od": 600,
                "flight_pitch": 400,
                "flight_thickness": 25,
            },
            "frame": {
                "rail_length": 5000,
                "rail_a": 250,
                "rail_b": 150,
                "rail_t": 10,
                "skid_width": 1800,
                "cross_a": 150,
                "cross_b": 100,
                "cross_t": 8,
                "cross_count": 5,
            },
        }
        result = evaluate_build(config, 7500.0)
        assert result["composite"] >= 0.55, (
            f"Good HTDS config scored too low: {result['composite']}"
        )

    def test_negative_compression_gap_penalised(self):
        config = {"compression_rollers": {"compression_gap": -5}}
        result = evaluate_build(config)
        cc = result["metrics"]["constraint_compliance"]["score"]
        assert cc < 1.0

    def test_zero_compression_gap_flagged(self):
        config = {"compression_rollers": {"compression_gap": 0}}
        result = evaluate_build(config)
        issues = result["metrics"]["constraint_compliance"]["issues"]
        assert any("compression_gap=0" in i for i in issues)


class TestTotalMassFromBomRows:
    def test_empty_bom_returns_zero(self):
        assert total_mass_from_bom_rows([]) == 0.0

    def test_known_spindle_mass_positive(self):
        rows = [{"part": "Spindle", "config": {}}]
        mass = total_mass_from_bom_rows(rows)
        assert mass > 0

    def test_known_drum_mass_positive(self):
        rows = [{"part": "Drum", "config": {}}]
        mass = total_mass_from_bom_rows(rows)
        assert mass > 0

    def test_unknown_part_skipped_gracefully(self):
        rows = [{"part": "UnknownWidget", "config": {}}]
        mass = total_mass_from_bom_rows(rows)
        assert mass == 0.0

    def test_multiple_parts_sum(self):
        rows = [
            {"part": "Spindle", "config": {}},
            {"part": "Drum", "config": {}},
        ]
        total = total_mass_from_bom_rows(rows)
        spindle = total_mass_from_bom_rows([{"part": "Spindle", "config": {}}])
        drum = total_mass_from_bom_rows([{"part": "Drum", "config": {}}])
        assert abs(total - (spindle + drum)) < 0.01


class TestDesignCache:
    """Test the design caching feature (Fix #5)."""

    def test_cache_hit_returns_cached_flag(self):
        """Second call with same config should return cached=True."""
        config = {"spindle": {"flight_od": 400, "shaft_od": 200, "flight_pitch": 600, "flight_thickness": 10}, "drum": {"drum_id": 600, "drum_length": 2000, "wall_thickness": 8}, "frame": {"rail_a": 200, "rail_b": 100, "rail_t": 9, "skid_width": 1800, "cross_a": 150, "cross_b": 100, "cross_t": 8, "rail_length": 5000}}
        _design_cache.clear()
        r1 = evaluate_build(config, 5000.0)
        r2 = evaluate_build(config, 5000.0)
        assert r1["cached"] is False
        assert r2["cached"] is True
        assert r1["composite"] == r2["composite"]

    def test_cache_miss_different_config(self):
        """Different configs should produce cache miss."""
        _design_cache.clear()
        c1 = {"spindle": {"flight_od": 400}}
        c2 = {"spindle": {"flight_od": 500}}
        r1 = evaluate_build(c1)
        r2 = evaluate_build(c2)
        assert r1["cached"] is False
        assert r2["cached"] is False

    def test_cache_key_includes_mass(self):
        """Same config but different mass should be different cache entries."""
        _design_cache.clear()
        config = {"spindle": {"flight_od": 400}}
        r1 = evaluate_build(config, 1000.0)
        r2 = evaluate_build(config, 2000.0)
        assert r1["cached"] is False
        assert r2["cached"] is False

    def test_cache_key_is_string(self):
        key = _make_cache_key({"a": 1}, 100.0)
        assert isinstance(key, str)
        assert len(key) == 64  # SHA-256 hex

    def test_cache_eviction(self):
        """Cache should evict oldest entries when over limit."""
        from app.core.evaluation import _MAX_CACHE
        _design_cache.clear()
        for i in range(_MAX_CACHE + 10):
            cfg = {"spindle": {"flight_od": float(400 + i)}}
            evaluate_build(cfg)
        assert len(_design_cache) <= _MAX_CACHE

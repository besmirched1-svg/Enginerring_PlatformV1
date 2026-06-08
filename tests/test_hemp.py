"""Tests for app/domain/hemp/ — hemp decorticator domain intelligence."""
import pytest
from app.domain.hemp.models import HempProcessConditions, HempPerformanceResult
from app.domain.hemp.evaluator import evaluate_hemp_performance


class TestHempProcessConditions:
    def test_defaults_valid(self):
        c = HempProcessConditions()
        assert 0 < c.moisture_content_pct < 100
        assert c.feed_rate_kg_hr > 0
        assert c.drum_rpm > 0

    def test_custom_conditions(self):
        c = HempProcessConditions(moisture_content_pct=18.0, drum_rpm=20.0)
        assert c.moisture_content_pct == 18.0
        assert c.drum_rpm == 20.0


class TestHempEvaluator:
    def _good_config(self):
        return {
            "drum": {"drum_id": 1500, "drum_length": 4500, "wall_thickness": 8,
                     "material": "stainless_304"},
            "spindle": {"shaft_od": 260, "flight_od": 600, "shaft_length": 4200},
            "compression_rollers": {"compression_gap": 12},
        }

    def test_returns_performance_result(self):
        result = evaluate_hemp_performance(self._good_config(), HempProcessConditions())
        assert isinstance(result, HempPerformanceResult)

    def test_composite_score_in_range(self):
        result = evaluate_hemp_performance(self._good_config(), HempProcessConditions())
        assert 0.0 <= result.composite_score <= 1.0

    def test_good_config_high_recovery(self):
        result = evaluate_hemp_performance(self._good_config(), HempProcessConditions())
        assert result.fibre_recovery_pct > 70.0

    def test_short_drum_penalised(self):
        config = {"drum": {"drum_id": 1500, "drum_length": 1000}}  # L/D = 0.67
        result = evaluate_hemp_performance(config, HempProcessConditions())
        # Issue must be flagged; score may still be reasonable due to other metrics
        assert any("too short" in i for i in result.issues)

    def test_tight_gap_flagged(self):
        config = {"drum": {"drum_id": 1500, "drum_length": 4500},
                  "compression_rollers": {"compression_gap": 2}}
        result = evaluate_hemp_performance(config, HempProcessConditions())
        assert any("tight" in i.lower() for i in result.issues)

    def test_high_moisture_flagged(self):
        result = evaluate_hemp_performance(
            self._good_config(),
            HempProcessConditions(moisture_content_pct=25.0),
        )
        assert any("moisture" in i.lower() for i in result.issues)

    def test_throughput_positive(self):
        result = evaluate_hemp_performance(self._good_config(), HempProcessConditions())
        assert result.throughput_kg_hr > 0

    def test_power_draw_positive(self):
        result = evaluate_hemp_performance(self._good_config(), HempProcessConditions())
        assert result.power_draw_kw > 0

    def test_to_dict_complete(self):
        result = evaluate_hemp_performance(self._good_config(), HempProcessConditions())
        d = result.to_dict()
        required = {"fibre_recovery_pct", "fibre_quality_score", "throughput_kg_hr",
                    "power_draw_kw", "composite_score", "issues"}
        assert required.issubset(d.keys())

    def test_deterministic(self):
        config = self._good_config()
        cond = HempProcessConditions()
        r1 = evaluate_hemp_performance(config, cond)
        r2 = evaluate_hemp_performance(config, cond)
        assert r1.composite_score == r2.composite_score

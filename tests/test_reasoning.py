"""Tests for Knowledge Reasoning package (Phase 13)."""

import tempfile

import pytest

from app.reasoning import (
    OutcomeRecord,
    ParameterCorrelation,
    RangePattern,
    EngineeringRule,
    Recommendation,
    AdaptiveMutationStrategy,
    ReasoningReport,
    wilson_lower_bound,
    sample_confidence,
    correlation_confidence,
    normalize_outcomes,
    mine_correlations,
    mine_range_patterns,
    extract_rules,
    recommend,
    build_adaptive_strategy,
    adaptive_mutate,
    KnowledgeReasoner,
    reason_over_store,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def records():
    """Synthetic outcomes where high wall_thickness => high score.

    score rises roughly linearly with wall_thickness (3..12), so the top range
    is a strong success region and the bottom range a failure region.
    roller_radius is uncorrelated noise.
    """
    recs = []
    radii = [20, 60, 30, 70, 40, 50, 25, 65, 35, 55]
    for i in range(40):
        wall = 3.0 + (i % 10)             # 3..12
        score = min(1.0, 0.25 + (wall - 3) / 9.0 * 0.7)  # 0.25..0.95
        recs.append(OutcomeRecord(
            parameters={"wall_thickness": wall, "roller_radius": radii[i % len(radii)]},
            score=score,
            outcome_id=f"o{i}",
            success=score >= 0.7,
        ))
    return recs


# ===================================================================
# Confidence
# ===================================================================

class TestConfidence:
    def test_wilson_empty(self):
        assert wilson_lower_bound(0, 0) == 0.0

    def test_wilson_perfect_small_sample_is_discounted(self):
        # 3/3 should be well below 1.0 due to uncertainty
        lb = wilson_lower_bound(3, 3)
        assert 0.0 < lb < 0.7

    def test_wilson_grows_with_sample(self):
        small = wilson_lower_bound(8, 10)
        large = wilson_lower_bound(80, 100)
        assert large > small

    def test_wilson_clamps_successes(self):
        assert wilson_lower_bound(15, 10) == wilson_lower_bound(10, 10)

    def test_sample_confidence(self):
        assert sample_confidence(0) == 0.0
        assert sample_confidence(30) == 1.0
        assert sample_confidence(60) == 1.0
        assert 0 < sample_confidence(15) < 1.0

    def test_correlation_confidence(self):
        assert correlation_confidence(0.0, 100) == 0.0
        c = correlation_confidence(0.8, 30)
        assert c == pytest.approx(0.8)


# ===================================================================
# Normalisation
# ===================================================================

class TestNormalize:
    def test_normalize_store_entries(self):
        raw = [{"id": "x", "data": {"parameters": {"a": 1.0}, "score": 0.8}}]
        recs = normalize_outcomes(raw)
        assert len(recs) == 1
        assert recs[0].parameters == {"a": 1.0}
        assert recs[0].success is True
        assert recs[0].outcome_id == "x"

    def test_normalize_flat_entries(self):
        raw = [{"parameters": {"a": 1.0}, "score": 0.5}]
        recs = normalize_outcomes(raw)
        assert recs[0].success is False

    def test_normalize_drops_nonnumeric(self):
        raw = [{"data": {"parameters": {"a": "bad", "b": 2}, "score": 0.9}}]
        recs = normalize_outcomes(raw)
        assert "a" not in recs[0].parameters
        assert recs[0].parameters["b"] == 2.0

    def test_threshold(self):
        raw = [{"parameters": {}, "score": 0.65}]
        assert normalize_outcomes(raw, success_threshold=0.6)[0].success is True
        assert normalize_outcomes(raw, success_threshold=0.7)[0].success is False


# ===================================================================
# Correlations
# ===================================================================

class TestCorrelations:
    def test_detects_positive_correlation(self, records):
        cors = mine_correlations(records)
        wall = next(c for c in cors if c.parameter == "wall_thickness")
        assert wall.correlation > 0.8
        assert wall.direction == "increases"
        assert wall.confidence > 0

    def test_noise_is_weakly_correlated(self, records):
        cors = mine_correlations(records)
        radius = next(c for c in cors if c.parameter == "roller_radius")
        assert abs(radius.correlation) < 0.5

    def test_sorted_by_abs_correlation(self, records):
        cors = mine_correlations(records)
        abs_vals = [abs(c.correlation) for c in cors]
        assert abs_vals == sorted(abs_vals, reverse=True)

    def test_min_samples(self):
        recs = [OutcomeRecord(parameters={"a": 1.0}, score=0.5)]
        assert mine_correlations(recs, min_samples=3) == []

    def test_zero_variance(self):
        recs = [OutcomeRecord(parameters={"a": 5.0}, score=s / 10) for s in range(5)]
        cors = mine_correlations(recs)
        # constant parameter -> zero correlation (no crash)
        if cors:
            assert cors[0].correlation == 0.0


# ===================================================================
# Range patterns
# ===================================================================

class TestRangePatterns:
    def test_finds_high_success_range(self, records):
        patterns = mine_range_patterns(records, bins=3)
        assert patterns
        # the top pattern should be a high wall_thickness band with high success
        top = patterns[0]
        assert top.success_rate >= 0.5
        assert top.confidence > 0

    def test_high_wall_more_successful_than_low(self, records):
        patterns = [p for p in mine_range_patterns(records, bins=3)
                    if p.parameter == "wall_thickness"]
        patterns.sort(key=lambda p: p.low)
        assert patterns[0].success_rate < patterns[-1].success_rate

    def test_to_dict(self, records):
        d = mine_range_patterns(records)[0].to_dict()
        assert "success_rate" in d and "confidence" in d

    def test_empty(self):
        assert mine_range_patterns([]) == []


# ===================================================================
# Rule extraction
# ===================================================================

class TestRuleExtraction:
    def test_extracts_success_rule(self, records):
        rules = extract_rules(records, bins=3)
        assert rules
        success_rules = [r for r in rules if r.consequent == "success"]
        assert success_rules
        r = success_rules[0]
        assert r.parameter == "wall_thickness"
        assert r.lift >= 1.0
        assert 0 < r.confidence <= 1.0
        assert "wall_thickness" in r.description

    def test_lift_above_one_for_kept_rules(self, records):
        rules = extract_rules(records, bins=3, min_lift=1.05)
        assert all(r.lift >= 1.05 for r in rules)

    def test_empty_records(self):
        assert extract_rules([]) == []

    def test_high_confidence_threshold_filters(self, records):
        strict = extract_rules(records, bins=3, min_confidence=0.99)
        lenient = extract_rules(records, bins=3, min_confidence=0.5)
        assert len(strict) <= len(lenient)


# ===================================================================
# Recommendations
# ===================================================================

class TestRecommendation:
    def test_recommends_increase_for_low_wall(self, records):
        reasoner = KnowledgeReasoner(records)
        recs = reasoner.recommend({"wall_thickness": 3.0})
        wall_rec = next((r for r in recs if r.parameter == "wall_thickness"), None)
        assert wall_rec is not None
        assert wall_rec.action in ("increase", "set")
        assert wall_rec.suggested_value > 3.0

    def test_keep_when_already_in_range(self, records):
        reasoner = KnowledgeReasoner(records)
        recs = reasoner.recommend({"wall_thickness": 11.5})
        wall_rec = next((r for r in recs if r.parameter == "wall_thickness"), None)
        assert wall_rec is not None
        assert wall_rec.action == "keep"

    def test_sorted_by_confidence(self, records):
        reasoner = KnowledgeReasoner(records)
        recs = reasoner.recommend({"wall_thickness": 3.0})
        confs = [r.confidence for r in recs]
        assert confs == sorted(confs, reverse=True)

    def test_no_rules_no_recs(self):
        assert recommend({"a": 1.0}, []) == []


# ===================================================================
# Adaptive mutation
# ===================================================================

class TestAdaptiveMutation:
    def test_strategy_targets_high_success_range(self, records):
        strat = build_adaptive_strategy(records, bins=3)
        assert "wall_thickness" in strat.parameters
        ps = strat.parameters["wall_thickness"]
        # target should sit in the upper part of the 3..12 range
        assert ps.target_value > 7.0
        assert 0 <= ps.exploration_scale <= 1.0

    def test_strategy_respects_bounds(self, records):
        bounds = {"wall_thickness": {"min": 1.5, "max": 9.0}}
        strat = build_adaptive_strategy(records, bounds=bounds, bins=3)
        ps = strat.parameters["wall_thickness"]
        assert ps.recommended_high <= 9.0
        assert ps.recommended_low >= 1.5

    def test_adaptive_mutate_pulls_toward_target(self, records):
        strat = build_adaptive_strategy(records, bins=3)
        target = strat.parameters["wall_thickness"].target_value
        # start far below target, no noise (zero exploration via deterministic seed)
        start = {"wall_thickness": 3.0}
        out = adaptive_mutate(start, strat, pull_strength=1.0, seed=1)
        # with full pull, result should be much closer to target than start
        assert abs(out["wall_thickness"] - target) < abs(start["wall_thickness"] - target)

    def test_adaptive_mutate_deterministic(self, records):
        strat = build_adaptive_strategy(records, bins=3)
        a = adaptive_mutate({"wall_thickness": 4.0}, strat, seed=42)
        b = adaptive_mutate({"wall_thickness": 4.0}, strat, seed=42)
        assert a == b

    def test_adaptive_mutate_clamps_to_bounds(self, records):
        bounds = {"wall_thickness": {"min": 1.5, "max": 15.0}}
        strat = build_adaptive_strategy(records, bounds=bounds, bins=3)
        for seed in range(20):
            out = adaptive_mutate({"wall_thickness": 12.0}, strat, bounds=bounds, seed=seed)
            assert 1.5 <= out["wall_thickness"] <= 15.0

    def test_empty_records_strategy(self):
        strat = build_adaptive_strategy([])
        assert strat.parameters == {}
        assert strat.notes


# ===================================================================
# Engine orchestration
# ===================================================================

class TestKnowledgeReasoner:
    def test_analyze(self, records):
        report = KnowledgeReasoner(records).analyze()
        assert isinstance(report, ReasoningReport)
        assert report.sample_count == 40
        assert report.correlations
        assert report.rules
        assert 0 <= report.success_rate <= 1.0

    def test_analyze_empty(self):
        report = KnowledgeReasoner([]).analyze()
        assert report.sample_count == 0
        assert report.notes

    def test_to_dict(self, records):
        d = KnowledgeReasoner(records).analyze().to_dict()
        assert set(d.keys()) == {
            "correlations", "patterns", "rules", "sample_count", "success_rate", "notes"
        }

    def test_from_store(self, records):
        from app.knowledge.knowledge_store import KnowledgeStore
        with tempfile.TemporaryDirectory() as d:
            store = KnowledgeStore(storage_path=d)
            for r in records:
                store.add_design_outcome({"parameters": r.parameters, "score": r.score})
            reasoner = KnowledgeReasoner.from_store(store)
            assert len(reasoner.records) == 40
            report = reasoner.analyze()
            assert report.rules

    def test_reason_over_store_convenience(self, records):
        from app.knowledge.knowledge_store import KnowledgeStore
        with tempfile.TemporaryDirectory() as d:
            store = KnowledgeStore(storage_path=d)
            for r in records:
                store.add_design_outcome({"parameters": r.parameters, "score": r.score})
            report = reason_over_store(store)
            assert report.sample_count == 40


# ===================================================================
# API
# ===================================================================

class TestReasoningAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    @pytest.fixture
    def payload_outcomes(self, records):
        return [{"parameters": r.parameters, "score": r.score} for r in records]

    def test_analyze_endpoint(self, client, payload_outcomes):
        r = client.post("/api/reasoning/analyze", json={"outcomes": payload_outcomes, "bins": 3})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["report"]["sample_count"] == 40
        assert body["report"]["rules"]

    def test_recommend_endpoint(self, client, payload_outcomes):
        r = client.post("/api/reasoning/recommend", json={
            "outcomes": payload_outcomes,
            "current_parameters": {"wall_thickness": 3.0},
            "bins": 3,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        params = [rec["parameter"] for rec in body["recommendations"]]
        assert "wall_thickness" in params

    def test_strategy_endpoint(self, client, payload_outcomes):
        r = client.post("/api/reasoning/strategy", json={
            "outcomes": payload_outcomes,
            "bounds": {"wall_thickness": {"min": 1.5, "max": 15.0}},
            "bins": 3,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "wall_thickness" in body["strategy"]["parameters"]

    def test_empty_outcomes(self, client):
        r = client.post("/api/reasoning/analyze", json={"outcomes": []})
        assert r.status_code == 200
        assert r.json()["report"]["sample_count"] == 0

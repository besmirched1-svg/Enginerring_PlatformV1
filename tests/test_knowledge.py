"""Tests for app/knowledge/store.py — design memory."""
import pytest
import tempfile
from pathlib import Path
from app.knowledge.store import DesignMemoryStore


@pytest.fixture
def store(tmp_path):
    return DesignMemoryStore(store_path=tmp_path / "test_memory.ndjson")


class TestDesignMemoryStore:
    def test_record_evaluation(self, store):
        store.record_evaluation(
            machine_name="test",
            revision_id="rev_001",
            config={"roller": {"diameter": 180}},
            evaluation={"composite": 0.75, "needs_improvement": False,
                        "metrics": {}, "all_issues": []},
        )
        records = store.query(machine_name="test")
        assert len(records) == 1
        assert records[0]["record_type"] == "evaluation"

    def test_record_mutation(self, store):
        store.record_mutation(
            machine_name="test",
            parent_revision="rev_001",
            child_revision="rev_002",
            parent_config={"wall_thickness": 3.0},
            child_config={"wall_thickness": 4.5},
            score_delta=0.05,
            signals=["CRITICAL_WALL_THINNING"],
        )
        records = store.query(record_type="mutation")
        assert len(records) == 1
        assert records[0]["score_delta"] == 0.05

    def test_record_promotion(self, store):
        store.record_promotion("test", "rev_003", 0.82, "Exceeded threshold")
        records = store.query(record_type="promotion")
        assert len(records) == 1

    def test_record_failure(self, store):
        store.record_failure("test", "rev_bad", "OpenSCAD timeout", {})
        records = store.query(record_type="failure")
        assert len(records) == 1

    def test_query_filter_by_machine(self, store):
        store.record_evaluation("machine_a", "rev_1", {}, {"composite": 0.7,
            "needs_improvement": True, "metrics": {}, "all_issues": []})
        store.record_evaluation("machine_b", "rev_1", {}, {"composite": 0.8,
            "needs_improvement": False, "metrics": {}, "all_issues": []})
        records = store.query(machine_name="machine_a")
        assert all(r["machine_name"] == "machine_a" for r in records)

    def test_query_empty_store(self, store):
        assert store.query() == []

    def test_get_lessons_returns_strings(self, store):
        store.record_evaluation("test", "rev_1", {}, {"composite": 0.7,
            "needs_improvement": True, "metrics": {}, "all_issues": ["wall thin"]})
        lessons = store.get_lessons("test")
        assert isinstance(lessons, list)
        assert all(isinstance(l, str) for l in lessons)

    def test_successful_configs_filtered(self, store):
        store.record_evaluation("test", "rev_1", {"a": 1},
            {"composite": 0.80, "needs_improvement": False, "metrics": {}, "all_issues": []})
        store.record_evaluation("test", "rev_2", {"a": 2},
            {"composite": 0.60, "needs_improvement": True, "metrics": {}, "all_issues": []})
        good = store.successful_configs("test", min_score=0.75)
        assert len(good) == 1

    def test_limit_respected(self, store):
        for i in range(10):
            store.record_evaluation(f"m{i}", f"rev_{i}", {},
                {"composite": 0.5, "needs_improvement": True, "metrics": {}, "all_issues": []})
        records = store.query(limit=5)
        assert len(records) == 5

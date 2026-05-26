import unittest
import redis
import json
from unittest.mock import Mock, MagicMock
from app.core.mutation import propose_next_config
from app.core.promotion import should_promote
from app.core.improvement_chain import ImprovementChainManager

class TestAutonomousEngineeringLoops(unittest.TestCase):
    def setUp(self):
        # Provision an isolated fake Redis client instance for deterministic validation tracking
        self.redis_client = MagicMock(spec=redis.Redis)
        self.redis_store = {}
        
        # Mock state storage responses natively for consistent cross-platform evaluations
        def fake_exists(key):
            return key in self.redis_store
        def fake_hset(key, mapping=None, **kwargs):
            if mapping:
                self.redis_store[key] = {k: v.encode('utf-8') if isinstance(v, str) else str(v).encode('utf-8') for k, v in mapping.items()}
            return 1
        def fake_hgetall(key):
            return self.redis_store.get(key, {})
        def fake_hget(key, field):
            return self.redis_store.get(key, {}).get(field)
            
        self.redis_client.exists.side_effect = fake_exists
        self.redis_client.hset.side_effect = fake_hset
        self.redis_client.hgetall.side_effect = fake_hgetall
        
        # Mock transactional context tracking loops safely
        pipe_mock = MagicMock()
        pipe_mock.hget.side_effect = fake_hget
        self.redis_client.pipeline.return_value = pipe_mock
        self.chain_manager = ImprovementChainManager(self.redis_client)

    def test_mutation_geometric_bounds(self):
        """
        Verifies that config mutation scales parameters safely and respects boundary values.
        """
        config = {"wall_thickness": 3.0, "clearance": 0.5, "roller_radius": 30.0}
        eval_failure = {"issues": ["wall_thickness_insufficient"], "metrics": {"structural_stability": 0.3}, "score": 0.4}
        
        mutated = propose_next_config(config, eval_failure)
        self.assertIsNotNone(mutated)
        self.assertEqual(mutated["wall_thickness"], 4.5)

    def test_promotion_margin_thresholds(self):
        """
        Validates that promotion requires a 10% improvement or flat 0.05 step change.
        """
        # Challenger failing to clear margin conditions
        promoted, reason = should_promote(challenger_score=0.52, champion_score=0.50)
        self.assertFalse(promoted)
        
        # Challenger clearing via the +0.05 margin requirement vector
        promoted, reason = should_promote(challenger_score=0.56, champion_score=0.50)
        self.assertTrue(promoted)

    def test_redis_three_attempt_budget_ceiling(self):
        """
        Critical Safety Check: Ensures the state manager blocks loop propagation past 3 attempts.
        """
        chain_id = "test_hemp_roller_runaway_loop"
        self.chain_manager.init_chain(chain_id, "hemp_roller", "v0")
        
        # Emulate successive transactional checks climbing the state index loop
        pipe = self.redis_client.pipeline()
        
        # Attempt 1, 2, 3 should clear successfully
        self.redis_store[f"improve:chain:{chain_id}"] = {b"status": b"active", b"attempts": b"0"}
        allowed_1 = self.chain_manager.attempt_and_increment(chain_id)
        
        self.redis_store[f"improve:chain:{chain_id}"] = {b"status": b"active", b"attempts": b"1"}
        allowed_2 = self.chain_manager.attempt_and_increment(chain_id)
        
        self.redis_store[f"improve:chain:{chain_id}"] = {b"status": b"active", b"attempts": b"2"}
        allowed_3 = self.chain_manager.attempt_and_increment(chain_id)
        
        # Attempt 4 must trigger absolute exhaustion limits and block loop re-injection
        self.redis_store[f"improve:chain:{chain_id}"] = {b"status": b"active", b"attempts": b"3"}
        allowed_4 = self.chain_manager.attempt_and_increment(chain_id)
        
        self.assertFalse(allowed_4, "Safety Violation: Optimization loop bypassed the maximum attempt threshold cap.")

if __name__ == '__main__':
    unittest.main()

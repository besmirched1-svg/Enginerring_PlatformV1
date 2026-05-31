from app.core.swarm import MultiAgentSwarm


def test_multi_agent_swarm_returns_champion():
    swarm = MultiAgentSwarm(session_id="test-swarm", output_dir="./outputs")
    result = swarm.run("Build a heavy wet hemp roller", max_generations=2, population_size=3)

    assert result["status"] == "success"
    assert "champion" in result
    assert isinstance(result["champion"].get("params"), dict)
    assert result["champion"].get("score") is not None
    assert "strategy" in result
    assert result["generations"] == 2

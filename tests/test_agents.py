from app.agents import (
    AgentInput,
    AgentOrchestrator,
    ComplianceAgent,
    CostAgent,
    DesignerAgent,
    DigitalTwinAgent,
    ManufacturingAgent,
    PhysicsAgent,
    PromotionAgent,
    ReliabilityAgent,
    ValidatorAgent,
    BaseAgent,
    AgentScore,
)


# ---------------------------------------------------------------------------
# Base agent tests
# ---------------------------------------------------------------------------


class TrivialAgent(BaseAgent):
    name = "test"
    description = "Trivial test agent"
    def evaluate(self, inp):
        return AgentScore(name=self.name, score=0.5, passed=True)


def test_base_agent_default_name():
    assert TrivialAgent().name == "test"


def test_base_agent_evaluate():
    a = TrivialAgent()
    r = a.evaluate(AgentInput(config={}))
    assert isinstance(r, AgentScore)
    assert r.score == 0.5
    assert r.passed is True


# ---------------------------------------------------------------------------
# Orchestrator tests
# ---------------------------------------------------------------------------


def test_orchestrator_register():
    o = AgentOrchestrator()
    a = TrivialAgent()
    o.register(a)
    assert o.get_agent("test") is a
    assert "test" in o.agent_names


def test_orchestrator_register_all():
    o = AgentOrchestrator()
    o.register_all([TrivialAgent(), TrivialAgent()])
    # second registration overwrites first
    assert len(o.agent_names) == 1


def test_orchestrator_evaluate_empty():
    o = AgentOrchestrator()
    r = o.evaluate(AgentInput(config={}))
    assert r.composite == 0.0
    assert r.passed is True
    assert r.objective_vector == []
    assert r.scores == []


def test_orchestrator_evaluate_one_agent():
    o = AgentOrchestrator()
    o.register(TrivialAgent())
    r = o.evaluate(AgentInput(config={}))
    assert r.composite == 0.5
    assert len(r.scores) == 1
    assert r.scores[0].name == "test"


def test_orchestrator_evaluate_agent_failure():
    class FailingAgent(BaseAgent):
        name = "fail"
        description = "Always fails"
        def evaluate(self, inp):
            raise RuntimeError("boom")

    o = AgentOrchestrator()
    o.register(FailingAgent())
    r = o.evaluate(AgentInput(config={}))
    assert r.composite == 0.0
    assert r.passed is False
    assert r.scores[0].score == 0.0
    assert "error" in r.scores[0].details


def test_orchestrator_get_agent_not_found():
    o = AgentOrchestrator()
    assert o.get_agent("nonexistent") is None


# ---------------------------------------------------------------------------
# DesignerAgent tests
# ---------------------------------------------------------------------------


def test_designer_agent_good_config():
    a = DesignerAgent()
    r = a.evaluate(AgentInput(config={
        "drum_diameter": 600.0,
        "drum_length": 1800.0,
        "wall_thickness": 6.0,
        "bore_clearance": 2.0,
        "roller_diameter": 200.0,
        "flight_pitch": 300.0,
        "shaft_diameter": 80.0,
    }))
    assert r.score >= 0.8  # should be mostly fine


def test_designer_agent_bad_ld_ratio():
    a = DesignerAgent()
    r = a.evaluate(AgentInput(config={
        "drum_length": 300.0,  # L/D = 0.5, below 1.5
        "drum_diameter": 600.0,
    }))
    assert r.score < 0.9, f"score={r.score} issues={r.details['issues']}"


def test_designer_agent_thin_wall():
    a = DesignerAgent()
    r = a.evaluate(AgentInput(config={"wall_thickness": 3.0}))
    assert r.score < 0.85, f"score={r.score} issues={r.details['issues']}"


def test_designer_agent_drum_od_exceeds_skid():
    a = DesignerAgent()
    r = a.evaluate(AgentInput(config={
        "drum_od": 1200.0,
        "skid_width": 1000.0,
    }))
    assert r.score < 0.9, f"score={r.score} issues={r.details['issues']}"


# ---------------------------------------------------------------------------
# ValidatorAgent tests
# ---------------------------------------------------------------------------


def test_validator_agent_ok():
    a = ValidatorAgent()
    r = a.evaluate(AgentInput(config={}, temperature_c=20.0))
    assert r.score >= 0.9


def test_validator_agent_hot():
    a = ValidatorAgent()
    r = a.evaluate(AgentInput(config={}, temperature_c=250.0))
    assert r.score <= 0.85, f"score={r.score}"  # -0.15 for >200C


def test_validator_agent_over_mass():
    a = ValidatorAgent()
    r = a.evaluate(AgentInput(
        config={"total_mass_kg": 2000.0},
        target_mass_kg=1000.0,
    ))
    assert r.score < 0.8


def test_validator_agent_over_cost():
    a = ValidatorAgent()
    r = a.evaluate(AgentInput(
        config={"total_build_cost_aud": 100000.0},
        target_cost_aud=50000.0,
    ))
    assert r.score < 0.8


# ---------------------------------------------------------------------------
# PhysicsAgent tests
# ---------------------------------------------------------------------------


def test_physics_agent_good_safety_factors():
    a = PhysicsAgent()
    r = a.evaluate(AgentInput(config={
        "shaft_safety_factor": 2.5,
        "frame_safety_factor": 3.0,
        "rotor_safety_factor": 2.2,
        "bearing_life_hours": 50000,
        "fatigue_safety_factor": 2.0,
        "natural_frequency_hz": 15.0,
    }))
    assert r.score > 0.9


def test_physics_agent_low_safety_factors():
    a = PhysicsAgent()
    r = a.evaluate(AgentInput(config={
        "shaft_safety_factor": 1.2,
        "frame_safety_factor": 1.1,
        "rotor_safety_factor": 1.0,
        "bearing_life_hours": 5000,
        "fatigue_safety_factor": 0.8,
    }))
    assert r.score < 0.6


def test_physics_agent_no_data():
    a = PhysicsAgent()
    r = a.evaluate(AgentInput(config={}))
    assert r.score == 0.5  # neutral


# ---------------------------------------------------------------------------
# ManufacturingAgent tests
# ---------------------------------------------------------------------------


def test_manufacturing_agent_good():
    a = ManufacturingAgent()
    r = a.evaluate(AgentInput(
        config={
            "material_utilisation": 80.0,
            "serviceability_index": 85.0,
            "total_fabrication_hours": 10.0,
            "total_mass_kg": 850.0,
            "total_weld_length_m": 5.0,
            "total_build_cost_aud": 20000.0,
            "sheets_required": 4,
        },
        target_cost_aud=30000.0,
        target_mass_kg=850.0,
    ))
    assert r.score > 0.7


# ---------------------------------------------------------------------------
# CostAgent tests
# ---------------------------------------------------------------------------


def test_cost_agent_good():
    a = CostAgent()
    r = a.evaluate(AgentInput(
        config={
            "total_build_cost_aud": 20000.0,
            "cost_per_kg_aud": 18.0,
            "total_mass_kg": 1000.0,
        },
        target_cost_aud=30000.0,
    ))
    assert r.score > 0.7


def test_cost_agent_over_budget():
    a = CostAgent()
    r = a.evaluate(AgentInput(
        config={"total_build_cost_aud": 50000.0, "total_mass_kg": 1000.0},
        target_cost_aud=25000.0,
    ))
    assert r.score < 0.6


# ---------------------------------------------------------------------------
# ComplianceAgent tests
# ---------------------------------------------------------------------------


def test_compliance_agent_no_guarding():
    a = ComplianceAgent()
    r = a.evaluate(AgentInput(
        config={"has_guarding": False, "machine_type": "hemp_roller"},
    ))
    assert r.score < 0.8


def test_compliance_agent_loud():
    a = ComplianceAgent()
    r = a.evaluate(AgentInput(config={"noise_level_db": 95.0}))
    assert r.score < 0.9


# ---------------------------------------------------------------------------
# ReliabilityAgent tests
# ---------------------------------------------------------------------------


def test_reliability_agent_good():
    a = ReliabilityAgent()
    r = a.evaluate(AgentInput(config={
        "mtbf_hours": 20000,
        "failure_rate_per_year": 0.3,
        "maintenance_hours_per_year": 40,
        "reliability_1yr": 0.97,
    }))
    assert r.score > 0.8


def test_reliability_agent_poor():
    a = ReliabilityAgent()
    r = a.evaluate(AgentInput(config={
        "mtbf_hours": 2000,
        "failure_rate_per_year": 3.0,
        "reliability_1yr": 0.80,
    }))
    assert r.score < 0.5


# ---------------------------------------------------------------------------
# PromotionAgent tests
# ---------------------------------------------------------------------------


def test_promotion_agent_first_eval():
    a = PromotionAgent()
    r = a.evaluate(AgentInput(config={}))
    assert r.score == 0.7
    assert r.passed is True


def test_promotion_agent_improved():
    a = PromotionAgent()
    r = a.evaluate(AgentInput(
        config={},
        existing_scores={"prev_composite": 0.6, "current_composite": 0.75},
    ))
    assert r.score == 1.0


def test_promotion_agent_regressed():
    a = PromotionAgent()
    r = a.evaluate(AgentInput(
        config={},
        existing_scores={"prev_composite": 0.8, "current_composite": 0.6},
    ))
    assert r.score < 0.5


# ---------------------------------------------------------------------------
# DigitalTwinAgent tests
# ---------------------------------------------------------------------------


def test_digital_twin_agent_good():
    a = DigitalTwinAgent()
    r = a.evaluate(AgentInput(config={
        "wear_rate_mm_per_hr": 0.005,
        "fatigue_life_cycles": 2e6,
        "mtbf_hours": 15000,
        "reliability_1yr": 0.96,
    }))
    assert r.score > 0.7


def test_digital_twin_agent_no_data():
    a = DigitalTwinAgent()
    r = a.evaluate(AgentInput(config={}))
    assert r.score == 0.5  # neutral


# ---------------------------------------------------------------------------
# Full orchestrator pipeline tests
# ---------------------------------------------------------------------------


def test_full_agent_pipeline():
    orch = AgentOrchestrator()
    orch.register_all([
        DesignerAgent(),
        ValidatorAgent(),
        PhysicsAgent(),
        DigitalTwinAgent(),
        ManufacturingAgent(),
        CostAgent(),
        ComplianceAgent(),
        ReliabilityAgent(),
        PromotionAgent(),
    ])
    assert len(orch.agent_names) == 9

    inp = AgentInput(config={
        "shaft_safety_factor": 2.5,
        "frame_safety_factor": 3.0,
        "fatigue_safety_factor": 2.0,
        "bearing_life_hours": 50000,
        "material_utilisation": 75.0,
        "serviceability_index": 70.0,
        "total_build_cost_aud": 20000.0,
        "cost_per_kg_aud": 18.0,
        "total_mass_kg": 850.0,
        "drum_diameter": 600.0,
        "drum_length": 2000.0,
        "wall_thickness": 6.0,
        "has_guarding": True,
        "has_emergency_stop": True,
        "pto_guard": True,
    }, machine_type="hemp_roller", target_cost_aud=30000.0, target_mass_kg=1000.0)
    result = orch.evaluate(inp)
    assert len(result.scores) == 9
    assert len(result.objective_vector) == 9
    assert len(result.objective_names) == 9
    assert 0.0 <= result.composite <= 1.0
    assert result.passed is True, f"composite={result.composite:.3f} details={ {s.name: s.score for s in result.scores} }"

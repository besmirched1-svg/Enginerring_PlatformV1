"""Tests for the EngineeringCommittee (Phase 10 — Autonomous Engineering Department)."""

import json
import os
import tempfile
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

from app.agents.base import AgentInput, AgentScore
from app.agents.orchestrator import AgentEvaluation
from app.agents.committee import (
    EngineeringCommittee,
    NegotiationSession,
    NegotiationRound,
    CommitteeVote,
    Vote,
    _vote_from_score,
    _resolve_round,
    mediate_by_compromise,
    create_committee,
)


# ---------------------------------------------------------------------------
# Unit tests: _vote_from_score
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,passed,agent_name,expected", [
    (0.9, True, "designer", Vote.APPROVE),
    (0.85, True, "cost", Vote.APPROVE),
    (0.7, True, "manufacturing", Vote.APPROVE_WITH_CONDITIONS),
    (0.65, True, "reliability", Vote.APPROVE_WITH_CONDITIONS),
    (0.55, True, "promotion", Vote.ABSTAIN),
    (0.3, True, "compliance", Vote.ABSTAIN),
    (0.2, False, "designer", Vote.REJECT),
    (0.35, False, "validator", Vote.REJECT),
    (0.2, False, "compliance", Vote.VETO),
    (0.25, False, "physics", Vote.VETO),
    (0.1, False, "validator", Vote.VETO),
    (0.5, False, "cost", Vote.REJECT),
])
def test_vote_from_score(score, passed, agent_name, expected):
    assert _vote_from_score(score, passed, agent_name) == expected


# ---------------------------------------------------------------------------
# Unit tests: _resolve_round
# ---------------------------------------------------------------------------

def _make_vote(agent, vote_val, weight=1.0, suggested=None):
    return CommitteeVote(
        agent_name=agent,
        vote=vote_val,
        score=0.8,
        rationale="test",
        weight=weight,
        suggested_changes=suggested or [],
    )


def test_resolve_veto_rejects():
    votes = [
        _make_vote("compliance", Vote.VETO, weight=2.0),
        _make_vote("designer", Vote.APPROVE, weight=1.0),
    ]
    passed, summary, changes, veto_agents = _resolve_round(votes)
    assert not passed
    assert "Vetoed" in summary
    assert "compliance" in veto_agents


def test_resolve_approve_threshold():
    votes = [
        _make_vote("designer", Vote.APPROVE, weight=1.0),
        _make_vote("cost", Vote.APPROVE, weight=1.0),
        _make_vote("promotion", Vote.ABSTAIN, weight=0.5),
    ]
    passed, summary, changes, veto_agents = _resolve_round(votes)
    assert passed
    assert veto_agents == []


def test_resolve_approve_with_conditions():
    votes = [
        _make_vote("designer", Vote.APPROVE_WITH_CONDITIONS, weight=1.0, suggested=["increase wall_thickness"]),
        _make_vote("cost", Vote.APPROVE, weight=1.0),
        _make_vote("promotion", Vote.ABSTAIN, weight=0.5),
    ]
    passed, summary, changes, veto_agents = _resolve_round(votes)
    assert passed
    assert "increase wall_thickness" in changes


def test_resolve_reject_majority():
    votes = [
        _make_vote("designer", Vote.REJECT, weight=1.0),
        _make_vote("cost", Vote.REJECT, weight=1.0),
        _make_vote("promotion", Vote.APPROVE, weight=0.5),
    ]
    passed, summary, changes, veto_agents = _resolve_round(votes)
    assert not passed


def test_resolve_split_no_majority():
    votes = [
        _make_vote("designer", Vote.APPROVE, weight=1.0),
        _make_vote("cost", Vote.REJECT, weight=1.0),
    ]
    passed, summary, changes, veto_agents = _resolve_round(votes)
    assert not passed
    assert "Mixed" in summary


# ---------------------------------------------------------------------------
# Unit tests: mediate_by_compromise
# ---------------------------------------------------------------------------

def test_mediate_by_compromise():
    votes = [
        _make_vote("reliability", Vote.APPROVE_WITH_CONDITIONS, suggested=["wall_thickness=15.0", "drum_diameter=1300.0"]),
        _make_vote("designer", Vote.APPROVE_WITH_CONDITIONS, suggested=["wall_thickness=12.0"]),
    ]
    config = {"wall_thickness": 10.0, "drum_diameter": 1200.0, "drum_length": 3000.0}
    result = mediate_by_compromise(votes, config)
    assert result["drum_diameter"] == 1300.0
    assert result["drum_length"] == 3000.0


def test_mediate_by_compromise_no_suggestions():
    votes = [_make_vote("designer", Vote.APPROVE, suggested=[])]
    config = {"wall_thickness": 10.0}
    result = mediate_by_compromise(votes, config)
    assert result == config


# ---------------------------------------------------------------------------
# Committee integration test with mocked orchestrator
# ---------------------------------------------------------------------------

class _MockOrchestrator:
    def __init__(self):
        self.agent_names = ["designer", "validator", "physics", "cost", "compliance"]

    def evaluate(self, inp: AgentInput) -> AgentEvaluation:
        scores = [
            AgentScore(name="designer", score=0.85, passed=True, details={}, weight=1.0),
            AgentScore(name="validator", score=0.90, passed=True, details={}, weight=1.5),
            AgentScore(name="physics", score=0.75, passed=True, details={"issues": ["below minimum margin"]}, weight=2.0),
            AgentScore(name="cost", score=0.60, passed=True, details={}, weight=1.0),
            AgentScore(name="compliance", score=0.95, passed=True, details={}, weight=2.0),
        ]
        composite = sum(s.score * s.weight for s in scores) / sum(s.weight for s in scores)
        return AgentEvaluation(scores=scores, composite=composite)


def test_committee_approves_config():
    committee = EngineeringCommittee(orchestrator=_MockOrchestrator(), archive_path=os.devnull)
    config = {
        "drum_diameter": 1200.0, "drum_length": 3000.0,
        "flight_thickness": 12.0, "rotational_speed": 100.0,
    }
    session = committee.run_negotiation(config, prompt="Test config", max_rounds=3)
    assert session.approved
    assert len(session.rounds) >= 1
    assert session.final_composite > 0


def test_committee_archive(tmp_path):
    archive_path = os.path.join(tmp_path, "decisions.ndjson")
    committee = EngineeringCommittee(orchestrator=_MockOrchestrator(), archive_path=archive_path)
    config = {
        "drum_diameter": 1200.0, "drum_length": 3000.0,
        "flight_thickness": 12.0, "rotational_speed": 100.0,
    }
    committee.run_negotiation(config, prompt="Archive test", max_rounds=2)
    records = committee.get_archive(limit=10)
    assert len(records) >= 1
    assert records[-1]["approved"] is True


def test_committee_get_session(tmp_path):
    archive_path = os.path.join(tmp_path, "decisions.ndjson")
    committee = EngineeringCommittee(orchestrator=_MockOrchestrator(), archive_path=archive_path)
    config = {
        "drum_diameter": 1200.0, "drum_length": 3000.0,
        "flight_thickness": 12.0, "rotational_speed": 100.0,
    }
    session = committee.run_negotiation(config, prompt="Session lookup test", max_rounds=2)
    record = committee.get_session(session.session_id)
    assert record is not None
    assert record["session_id"] == session.session_id


def test_committee_empty_archive(tmp_path):
    archive_path = os.path.join(tmp_path, "empty.ndjson")
    committee = EngineeringCommittee(orchestrator=_MockOrchestrator(), archive_path=archive_path)
    records = committee.get_archive(limit=10)
    assert records == []


# ---------------------------------------------------------------------------
# Committee: config with a failing agent that triggers conditions
# ---------------------------------------------------------------------------

class _FailingMockOrchestrator:
    def __init__(self):
        self.agent_names = ["designer", "validator", "physics", "cost", "compliance"]

    def evaluate(self, inp: AgentInput) -> AgentEvaluation:
        scores = [
            AgentScore(name="designer", score=0.50, passed=True, details={}, weight=1.0),
            AgentScore(name="validator", score=0.40, passed=False, details={"issues": ["constraint violation"]}, weight=1.5),
            AgentScore(name="physics", score=0.60, passed=True, details={}, weight=2.0),
            AgentScore(name="cost", score=0.55, passed=True, details={}, weight=1.0),
            AgentScore(name="compliance", score=0.90, passed=True, details={}, weight=2.0),
        ]
        composite = sum(s.score * s.weight for s in scores) / sum(s.weight for s in scores)
        return AgentEvaluation(scores=scores, composite=composite)


def test_committee_rejects_and_compromises():
    committee = EngineeringCommittee(orchestrator=_FailingMockOrchestrator(), archive_path=os.devnull)
    config = {"wall_thickness": 5.0, "drum_diameter": 800.0}
    session = committee.run_negotiation(config, prompt="Failing test", max_rounds=3)
    assert len(session.rounds) >= 1


# ---------------------------------------------------------------------------
# Committee Veto scenario
# ---------------------------------------------------------------------------

class _VetoMockOrchestrator:
    def __init__(self):
        self.agent_names = ["designer", "compliance", "physics"]

    def evaluate(self, inp: AgentInput) -> AgentEvaluation:
        scores = [
            AgentScore(name="designer", score=0.85, passed=True, details={}, weight=1.0),
            AgentScore(name="compliance", score=0.15, passed=False, details={"issues": ["critical safety violation"]}, weight=2.0),
            AgentScore(name="physics", score=0.70, passed=True, details={}, weight=2.0),
        ]
        composite = sum(s.score * s.weight for s in scores) / sum(s.weight for s in scores)
        return AgentEvaluation(scores=scores, composite=composite)


def test_committee_veto():
    committee = EngineeringCommittee(orchestrator=_VetoMockOrchestrator(), archive_path=os.devnull)
    config = {"wall_thickness": 2.0}
    session = committee.run_negotiation(config, prompt="Veto test", max_rounds=2)
    assert "compliance" in session.veto_agents
    assert not session.approved


# ---------------------------------------------------------------------------
# Vote dataclass
# ---------------------------------------------------------------------------

def test_committee_vote_defaults():
    v = CommitteeVote(agent_name="test", vote=Vote.APPROVE, score=0.9)
    assert v.rationale == ""
    assert v.issues == []
    assert v.suggested_changes == []
    assert v.weight == 1.0


def test_negotiation_round_defaults():
    r = NegotiationRound(round_number=1)
    assert r.proposed_config == {}
    assert r.votes == []
    assert r.suggested_changes == []


# ---------------------------------------------------------------------------
# create_committee factory
# ---------------------------------------------------------------------------

def test_create_committee_default():
    cmte = create_committee(register_default_agents=True, archive_path=os.devnull)
    assert cmte.orchestrator is not None


# ---------------------------------------------------------------------------
# Archive edge cases
# ---------------------------------------------------------------------------

def test_archive_corrupted_line(tmp_path):
    archive_path = os.path.join(tmp_path, "corrupt.ndjson")
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write("not valid json\n{\"valid\": true}\n")
    committee = EngineeringCommittee(orchestrator=_MockOrchestrator(), archive_path=archive_path)
    records = committee.get_archive(limit=10)
    assert len(records) == 1
    assert records[0]["valid"] is True


# ---------------------------------------------------------------------------
# _cast_votes coverage
# ---------------------------------------------------------------------------

def test_cast_votes():
    committee = EngineeringCommittee(orchestrator=_MockOrchestrator(), archive_path=os.devnull)
    evaluation = _MockOrchestrator().evaluate(
        AgentInput(config={}, prompt="test", machine_type="hemp_roller")
    )
    votes = committee._cast_votes(evaluation)
    assert len(votes) == 5
    vote_names = [v.agent_name for v in votes]
    assert "designer" in vote_names
    assert "compliance" in vote_names

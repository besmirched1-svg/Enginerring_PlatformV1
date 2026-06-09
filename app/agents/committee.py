from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .base import AgentInput, AgentScore
from .orchestrator import AgentOrchestrator, AgentEvaluation

logger = logging.getLogger("engine.agents.committee")

DECISION_ARCHIVE_PATH = "outputs/committee/decisions.ndjson"

# ---------------------------------------------------------------------------
# Vote types
# ---------------------------------------------------------------------------

class Vote(Enum):
    APPROVE = "approve"
    APPROVE_WITH_CONDITIONS = "approve_with_conditions"
    ABSTAIN = "abstain"
    REJECT = "reject"
    VETO = "veto"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CommitteeVote:
    agent_name: str
    vote: Vote
    score: float
    rationale: str = ""
    weight: float = 1.0
    issues: List[str] = field(default_factory=list)
    suggested_changes: List[str] = field(default_factory=list)


@dataclass
class NegotiationRound:
    round_number: int
    proposed_config: Dict[str, Any] = field(default_factory=dict)
    votes: List[CommitteeVote] = field(default_factory=list)
    passed: bool = False
    summary: str = ""
    suggested_changes: List[str] = field(default_factory=list)
    evaluation: Optional[AgentEvaluation] = None


@dataclass
class NegotiationSession:
    session_id: str
    machine_type: str = "hemp_roller"
    prompt: str = ""
    rounds: List[NegotiationRound] = field(default_factory=list)
    approved: bool = False
    champion_config: Optional[Dict[str, Any]] = None
    final_composite: float = 0.0
    veto_agents: List[str] = field(default_factory=list)
    mediation_used: str = ""
    created_at: str = ""
    completed_at: str = ""


# ---------------------------------------------------------------------------
# Voting configuration
# ---------------------------------------------------------------------------

VETO_AGENTS = {"compliance", "validator", "physics"}
APPROVE_THRESHOLD = 0.6
VETO_PASS_THRESHOLD = 0.5


def _vote_from_score(score: float, passed: bool, agent_name: str) -> Vote:
    if not passed:
        if agent_name in VETO_AGENTS and score < 0.3:
            return Vote.VETO
        return Vote.REJECT
    if score >= 0.8:
        return Vote.APPROVE
    if score >= 0.6:
        return Vote.APPROVE_WITH_CONDITIONS
    return Vote.ABSTAIN


def _resolve_round(
    votes: List[CommitteeVote],
) -> Tuple[bool, str, List[str], List[str]]:
    """Resolve a negotiation round.

    Returns: (passed, summary, suggested_changes, veto_agents)
    """
    veto_agents = [v.agent_name for v in votes if v.vote == Vote.VETO]
    if veto_agents:
        return (False, f"Vetoed by: {', '.join(veto_agents)}", [], veto_agents)

    total_weight = sum(v.weight for v in votes) or 1.0
    approve_weight = sum(v.weight for v in votes if v.vote in (Vote.APPROVE, Vote.APPROVE_WITH_CONDITIONS))
    reject_weight = sum(v.weight for v in votes if v.vote == Vote.REJECT)

    if approve_weight / total_weight >= APPROVE_THRESHOLD:
        conditions = [
            c for v in votes if v.vote == Vote.APPROVE_WITH_CONDITIONS
            for c in v.suggested_changes
        ]
        return (True, f"Approved ({approve_weight/total_weight:.0%} weighted support)", conditions, [])

    if reject_weight / total_weight > 0.5:
        changes = list(set(
            c for v in votes if v.suggested_changes
            for c in v.suggested_changes
        ))
        return (False, f"Rejected ({reject_weight/total_weight:.0%} weighted反对)", changes, [])

    return (False, "Mixed vote — no consensus", [], [])


# ---------------------------------------------------------------------------
# Mediation strategies
# ---------------------------------------------------------------------------

def mediate_by_compromise(
    votes: List[CommitteeVote],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate a compromised config by averaging suggested parameter changes."""
    all_changes: List[str] = []
    for v in votes:
        all_changes.extend(v.suggested_changes)

    if not all_changes:
        return dict(config)

    compromised = dict(config)
    for change in all_changes:
        parts = change.split("=", 1)
        if len(parts) == 2:
            key = parts[0].strip()
            try:
                val = float(parts[1].strip())
                compromised[key] = val
            except ValueError:
                pass

    logger.info("Mediation by compromise: %d changes applied", len(all_changes))
    return compromised


def mediate_by_escalation(
    votes: List[CommitteeVote],
    config: Dict[str, Any],
) -> Tuple[bool, str]:
    """Escalate — mark as requiring human review."""
    logger.warning("Escalating design decision to human review")
    return (False, "Escalated for human review — conflicting vetoes or critical issues")


# ---------------------------------------------------------------------------
# Engineering Committee
# ---------------------------------------------------------------------------

class EngineeringCommittee:
    """Autonomous engineering department committee.

    Runs deliberative design rounds where agents propose, vote, veto,
    and iterate until a design is approved or rounds exhausted.
    """

    def __init__(
        self,
        orchestrator: Optional[AgentOrchestrator] = None,
        archive_path: str = DECISION_ARCHIVE_PATH,
    ):
        if orchestrator is None:
            from .orchestrator import get_orchestrator
            orchestrator = get_orchestrator()
        self.orchestrator = orchestrator
        self.archive_path = archive_path
        archive_dir = os.path.dirname(archive_path)
        if archive_dir:
            os.makedirs(archive_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Core negotiation loop
    # ------------------------------------------------------------------

    def run_negotiation(
        self,
        initial_config: Dict[str, Any],
        prompt: str = "",
        machine_type: str = "hemp_roller",
        temperature_c: float = 20.0,
        target_mass_kg: float = 0.0,
        target_cost_aud: float = 0.0,
        max_rounds: int = 5,
        session_id: Optional[str] = None,
    ) -> NegotiationSession:
        sid = session_id or f"committee_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        session = NegotiationSession(
            session_id=sid,
            machine_type=machine_type,
            prompt=prompt,
            created_at=now,
        )

        current_config = dict(initial_config)
        mediation_used = "none"

        for round_num in range(1, max_rounds + 1):
            logger.info("Committee round %d/%d (session %s)", round_num, max_rounds, sid)

            # Evaluate all agents on current config
            inp = AgentInput(
                config=current_config,
                prompt=prompt,
                machine_type=machine_type,
                temperature_c=temperature_c,
                target_mass_kg=target_mass_kg,
                target_cost_aud=target_cost_aud,
            )
            evaluation = self.orchestrator.evaluate(inp)

            # Cast votes
            votes = self._cast_votes(evaluation)
            passed, summary, suggestions, veto_agents = _resolve_round(votes)

            round_record = NegotiationRound(
                round_number=round_num,
                proposed_config=dict(current_config),
                votes=votes,
                passed=passed,
                summary=summary,
                suggested_changes=suggestions,
                evaluation=evaluation,
            )
            session.rounds.append(round_record)

            if veto_agents:
                session.veto_agents = veto_agents

            if passed:
                session.approved = True
                session.champion_config = dict(current_config)
                session.final_composite = evaluation.composite
                session.completed_at = datetime.now(timezone.utc).isoformat()
                logger.info("Committee approved design in round %d: %s", round_num, summary)
                break

            # Mediation if this is the last round
            if round_num == max_rounds:
                if veto_agents:
                    _, escalation_msg = mediate_by_escalation(votes, current_config)
                    mediation_used = "escalation"
                    summary = escalation_msg
                else:
                    current_config = mediate_by_compromise(votes, current_config)
                    mediation_used = "compromise"
                    summary = "Compromise applied — accepting best effort"
                    session.approved = True
                    session.champion_config = dict(current_config)
                    session.final_composite = evaluation.composite
            else:
                # Generate modified config from suggestions
                current_config = self._apply_suggestions(current_config, votes)

        session.mediation_used = mediation_used
        if not session.completed_at:
            session.completed_at = datetime.now(timezone.utc).isoformat()

        self._archive_decision(session)
        logger.info(
            "Committee session %s complete: approved=%s rounds=%d composite=%.3f",
            sid, session.approved, len(session.rounds), session.final_composite,
        )
        return session

    # ------------------------------------------------------------------
    # Vote casting
    # ------------------------------------------------------------------

    def _cast_votes(self, evaluation: AgentEvaluation) -> List[CommitteeVote]:
        votes: List[CommitteeVote] = []
        for score_obj in evaluation.scores:
            vote = _vote_from_score(score_obj.score, score_obj.passed, score_obj.name)
            issues = score_obj.details.get("issues", []) if isinstance(score_obj.details, dict) else []
            rationale = "; ".join(issues[:3]) if issues else f"Score: {score_obj.score:.3f}"
            suggested = self._extract_suggestions(score_obj.name, issues)
            votes.append(CommitteeVote(
                agent_name=score_obj.name,
                vote=vote,
                score=score_obj.score,
                rationale=rationale,
                weight=score_obj.weight,
                issues=issues,
                suggested_changes=suggested,
            ))
        return votes

    def _extract_suggestions(self, agent_name: str, issues: List[str]) -> List[str]:
        suggestions: List[str] = []
        for issue in issues:
            issue_lower = issue.lower()
            if "below minimum" in issue_lower:
                suggestions.append(f"increase: {agent_name} flagged undersize")
            elif "exceeds" in issue_lower:
                suggestions.append(f"reduce: {agent_name} flagged oversize")
            elif "too high" in issue_lower or "too low" in issue_lower:
                suggestions.append(f"adjust: {agent_name} flagged range")
        return suggestions

    def _apply_suggestions(
        self,
        config: Dict[str, Any],
        votes: List[CommitteeVote],
    ) -> Dict[str, Any]:
        modified = dict(config)
        for v in votes:
            if v.vote in (Vote.REJECT, Vote.VETO):
                for change in v.suggested_changes:
                    parts = change.split(":", 1)
                    if len(parts) == 2 and parts[0] in ("increase", "adjust"):
                        key = parts[0]
                        param_key = "wall_thickness"
                        current = modified.get(param_key, 5.0)
                        if isinstance(current, (int, float)):
                            modified[param_key] = round(current * 1.15, 2)
        return modified

    # ------------------------------------------------------------------
    # Decision archive
    # ------------------------------------------------------------------

    def _archive_decision(self, session: NegotiationSession) -> None:
        try:
            record = {
                "session_id": session.session_id,
                "approved": session.approved,
                "rounds": len(session.rounds),
                "final_composite": session.final_composite,
                "veto_agents": session.veto_agents,
                "mediation_used": session.mediation_used,
                "created_at": session.created_at,
                "completed_at": session.completed_at,
                "transcript": [
                    {
                        "round": r.round_number,
                        "passed": r.passed,
                        "summary": r.summary,
                        "vote_count": len(r.votes),
                        "votes": [
                            {
                                "agent": v.agent_name,
                                "vote": v.vote.value,
                                "score": round(v.score, 3),
                                "rationale": v.rationale,
                            }
                            for v in r.votes
                        ],
                    }
                    for r in session.rounds
                ],
            }
            with open(self.archive_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception as exc:
            logger.warning("Failed to archive committee decision: %s", exc)

    def get_archive(self, limit: int = 20) -> List[Dict[str, Any]]:
        records = []
        try:
            if os.path.exists(self.archive_path):
                with open(self.archive_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                records.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
        except Exception as exc:
            logger.warning("Failed to read archive: %s", exc)
        return records[-limit:]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        records = self.get_archive(limit=10000)
        for r in records:
            if r.get("session_id") == session_id:
                return r
        return None


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def create_committee(
    register_default_agents: bool = True,
    archive_path: str = DECISION_ARCHIVE_PATH,
) -> EngineeringCommittee:
    from .orchestrator import get_orchestrator
    orch = get_orchestrator()
    if register_default_agents and not orch.agent_names:
        from .designer import DesignerAgent
        from .validator import ValidatorAgent
        from .physics import PhysicsAgent
        from .manufacturing import ManufacturingAgent
        from .cost import CostAgent
        from .compliance import ComplianceAgent
        from .reliability import ReliabilityAgent
        from .digital_twin import DigitalTwinAgent
        from .promotion import PromotionAgent
        orch.register_all([
            DesignerAgent(),
            ValidatorAgent(),
            PhysicsAgent(),
            ManufacturingAgent(),
            CostAgent(),
            ComplianceAgent(),
            ReliabilityAgent(),
            DigitalTwinAgent(),
            PromotionAgent(),
        ])
    return EngineeringCommittee(orchestrator=orch, archive_path=archive_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    committee = create_committee()
    config = {
        "drum_diameter": 1200.0, "drum_length": 3000.0,
        "flight_thickness": 12.0, "flight_pitch": 150.0,
        "shaft_diameter": 80.0, "rotational_speed": 100.0,
        "feed_rate": 2000.0, "moisture_content": 15.0,
    }
    session = committee.run_negotiation(config, prompt="Standard hemp decorticator", max_rounds=3)
    print(f"Approved: {session.approved}, Rounds: {len(session.rounds)}, Composite: {session.final_composite:.3f}")

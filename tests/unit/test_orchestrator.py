from vigil.agents.orchestrator import VigilOrchestrator
from vigil.backends import BackendBundle
from vigil.backends.actions import MockActionBackend
from vigil.backends.audit import LocalAuditBackend
from vigil.schemas import (
    EnterpriseFinding,
    MonitoringInstruction,
    RegulatoryObligation,
    SourceEvidence,
    SourceFinding,
)


class ObligationOnlySourceBackend:
    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]:
        return [
            SourceFinding(
                summary="Official source describes a possible obligation.",
                obligations=[
                    RegulatoryObligation(
                        id="obl-test",
                        text="Review high-risk AI oversight procedures.",
                        jurisdiction=instruction.jurisdiction or "European Union",
                        topics=["human oversight"],
                        risk_level="high",
                        source_quote="Deployers shall review oversight procedures.",
                        confidence="high",
                    )
                ],
                evidence=[
                    SourceEvidence(
                        title="Official source",
                        snippet="Deployers shall review oversight procedures.",
                    )
                ],
                confidence=0.8,
            )
        ]


class EmptyRetrievalBackend:
    async def search(
        self,
        instruction: MonitoringInstruction,
        source_findings: list[SourceFinding],
    ) -> list[EnterpriseFinding]:
        return []


class AmbiguousSourceBackend:
    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]:
        return [
            SourceFinding(
                summary="Source update is too ambiguous to extract obligations.",
                obligations=[],
                evidence=[],
                confidence=0.2,
                uncertainty="No evidence-backed obligations were found.",
            )
        ]


async def test_orchestrator_marks_obligations_without_internal_match_informational() -> None:
    audit = LocalAuditBackend()
    orchestrator = VigilOrchestrator(
        backends=BackendBundle(
            source=ObligationOnlySourceBackend(),
            retrieval=EmptyRetrievalBackend(),
            actions=MockActionBackend(),
            audit=audit,
        )
    )

    decision = await orchestrator.analyze(
        MonitoringInstruction(
            query="EU AI Act deployer obligations",
            jurisdiction="European Union",
            domain="AI governance",
        )
    )

    assert decision.classification == "informational"
    assert decision.is_actionable is False
    assert decision.approval_required is False
    assert decision.ticket_status == "not_required"
    assert not any(result.action == "create_ticket" for result in decision.action_results)
    assert [event.event_type for event in audit.events][-1] == "analysis_completed"


async def test_orchestrator_marks_uncertain_source_without_obligations_ambiguous() -> None:
    orchestrator = VigilOrchestrator(
        backends=BackendBundle(
            source=AmbiguousSourceBackend(),
            retrieval=EmptyRetrievalBackend(),
            actions=MockActionBackend(),
            audit=LocalAuditBackend(),
        )
    )

    decision = await orchestrator.analyze(
        MonitoringInstruction(query="new AI governance consultation")
    )

    assert decision.classification == "ambiguous"
    assert decision.risk_level.value == "medium"
    assert decision.approval_required is False
    assert "Ask for clarification" in decision.recommended_actions[0]

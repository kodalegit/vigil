from vigil.agents.orchestrator import VigilOrchestrator
from vigil.backends import BackendBundle
from vigil.backends.actions import MockActionBackend
from vigil.backends.audit import LocalAuditBackend
from vigil.backends.memory import LocalMemoryBackend
from vigil.backends.org_context import LocalOrgContextRegistry, build_context_update_proposal
from vigil.backends.retrieval import LocalRetrievalBackend
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


class UnrelatedObligationSourceBackend:
    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]:
        return [
            SourceFinding(
                summary="Official source describes a shipping obligation.",
                obligations=[
                    RegulatoryObligation(
                        id="obl-shipping",
                        text="Report maritime ballast water discharge events to the port authority.",
                        jurisdiction=instruction.jurisdiction or "European Union",
                        topics=["shipping compliance"],
                        risk_level="medium",
                        source_quote="Vessels must report ballast discharge events.",
                        confidence="high",
                    )
                ],
                evidence=[
                    SourceEvidence(
                        title="Shipping source",
                        snippet="Vessels must report ballast discharge events.",
                    )
                ],
                confidence=0.8,
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


async def test_orchestrator_does_not_create_false_positive_artifacts_for_unrelated_obligation() -> None:
    audit = LocalAuditBackend()
    orchestrator = VigilOrchestrator(
        backends=BackendBundle(
            source=UnrelatedObligationSourceBackend(),
            retrieval=LocalRetrievalBackend(top_k=4, min_score=0.08),
            actions=MockActionBackend(),
            audit=audit,
            org_context=LocalOrgContextRegistry(),
            memory=LocalMemoryBackend(),
        )
    )

    decision = await orchestrator.analyze(
        MonitoringInstruction(
            query="maritime ballast water discharge reporting",
            jurisdiction="European Union",
            domain="shipping compliance",
        )
    )

    assert decision.classification == "informational"
    assert decision.enterprise_findings == []
    assert decision.approval_required is False
    assert not any(result.action == "send_alert" for result in decision.action_results)


async def test_orchestrator_uses_approved_org_context_and_false_positive_inventory() -> None:
    registry = LocalOrgContextRegistry()
    proposal = await build_context_update_proposal(
        registry,
        org_id="false-positive-org",
        summary="Approve false positive and Slack routing.",
        updates={
            "slack_preferences": {"default_channel": "#legal-review"},
            "obligation_inventory": [
                {
                    "obligation_id": "obl-test",
                    "jurisdiction": "European Union",
                    "canonical_text": "Review high-risk AI oversight procedures.",
                    "status": "false_positive",
                    "approval_status": "approved",
                    "confidence": "high",
                    "evidence_snippets": ["Deployers shall review oversight procedures."],
                }
            ],
        },
        approved=True,
    )
    await registry.commit_proposal(proposal.proposal_id, approved=True)
    audit = LocalAuditBackend()
    orchestrator = VigilOrchestrator(
        backends=BackendBundle(
            source=ObligationOnlySourceBackend(),
            retrieval=EmptyRetrievalBackend(),
            actions=MockActionBackend(),
            audit=audit,
            org_context=registry,
            memory=LocalMemoryBackend(),
        )
    )

    decision = await orchestrator.analyze(
        MonitoringInstruction(
            query="EU AI Act deployer obligations",
            org_id="false-positive-org",
        )
    )

    assert decision.classification == "irrelevant"
    assert decision.slack_channel == "#legal-review"
    assert any(event.event_type == "context_loaded" for event in audit.events)


async def test_orchestrator_records_approval_and_creates_ticket_once() -> None:
    audit = LocalAuditBackend()
    orchestrator = VigilOrchestrator(
        backends=BackendBundle(
            source=ObligationOnlySourceBackend(),
            retrieval=LocalRetrievalBackend(top_k=3),
            actions=MockActionBackend(),
            audit=audit,
            org_context=LocalOrgContextRegistry(),
            memory=LocalMemoryBackend(),
        )
    )
    decision = await orchestrator.analyze(
        MonitoringInstruction(query="EU AI Act deployer obligations")
    )

    approved = await orchestrator.record_approval(
        decision,
        approved_by="compliance-lead",
        idempotency_key="ticket:test-approval",
    )
    replay = await orchestrator.record_approval(
        approved,
        approved_by="compliance-lead",
        idempotency_key="ticket:test-approval",
    )

    assert approved.approval_status == "approved"
    assert approved.ticket_status == "created"
    assert approved.ticket_id
    assert replay.ticket_id == approved.ticket_id
    assert len(
        [
            result
            for result in approved.action_results
            if result.action == "create_ticket" and result.success
        ]
    ) == 1
    assert any(event.event_type == "ticket_created" for event in audit.events)
    assert any(event.event_type == "approval_idempotent_replay" for event in audit.events)

from vigil.backends.actions import build_slack_alert_payload
from vigil.backends.actions import MockActionBackend
from vigil.schemas import (
    Citation,
    EnterpriseChunk,
    EnterpriseDocument,
    EnterpriseFinding,
    ImpactDecision,
    RiskLevel,
    SourceFinding,
)


def test_slack_payload_is_approval_oriented_and_snippet_limited() -> None:
    long_text = "Sensitive policy text. " * 30
    document = EnterpriseDocument(
        doc_id="policy-ai-governance",
        title="AI Governance Policy",
        owner="Head of AI Governance",
        artifact_type="policy",
    )
    decision = ImpactDecision(
        is_actionable=True,
        risk_level=RiskLevel.high,
        classification="actionable",
        summary="Vigil found an actionable EU AI Act update.",
        recommended_actions=["Request human approval before creating remediation tasks."],
        approval_required=True,
        approval_status="pending",
        ticket_status="blocked_pending_approval",
        source_findings=[
            SourceFinding(
                summary="EU AI Act",
                obligations=[
                    {
                        "id": "obl-human-oversight",
                        "text": "Maintain documented human oversight.",
                        "jurisdiction": "European Union",
                        "source_quote": "Oversight required.",
                    }
                ],
            )
        ],
        enterprise_findings=[
            EnterpriseFinding(
                summary="Affected docs",
                chunks=[
                    EnterpriseChunk(
                        chunk_id="policy-ai-governance:1",
                        document=document,
                        text=long_text,
                        citation=Citation(
                            source="local",
                            title="AI Governance Policy",
                            snippet=long_text,
                            source_type="local",
                        ),
                    )
                ],
            )
        ],
    )

    payload = build_slack_alert_payload(decision)

    assert payload["classification"] == "actionable"
    assert payload["approval_required"] is True
    assert payload["approval_status"] == "pending"
    assert "Approve & create ticket" in payload["buttons"]
    assert payload["affected_artifacts"][0]["owner"] == "Head of AI Governance"
    assert len(payload["affected_artifacts"][0]["snippet"]) <= 220


async def test_mock_ticket_creation_is_approval_gated_and_idempotent() -> None:
    decision = ImpactDecision(
        analysis_id="analysis-idempotent",
        is_actionable=True,
        risk_level=RiskLevel.high,
        classification="actionable",
        summary="Actionable update.",
        approval_required=True,
        approval_status="pending",
        ticket_status="blocked_pending_approval",
    )
    backend = MockActionBackend()

    blocked = await backend.create_ticket(decision, approved=False)
    first = await backend.create_ticket(
        decision,
        approved=True,
        idempotency_key="ticket:analysis-idempotent",
    )
    replay = await backend.create_ticket(
        decision,
        approved=True,
        idempotency_key="ticket:analysis-idempotent",
    )

    assert blocked.success is False
    assert first.success is True
    assert first.external_id
    assert replay.external_id == first.external_id

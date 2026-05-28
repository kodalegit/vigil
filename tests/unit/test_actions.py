from types import SimpleNamespace
from typing import Any

from vigil.backends.actions import (
    MockActionBackend,
    SlackActionBackend,
    build_slack_alert_payload,
    build_slack_blocks,
)
from vigil.schemas import (
    Citation,
    EnterpriseChunk,
    EnterpriseDocument,
    EnterpriseFinding,
    ImpactDecision,
    RegulatoryObligation,
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
                    RegulatoryObligation(
                        id="obl-human-oversight",
                        text="Maintain documented human oversight.",
                        jurisdiction="European Union",
                        source_quote="Oversight required.",
                    )
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
    assert payload["actions"][0]["action_id"] == "approve_ticket"
    assert payload["actions"][0]["value"]["analysis_id"] == decision.analysis_id
    assert payload["affected_artifacts"][0]["owner"] == "Head of AI Governance"
    assert len(payload["affected_artifacts"][0]["snippet"]) <= 220
    blocks = build_slack_blocks(payload)
    assert blocks[-1]["type"] == "actions"
    assert blocks[-1]["elements"][0]["action_id"] == "approve_ticket"


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


async def test_slack_action_backend_posts_alert_with_blocks() -> None:
    class FakeSlackClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def chat_postMessage(self, **kwargs: Any) -> dict[str, object]:
            self.calls.append(kwargs)
            return {"ok": True, "ts": "123.456"}

    client = FakeSlackClient()
    backend = SlackActionBackend(
        settings=SimpleNamespace(slack_bot_token="xoxb-test-token"),
        client=client,
    )
    decision = ImpactDecision(
        analysis_id="analysis-slack",
        is_actionable=True,
        risk_level=RiskLevel.high,
        classification="actionable",
        summary="Actionable update.",
        approval_required=True,
        approval_status="pending",
        ticket_status="blocked_pending_approval",
        slack_channel="#legal-review",
    )

    result = await backend.send_alert(decision)

    assert result.success is True
    assert result.external_id == "123.456"
    assert client.calls[0]["channel"] == "#legal-review"
    assert client.calls[0]["blocks"][-1]["elements"][0]["action_id"] == "approve_ticket"

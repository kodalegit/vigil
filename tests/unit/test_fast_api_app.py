from typing import Any

from vigil.backends import BackendBundle
from vigil.backends.actions import MockActionBackend
from vigil.backends.audit import LocalAuditBackend
from vigil.backends.decisions import LocalDecisionStore
from vigil.backends.memory import LocalMemoryBackend
from vigil.backends.org_context import LocalOrgContextRegistry
from vigil.backends.retrieval import LocalRetrievalBackend
from vigil.fast_api_app import _parse_slack_command_text, _process_slack_analysis_command
from vigil.schemas import MonitoringInstruction, RegulatoryObligation, RiskLevel, SourceFinding


class ObligationSourceBackend:
    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]:
        return [
            SourceFinding(
                summary="Official source describes high-risk AI deployer obligations.",
                obligations=[
                    RegulatoryObligation(
                        id="obl-human-oversight",
                        text="Maintain documented human oversight procedures for high-risk AI workflows.",
                        jurisdiction=instruction.jurisdiction or "European Union",
                        topics=["human oversight", "AI governance"],
                        risk_level=RiskLevel.high,
                        source_quote="Deployers shall maintain human oversight.",
                        confidence="high",
                    )
                ],
                confidence=0.8,
            )
        ]


def test_parse_slack_command_text_preserves_argument_case() -> None:
    assert _parse_slack_command_text("") == ("", "")
    assert _parse_slack_command_text("onboard") == ("onboard", "")
    assert _parse_slack_command_text("Analyze EU AI Act obligations") == (
        "analyze",
        "EU AI Act obligations",
    )


async def test_slack_analysis_command_runs_orchestrator_and_posts_status(monkeypatch) -> None:
    decisions = LocalDecisionStore()
    backends = BackendBundle(
        source=ObligationSourceBackend(),
        retrieval=LocalRetrievalBackend(top_k=3),
        actions=MockActionBackend(),
        audit=LocalAuditBackend(),
        org_context=LocalOrgContextRegistry(),
        memory=LocalMemoryBackend(),
        decisions=decisions,
    )
    messages: list[str] = []

    def fake_create_backends() -> BackendBundle:
        return backends

    async def fake_post_slack_response(payload: dict[str, Any], text: str) -> None:
        messages.append(text)

    monkeypatch.setattr("vigil.fast_api_app.create_backends", fake_create_backends)
    monkeypatch.setattr("vigil.fast_api_app._post_slack_response", fake_post_slack_response)

    await _process_slack_analysis_command(
        {
            "team_id": "T123",
            "user_id": "U123",
            "response_url": "https://hooks.slack.com/actions/test",
        },
        "EU AI Act high-risk AI deployer obligations",
    )

    stored = next(iter(decisions.decisions.values()), None)
    assert stored is not None
    assert stored.is_actionable is True
    assert stored.approval_required is True
    assert any(result.action == "send_alert" for result in stored.action_results)
    assert messages == [
        "Vigil found an actionable regulatory impact and posted the review alert for `slack-team-T123`."
    ]

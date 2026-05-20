from typing import Protocol

from vigil.schemas import ActionResult, ImpactDecision


class ActionBackend(Protocol):
    async def send_alert(self, decision: ImpactDecision) -> ActionResult: ...

    async def generate_report(self, decision: ImpactDecision) -> ActionResult: ...


class MockActionBackend:
    async def send_alert(self, decision: ImpactDecision) -> ActionResult:
        payload = build_slack_alert_payload(decision)
        return ActionResult(
            action="send_alert",
            success=True,
            message=(
                f"Mock Slack alert prepared for {decision.risk_level.value} risk decision "
                f"with {len(payload['affected_artifacts'])} affected artifacts."
            ),
        )

    async def generate_report(self, decision: ImpactDecision) -> ActionResult:
        return ActionResult(
            action="generate_report",
            success=True,
            message="Mock cited report generated.",
        )


def build_slack_alert_payload(decision: ImpactDecision) -> dict:
    affected_artifacts = []
    for finding in decision.enterprise_findings:
        for chunk in finding.chunks[:5]:
            affected_artifacts.append(
                {
                    "doc_id": chunk.document.doc_id,
                    "title": chunk.document.title,
                    "owner": chunk.document.owner,
                    "snippet": _safe_snippet(chunk.text),
                    "section_ref": chunk.section_ref,
                }
            )

    what_changed = [
        obligation.text
        for finding in decision.source_findings
        for obligation in finding.obligations
    ][:5]
    return {
        "channel": "#ai-governance-review",
        "title": "EU AI Act update may affect AI governance controls",
        "classification": "actionable" if decision.is_actionable else "informational",
        "priority": decision.risk_level.value,
        "what_changed": what_changed,
        "why_it_matters": [decision.summary],
        "affected_artifacts": affected_artifacts,
        "suggested_actions": decision.recommended_actions,
        "buttons": [
            "Approve & create ticket",
            "Ask follow-up",
            "Mark as false positive",
        ],
    }


def _safe_snippet(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."

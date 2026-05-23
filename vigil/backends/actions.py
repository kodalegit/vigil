from typing import Protocol

from vigil.schemas import ActionResult, ImpactDecision


class ActionBackend(Protocol):
    async def send_alert(self, decision: ImpactDecision) -> ActionResult: ...

    async def generate_report(self, decision: ImpactDecision) -> ActionResult: ...

    async def create_ticket(self, decision: ImpactDecision, approved: bool = False) -> ActionResult: ...


class MockActionBackend:
    async def send_alert(self, decision: ImpactDecision) -> ActionResult:
        payload = build_slack_alert_payload(decision)
        return ActionResult(
            action="send_alert",
            success=True,
            message=(
                f"Mock Slack alert prepared for {decision.risk_level.value} risk decision "
                f"with {len(payload['affected_artifacts'])} affected artifact snippets."
            ),
        )

    async def generate_report(self, decision: ImpactDecision) -> ActionResult:
        return ActionResult(
            action="generate_report",
            success=True,
            message="Mock cited report generated.",
        )

    async def create_ticket(self, decision: ImpactDecision, approved: bool = False) -> ActionResult:
        if not approved:
            return ActionResult(
                action="create_ticket",
                success=False,
                message="Mock ticket creation blocked until human approval is recorded.",
            )
        return ActionResult(
            action="create_ticket",
            success=True,
            message=(
                "Mock remediation ticket created for "
                f"{len(_affected_artifacts(decision))} affected artifact snippets."
            ),
        )


def build_slack_alert_payload(decision: ImpactDecision) -> dict:
    what_changed = [
        obligation.text
        for finding in decision.source_findings
        for obligation in finding.obligations
    ][:5]
    return {
        "channel": "#ai-governance-review",
        "title": "EU AI Act update may affect AI governance controls",
        "classification": decision.classification,
        "priority": decision.risk_level.value,
        "approval_required": decision.approval_required,
        "approval_status": decision.approval_status,
        "what_changed": what_changed,
        "why_it_matters": [decision.summary],
        "affected_artifacts": _affected_artifacts(decision),
        "suggested_actions": decision.recommended_actions,
        "buttons": [
            "Approve & create ticket",
            "Ask follow-up",
            "Mark as false positive",
        ],
    }


def _affected_artifacts(decision: ImpactDecision) -> list[dict]:
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
    return affected_artifacts


def _safe_snippet(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."

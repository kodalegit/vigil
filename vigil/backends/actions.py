import json
from typing import Any, Protocol
from uuid import uuid4

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from vigil.schemas import ActionResult, ImpactDecision
from vigil.settings import Settings, get_settings


class ActionBackend(Protocol):
    async def send_alert(self, decision: ImpactDecision) -> ActionResult: ...

    async def generate_report(self, decision: ImpactDecision) -> ActionResult: ...

    async def create_ticket(
        self,
        decision: ImpactDecision,
        approved: bool = False,
        idempotency_key: str | None = None,
    ) -> ActionResult: ...


_MOCK_TICKETS: dict[str, str] = {}


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

    async def create_ticket(
        self,
        decision: ImpactDecision,
        approved: bool = False,
        idempotency_key: str | None = None,
    ) -> ActionResult:
        idempotency_key = idempotency_key or f"ticket:{decision.analysis_id}"
        if not approved:
            return ActionResult(
                action="create_ticket",
                success=False,
                message="Mock ticket creation blocked until human approval is recorded.",
                idempotency_key=idempotency_key,
            )
        ticket_id = _MOCK_TICKETS.setdefault(
            idempotency_key,
            f"mock-ticket-{uuid4().hex[:8]}",
        )
        return ActionResult(
            action="create_ticket",
            success=True,
            message=(
                "Mock remediation ticket created for "
                f"{len(_affected_artifacts(decision))} affected artifact snippets."
            ),
            external_id=ticket_id,
            idempotency_key=idempotency_key,
        )


class SlackActionBackend:
    def __init__(
        self,
        settings: Settings | None = None,
        client: WebClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or WebClient(token=self.settings.slack_bot_token)

    async def send_alert(self, decision: ImpactDecision) -> ActionResult:
        if not self.settings.slack_bot_token:
            return ActionResult(
                action="send_alert",
                success=False,
                message="Slack alert was not sent because SLACK_BOT_TOKEN is not configured.",
            )

        payload = build_slack_alert_payload(decision)
        try:
            response = self.client.chat_postMessage(
                channel=payload["channel"],
                text=payload["title"],
                blocks=build_slack_blocks(payload),
            )
        except SlackApiError as error:
            return ActionResult(
                action="send_alert",
                success=False,
                message=f"Slack alert failed: {error.response.get('error', 'unknown_error')}",
            )

        return ActionResult(
            action="send_alert",
            success=bool(response.get("ok")),
            message="Slack alert posted." if response.get("ok") else "Slack alert was rejected.",
            external_id=response.get("ts"),
        )

    async def generate_report(self, decision: ImpactDecision) -> ActionResult:
        return ActionResult(
            action="generate_report",
            success=True,
            message="Slack backend report generation is currently represented by the alert payload.",
        )

    async def create_ticket(
        self,
        decision: ImpactDecision,
        approved: bool = False,
        idempotency_key: str | None = None,
    ) -> ActionResult:
        return await MockActionBackend().create_ticket(
            decision,
            approved=approved,
            idempotency_key=idempotency_key,
        )


def build_slack_alert_payload(decision: ImpactDecision) -> dict:
    what_changed = [
        obligation.text
        for finding in decision.source_findings
        for obligation in finding.obligations
    ][:5]
    return {
        "channel": decision.slack_channel or "#ai-governance-review",
        "title": "EU AI Act update may affect AI governance controls",
        "classification": decision.classification,
        "priority": decision.risk_level.value,
        "approval_required": decision.approval_required,
        "approval_status": decision.approval_status,
        "reviewers": decision.reviewer_user_ids,
        "what_changed": what_changed,
        "why_it_matters": [decision.summary],
        "affected_artifacts": _affected_artifacts(decision),
        "suggested_actions": decision.recommended_actions,
        "buttons": [
            "Approve & create ticket",
            "Ask follow-up",
            "Mark as false positive",
        ],
        "actions": [
            {
                "label": "Approve & create ticket",
                "action_id": "approve_ticket",
                "value": {
                    "analysis_id": decision.analysis_id,
                    "org_id": decision.org_id,
                    "idempotency_key": f"ticket:{decision.org_id}:{decision.analysis_id}",
                },
            },
            {
                "label": "Ask follow-up",
                "action_id": "ask_follow_up",
                "value": {
                    "analysis_id": decision.analysis_id,
                    "org_id": decision.org_id,
                },
            },
            {
                "label": "Mark as false positive",
                "action_id": "mark_false_positive",
                "value": {
                    "analysis_id": decision.analysis_id,
                    "org_id": decision.org_id,
                },
            },
        ],
    }


def build_slack_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    fields = [
        f"*Classification:*\n{payload['classification']}",
        f"*Priority:*\n{payload['priority']}",
        f"*Approval:*\n{payload['approval_status']}",
    ]
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": payload["title"][:150]},
        },
        {
            "type": "section",
            "fields": [{"type": "mrkdwn", "text": field} for field in fields],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _mrkdwn_list(payload["why_it_matters"])},
        },
    ]
    if payload["what_changed"]:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*What changed*\n" + _mrkdwn_list(payload["what_changed"]),
                },
            }
        )
    if payload["affected_artifacts"]:
        artifacts = [
            f"{item['title']} ({item.get('owner') or 'unowned'}): {item['snippet']}"
            for item in payload["affected_artifacts"][:3]
        ]
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Affected artifacts*\n" + _mrkdwn_list(artifacts),
                },
            }
        )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": action["label"]},
                    "action_id": action["action_id"],
                    "value": json.dumps(action["value"], sort_keys=True),
                    **({"style": "primary"} if action["action_id"] == "approve_ticket" else {}),
                }
                for action in payload["actions"]
            ],
        }
    )
    return blocks


def _mrkdwn_list(items: list[str]) -> str:
    return "\n".join(f"- {_escape_mrkdwn(item)}" for item in items[:5]) or "- None"


def _escape_mrkdwn(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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

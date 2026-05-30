import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qs

from vigil.schemas import ContextUpdateProposal


ONBOARDING_CALLBACK_ID = "vigil_onboarding"
ONBOARDING_CONFIRM_CALLBACK_ID = "vigil_onboarding_confirmation"
ONBOARDING_START_ACTION_ID = "start_onboarding"
ONBOARDING_CONFIRM_ACTION_ID = "confirm_onboarding_context_update"
ONBOARDING_CANCEL_ACTION_ID = "cancel_onboarding_context_update"
FOLLOW_UP_CALLBACK_ID = "vigil_follow_up"


def verify_slack_signature(
    *,
    signing_secret: str,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    now: float | None = None,
    tolerance_seconds: int = 60 * 5,
) -> bool:
    if not signing_secret or not timestamp or not signature:
        return False
    try:
        request_time = int(timestamp)
    except ValueError:
        return False
    current_time = time.time() if now is None else now
    if abs(current_time - request_time) > tolerance_seconds:
        return False

    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(
        signing_secret.encode("utf-8"),
        base,
        hashlib.sha256,
    ).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)


def parse_slack_interaction_payload(body: bytes) -> dict[str, Any]:
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    payload_values = parsed.get("payload", [])
    if not payload_values:
        return {}
    payload = json.loads(payload_values[0])
    if not isinstance(payload, dict):
        return {}
    return payload


def parse_slack_command_payload(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[0] for key, values in parsed.items() if values}


def slack_action_id(payload: dict[str, Any]) -> str | None:
    action = _first_action(payload)
    if not action:
        return None
    action_id = action.get("action_id") or action.get("name")
    return str(action_id) if action_id else None


def slack_action_value(payload: dict[str, Any]) -> dict[str, Any]:
    action = _first_action(payload)
    if not action:
        return {}
    value = action.get("value")
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"value": value}
    return parsed if isinstance(parsed, dict) else {}


def slack_user_id(payload: dict[str, Any]) -> str | None:
    user = payload.get("user")
    if not isinstance(user, dict):
        return None
    user_id = user.get("id") or user.get("username") or user.get("name")
    return str(user_id) if user_id else None


def slack_team_id(payload: dict[str, Any]) -> str | None:
    team = payload.get("team")
    if isinstance(team, dict):
        team_id = team.get("id")
        if team_id:
            return str(team_id)
    team_id = payload.get("team_id")
    return str(team_id) if team_id else None


def slack_enterprise_id(payload: dict[str, Any]) -> str | None:
    enterprise = payload.get("enterprise")
    if isinstance(enterprise, dict):
        enterprise_id = enterprise.get("id")
        if enterprise_id:
            return str(enterprise_id)
    enterprise_id = payload.get("enterprise_id")
    return str(enterprise_id) if enterprise_id else None


def slack_channel_id(payload: dict[str, Any]) -> str | None:
    channel = payload.get("channel")
    if isinstance(channel, dict):
        channel_id = channel.get("id")
        if channel_id:
            return str(channel_id)
    channel_id = payload.get("channel_id")
    return str(channel_id) if channel_id else None


def slack_trigger_id(payload: dict[str, Any]) -> str | None:
    trigger_id = payload.get("trigger_id")
    return str(trigger_id) if trigger_id else None


def slack_org_id(payload: dict[str, Any]) -> str:
    enterprise_id = slack_enterprise_id(payload)
    if enterprise_id:
        return f"slack-ent-{enterprise_id}"
    team_id = slack_team_id(payload)
    if team_id:
        return f"slack-team-{team_id}"
    return "default-org"


def build_onboarding_start_blocks(org_id: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Set up Vigil for this workspace*\n"
                    "Capture the org profile, review channel, trusted sources, and first "
                    "monitoring profile."
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Start onboarding"},
                    "style": "primary",
                    "action_id": ONBOARDING_START_ACTION_ID,
                    "value": json.dumps({"org_id": org_id}, sort_keys=True),
                }
            ],
        },
    ]


def build_onboarding_modal(
    *,
    org_id: str,
    channel_id: str | None = None,
    user_id: str | None = None,
    team_id: str | None = None,
    enterprise_id: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": ONBOARDING_CALLBACK_ID,
        "private_metadata": json.dumps(
            {
                "org_id": org_id,
                "channel_id": channel_id,
                "user_id": user_id,
                "team_id": team_id,
                "enterprise_id": enterprise_id,
            },
            sort_keys=True,
        ),
        "title": {"type": "plain_text", "text": "Set up Vigil"},
        "submit": {"type": "plain_text", "text": "Review"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _plain_input("display_name", "Organization name", "Acme AI"),
            _plain_input("sectors", "Sectors", "SaaS, fintech"),
            _plain_input("products", "Products or systems", "Credit model, support chatbot"),
            _plain_input(
                "business_model",
                "Business profile",
                "Mid-size SaaS company handling regulated customer data.",
                multiline=True,
            ),
            _plain_input("jurisdictions", "Jurisdictions", "European Union, United States"),
            {
                "type": "input",
                "block_id": "risk_tolerance",
                "label": {"type": "plain_text", "text": "Risk tolerance"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": _option("medium", "Medium"),
                    "options": [
                        _option("low", "Low"),
                        _option("medium", "Medium"),
                        _option("high", "High"),
                        _option("critical", "Critical"),
                    ],
                },
            },
            {
                "type": "input",
                "block_id": "default_channel",
                "label": {"type": "plain_text", "text": "Default review channel"},
                "element": {
                    "type": "channels_select",
                    "action_id": "value",
                    **({"initial_channel": channel_id} if channel_id else {}),
                },
            },
            {
                "type": "input",
                "block_id": "reviewers",
                "optional": True,
                "label": {"type": "plain_text", "text": "Reviewers"},
                "element": {"type": "multi_users_select", "action_id": "value"},
            },
            _plain_input("source_name", "Trusted source name", "EU AI Act briefing"),
            _plain_input("source_url", "Trusted source URL", "https://artificialintelligenceact.eu/"),
            _plain_input("source_domains", "Source domains", "AI governance"),
            _plain_input("source_regulators", "Regulators", "European Union"),
            _plain_input(
                "monitoring_query",
                "First monitoring query",
                "EU AI Act high-risk AI deployer obligations",
            ),
            _plain_input("monitoring_cadence", "Monitoring cadence", "weekly"),
            {
                "type": "input",
                "block_id": "retrieval_source_type",
                "optional": True,
                "label": {"type": "plain_text", "text": "Enterprise retrieval source"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "Select a source"},
                    "options": [
                        _option("rag_engine", "Existing RAG Engine corpus"),
                        _option("drive", "Google Drive folder"),
                        _option("gcs", "Cloud Storage prefix"),
                    ],
                },
            },
            _plain_input(
                "rag_corpus",
                "RAG corpus resource",
                "projects/.../locations/.../ragCorpora/...",
                optional=True,
            ),
            _plain_input(
                "drive_folder_id",
                "Drive folder ID",
                "Folder ID from the Google Drive URL",
                optional=True,
            ),
            _plain_input(
                "gcs_uri",
                "Cloud Storage URI",
                "gs://bucket/path",
                optional=True,
            ),
        ],
    }


def parse_onboarding_submission(payload: dict[str, Any]) -> dict[str, Any]:
    view = payload.get("view") if isinstance(payload.get("view"), dict) else {}
    metadata = _json_dict(view.get("private_metadata"))
    values = view.get("state", {}).get("values", {})
    if not isinstance(values, dict):
        values = {}
    channel_id = _selected_channel(values, "default_channel") or metadata.get("channel_id")
    user_id = slack_user_id(payload) or metadata.get("user_id")
    org_id = str(metadata.get("org_id") or slack_org_id(payload))
    return {
        "org_id": org_id,
        "requested_by": user_id,
        "display_name": _plain_value(values, "display_name"),
        "sectors": _plain_value(values, "sectors"),
        "products": _plain_value(values, "products"),
        "business_model": _plain_value(values, "business_model"),
        "jurisdictions": _plain_value(values, "jurisdictions"),
        "risk_tolerance": _selected_option(values, "risk_tolerance") or "medium",
        "slack_channel": channel_id,
        "reviewers": _selected_users(values, "reviewers"),
        "source_name": _plain_value(values, "source_name"),
        "source_url": _plain_value(values, "source_url"),
        "source_jurisdictions": _plain_value(values, "jurisdictions"),
        "source_domains": _plain_value(values, "source_domains"),
        "source_regulators": _plain_value(values, "source_regulators"),
        "monitoring_query": _plain_value(values, "monitoring_query"),
        "monitoring_cadence": _plain_value(values, "monitoring_cadence"),
        "retrieval_source_type": _selected_option(values, "retrieval_source_type"),
        "rag_corpus": _plain_value(values, "rag_corpus"),
        "drive_folder_id": _plain_value(values, "drive_folder_id"),
        "gcs_uri": _plain_value(values, "gcs_uri"),
    }


def onboarding_context_updates(submission: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    profile_updates = {
        key: value
        for key, value in {
            "display_name": submission.get("display_name"),
            "sectors": _csv(submission.get("sectors")),
            "products": _csv(submission.get("products")),
            "business_model": submission.get("business_model"),
            "jurisdictions": _csv(submission.get("jurisdictions")),
            "risk_tolerance": submission.get("risk_tolerance"),
        }.items()
        if value not in (None, "", [])
    }
    if profile_updates:
        updates["profile"] = profile_updates

    slack_updates = {
        key: value
        for key, value in {
            "default_channel": submission.get("slack_channel"),
            "reviewer_user_ids": _csv_or_list(submission.get("reviewers")),
        }.items()
        if value not in (None, "", [])
    }
    if slack_updates:
        updates["slack_preferences"] = slack_updates

    source_name = submission.get("source_name")
    source_url = submission.get("source_url")
    source_id = _slug(source_name) if isinstance(source_name, str) else "trusted-source"
    if source_name and source_url:
        updates["source_policy"] = {
            "allowlisted_sources": [
                {
                    "source_id": source_id,
                    "name": source_name,
                    "url": source_url,
                    "jurisdictions": _csv(submission.get("source_jurisdictions")),
                    "domains": _csv(submission.get("source_domains")),
                    "regulators": _csv(submission.get("source_regulators")),
                    "trust_level": "trusted",
                    "freshness_days": 30,
                }
            ],
            "require_allowlist": True,
        }

    monitoring_query = submission.get("monitoring_query")
    if monitoring_query:
        updates["monitoring_profiles"] = [
            {
                "profile_id": _slug(str(monitoring_query))[:64] or "default-monitoring",
                "name": str(monitoring_query),
                "query": str(monitoring_query),
                "jurisdictions": _csv(submission.get("jurisdictions")),
                "domains": _csv(submission.get("source_domains")),
                "cadence": submission.get("monitoring_cadence") or "weekly",
                "threshold": "medium",
                "source_ids": [source_id] if source_name and source_url else [],
                "enabled": True,
            }
        ]

    retrieval_source_type = submission.get("retrieval_source_type")
    rag_corpus = submission.get("rag_corpus")
    drive_folder_id = submission.get("drive_folder_id")
    gcs_uri = submission.get("gcs_uri")
    if retrieval_source_type or rag_corpus or drive_folder_id or gcs_uri:
        source_type = retrieval_source_type or (
            "rag_engine" if rag_corpus else "drive" if drive_folder_id else "gcs"
        )
        resource_name = (
            "RAG Engine corpus"
            if source_type == "rag_engine"
            else "Google Drive policy folder"
            if source_type == "drive"
            else "Cloud Storage policy prefix"
        )
        updates["retrieval_resources"] = [
            {
                "resource_id": _slug(str(rag_corpus or drive_folder_id or gcs_uri or source_type)),
                "name": resource_name,
                "source_type": source_type,
                "rag_corpus": rag_corpus,
                "drive_folder_id": drive_folder_id,
                "gcs_uri": gcs_uri,
                "refresh_cadence": "manual",
                "enabled": True,
            }
        ]

    return updates


def build_onboarding_confirmation_blocks(proposal: ContextUpdateProposal) -> list[dict[str, Any]]:
    diff = "\n".join(f"- {item}" for item in proposal.diff[:8])
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Vigil onboarding is ready for review*\n{diff}\n\n"
                    f"Proposal `{proposal.proposal_id}` will become the approved profile for "
                    f"`{proposal.org_id}`."
                ),
            },
        },
    ]


def onboarding_confirmation_metadata(proposal: ContextUpdateProposal) -> str:
    return json.dumps(
        {"proposal_id": proposal.proposal_id, "org_id": proposal.org_id},
        sort_keys=True,
    )


def onboarding_confirmation_ids(payload: dict[str, Any]) -> dict[str, str]:
    view = payload.get("view") if isinstance(payload.get("view"), dict) else {}
    metadata = _json_dict(view.get("private_metadata"))
    return {
        "proposal_id": str(metadata.get("proposal_id") or ""),
        "org_id": str(metadata.get("org_id") or ""),
    }


def build_onboarding_complete_blocks(org_id: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Vigil onboarding is complete.*\nApproved profile: `{org_id}`",
            },
        }
    ]


def build_follow_up_modal(
    *,
    analysis_id: str,
    org_id: str,
    response_url: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": FOLLOW_UP_CALLBACK_ID,
        "private_metadata": json.dumps(
            {
                "analysis_id": analysis_id,
                "org_id": org_id,
                "response_url": response_url,
            },
            sort_keys=True,
        ),
        "title": {"type": "plain_text", "text": "Ask follow-up"},
        "submit": {"type": "plain_text", "text": "Record"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _plain_input(
                "follow_up_note",
                "Follow-up question or note",
                "What evidence should Vigil retrieve before this is approved?",
                multiline=True,
            )
        ],
    }


def parse_follow_up_submission(payload: dict[str, Any]) -> dict[str, str]:
    view = payload.get("view") if isinstance(payload.get("view"), dict) else {}
    metadata = _json_dict(view.get("private_metadata"))
    values = view.get("state", {}).get("values", {})
    if not isinstance(values, dict):
        values = {}
    return {
        "analysis_id": str(metadata.get("analysis_id") or ""),
        "org_id": str(metadata.get("org_id") or ""),
        "response_url": str(metadata.get("response_url") or ""),
        "requested_by": slack_user_id(payload) or "",
        "note": _plain_value(values, "follow_up_note") or "",
    }


def build_follow_up_complete_blocks(analysis_id: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Follow-up recorded.*\n"
                    f"Decision `{analysis_id}` remains pending review."
                ),
            },
        }
    ]


def _first_action(payload: dict[str, Any]) -> dict[str, Any] | None:
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        return None
    action = actions[0]
    if not isinstance(action, dict):
        return None
    return action


def _plain_input(
    block_id: str,
    label: str,
    placeholder: str,
    *,
    multiline: bool = False,
    optional: bool = False,
) -> dict[str, Any]:
    return {
        "type": "input",
        "block_id": block_id,
        "optional": optional,
        "label": {"type": "plain_text", "text": label},
        "element": {
            "type": "plain_text_input",
            "action_id": "value",
            "placeholder": {"type": "plain_text", "text": placeholder},
            "multiline": multiline,
        },
    }


def _option(value: str, text: str) -> dict[str, Any]:
    return {"text": {"type": "plain_text", "text": text}, "value": value}


def _json_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _input(values: dict[str, Any], block_id: str) -> dict[str, Any]:
    block = values.get(block_id)
    if not isinstance(block, dict):
        return {}
    action = block.get("value")
    if isinstance(action, dict):
        return action
    for value in block.values():
        if isinstance(value, dict):
            return value
    return {}


def _plain_value(values: dict[str, Any], block_id: str) -> str | None:
    value = _input(values, block_id).get("value")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _selected_option(values: dict[str, Any], block_id: str) -> str | None:
    option = _input(values, block_id).get("selected_option")
    if not isinstance(option, dict):
        return None
    value = option.get("value")
    return str(value) if value else None


def _selected_channel(values: dict[str, Any], block_id: str) -> str | None:
    value = _input(values, block_id).get("selected_channel")
    return str(value) if value else None


def _selected_users(values: dict[str, Any], block_id: str) -> list[str]:
    selected = _input(values, block_id).get("selected_users")
    if not isinstance(selected, list):
        return []
    return [str(user) for user in selected if user]


def _csv(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _csv_or_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return _csv(value)


def _slug(value: str) -> str:
    return "-".join(part for part in value.lower().replace("/", " ").split() if part)

import hashlib
import hmac
import json
from urllib.parse import quote_plus

from vigil.slack import (
    build_onboarding_confirmation_blocks,
    build_follow_up_modal,
    onboarding_confirmation_ids,
    onboarding_confirmation_metadata,
    build_onboarding_modal,
    build_onboarding_start_blocks,
    onboarding_context_updates,
    parse_slack_interaction_payload,
    parse_follow_up_submission,
    parse_onboarding_submission,
    slack_action_id,
    slack_org_id,
    slack_action_value,
    slack_user_id,
    verify_slack_signature,
)
from vigil.schemas import ContextUpdateProposal, OrgContext


def test_verify_slack_signature_accepts_valid_signature() -> None:
    secret = "test-signing-secret"
    timestamp = "1779747600"
    body = b"payload=%7B%22type%22%3A%22block_actions%22%7D"
    signature = _signature(secret, timestamp, body)

    assert verify_slack_signature(
        signing_secret=secret,
        body=body,
        timestamp=timestamp,
        signature=signature,
        now=1779747600,
    )


def test_verify_slack_signature_rejects_stale_or_mismatched_requests() -> None:
    secret = "test-signing-secret"
    timestamp = "1779747600"
    body = b"payload=%7B%22type%22%3A%22block_actions%22%7D"
    signature = _signature(secret, timestamp, body)

    assert not verify_slack_signature(
        signing_secret=secret,
        body=body,
        timestamp=timestamp,
        signature=signature,
        now=1779748001,
    )
    assert not verify_slack_signature(
        signing_secret=secret,
        body=b"payload=tampered",
        timestamp=timestamp,
        signature=signature,
        now=1779747600,
    )


def test_parse_slack_interaction_payload_and_action_id() -> None:
    payload = {
        "type": "block_actions",
        "actions": [{"action_id": "approve_ticket"}],
    }
    body = f"payload={quote_plus(json.dumps(payload))}".encode("utf-8")

    parsed = parse_slack_interaction_payload(body)

    assert parsed["type"] == "block_actions"
    assert slack_action_id(parsed) == "approve_ticket"


def test_slack_action_value_and_user_id_parse_button_metadata() -> None:
    payload = {
        "user": {"id": "U123"},
        "actions": [
            {
                "action_id": "approve_ticket",
                "value": json.dumps(
                    {
                        "analysis_id": "analysis-123",
                        "idempotency_key": "ticket:analysis-123",
                    }
                ),
            }
        ],
    }

    assert slack_action_value(payload)["analysis_id"] == "analysis-123"
    assert slack_action_value(payload)["idempotency_key"] == "ticket:analysis-123"
    assert slack_user_id(payload) == "U123"


def test_slack_org_id_prefers_enterprise_over_team() -> None:
    assert slack_org_id({"enterprise": {"id": "E123"}, "team": {"id": "T123"}}) == (
        "slack-ent-E123"
    )
    assert slack_org_id({"team": {"id": "T123"}}) == "slack-team-T123"
    assert slack_org_id({}) == "default-org"


def test_onboarding_start_and_modal_blocks_include_stable_metadata() -> None:
    start_blocks = build_onboarding_start_blocks("slack-team-T123")
    modal = build_onboarding_modal(
        org_id="slack-team-T123",
        channel_id="C123",
        user_id="U123",
        team_id="T123",
    )

    assert start_blocks[-1]["elements"][0]["action_id"] == "start_onboarding"
    assert modal["callback_id"] == "vigil_onboarding"
    assert json.loads(modal["private_metadata"])["org_id"] == "slack-team-T123"
    assert any(block.get("block_id") == "default_channel" for block in modal["blocks"])


def test_parse_onboarding_submission_builds_context_updates() -> None:
    payload = {
        "type": "view_submission",
        "user": {"id": "U123"},
        "view": {
            "callback_id": "vigil_onboarding",
            "private_metadata": json.dumps(
                {"org_id": "slack-team-T123", "channel_id": "CDEFAULT"}
            ),
            "state": {
                "values": {
                    "display_name": {"value": {"value": "Acme AI"}},
                    "sectors": {"value": {"value": "SaaS, fintech"}},
                    "products": {"value": {"value": "Credit model"}},
                    "business_model": {"value": {"value": "Regulated SaaS."}},
                    "jurisdictions": {"value": {"value": "European Union, United States"}},
                    "risk_tolerance": {
                        "value": {"selected_option": {"value": "low"}}
                    },
                    "default_channel": {"value": {"selected_channel": "CLEGAL"}},
                    "reviewers": {"value": {"selected_users": ["U123", "U456"]}},
                    "source_name": {"value": {"value": "EU AI Act briefing"}},
                    "source_url": {"value": {"value": "https://artificialintelligenceact.eu/"}},
                    "source_domains": {"value": {"value": "AI governance"}},
                    "source_regulators": {"value": {"value": "European Union"}},
                    "monitoring_query": {
                        "value": {"value": "EU AI Act high-risk AI deployer obligations"}
                    },
                    "monitoring_cadence": {"value": {"value": "weekly"}},
                    "retrieval_source_type": {
                        "value": {"selected_option": {"value": "rag_engine"}}
                    },
                    "rag_corpus": {
                        "value": {
                            "value": "projects/acme/locations/us-central1/ragCorpora/123"
                        }
                    },
                }
            },
        },
    }

    submission = parse_onboarding_submission(payload)
    updates = onboarding_context_updates(submission)

    assert submission["org_id"] == "slack-team-T123"
    assert submission["requested_by"] == "U123"
    assert updates["profile"]["display_name"] == "Acme AI"
    assert updates["profile"]["risk_tolerance"] == "low"
    assert updates["slack_preferences"]["default_channel"] == "CLEGAL"
    assert updates["slack_preferences"]["reviewer_user_ids"] == ["U123", "U456"]
    assert updates["source_policy"]["allowlisted_sources"][0]["source_id"] == "eu-ai-act-briefing"
    assert updates["monitoring_profiles"][0]["enabled"] is True
    assert updates["retrieval_resources"][0]["source_type"] == "rag_engine"
    assert updates["retrieval_resources"][0]["rag_corpus"] == (
        "projects/acme/locations/us-central1/ragCorpora/123"
    )


def test_onboarding_confirmation_blocks_commit_existing_proposal() -> None:
    proposal = ContextUpdateProposal(
        proposal_id="ctx-123",
        org_id="slack-team-T123",
        summary="Slack onboarding.",
        proposed_context=OrgContext(),
        diff=["Updated organization profile.", "Updated Slack preferences."],
    )

    blocks = build_onboarding_confirmation_blocks(proposal)
    metadata = onboarding_confirmation_metadata(proposal)
    parsed = onboarding_confirmation_ids({"view": {"private_metadata": metadata}})

    assert blocks[0]["type"] == "section"
    assert parsed["proposal_id"] == "ctx-123"
    assert parsed["org_id"] == "slack-team-T123"


def test_follow_up_modal_round_trips_submission_metadata() -> None:
    modal = build_follow_up_modal(
        analysis_id="analysis-123",
        org_id="slack-team-T123",
        response_url="https://hooks.slack.com/actions/test",
    )
    metadata = json.loads(modal["private_metadata"])
    payload = {
        "type": "view_submission",
        "user": {"id": "U123"},
        "view": {
            "callback_id": "vigil_follow_up",
            "private_metadata": modal["private_metadata"],
            "state": {
                "values": {
                    "follow_up_note": {
                        "value": {"value": "Please retrieve the cited policy owner."}
                    }
                }
            },
        },
    }

    submission = parse_follow_up_submission(payload)

    assert metadata["analysis_id"] == "analysis-123"
    assert submission["analysis_id"] == "analysis-123"
    assert submission["org_id"] == "slack-team-T123"
    assert submission["requested_by"] == "U123"
    assert submission["note"] == "Please retrieve the cited policy owner."


def _signature(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        b"v0:" + timestamp.encode("utf-8") + b":" + body,
        hashlib.sha256,
    ).hexdigest()
    return f"v0={digest}"

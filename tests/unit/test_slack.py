import hashlib
import hmac
import json
from urllib.parse import quote_plus

from vigil.slack import (
    parse_slack_interaction_payload,
    slack_action_id,
    slack_action_value,
    slack_user_id,
    verify_slack_signature,
)


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


def _signature(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        b"v0:" + timestamp.encode("utf-8") + b":" + body,
        hashlib.sha256,
    ).hexdigest()
    return f"v0={digest}"

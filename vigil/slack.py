import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qs


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


def slack_action_id(payload: dict[str, Any]) -> str | None:
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        return None
    action = actions[0]
    if not isinstance(action, dict):
        return None
    action_id = action.get("action_id") or action.get("name")
    return str(action_id) if action_id else None

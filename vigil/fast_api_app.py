# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os

import google.auth
from fastapi import FastAPI, HTTPException, Request
from google.adk.cli.fast_api import get_fast_api_app
from google.cloud import logging as google_cloud_logging

from vigil.app_utils.telemetry import setup_telemetry
from vigil.app_utils.typing import Feedback
from vigil.agents import VigilOrchestrator
from vigil.backends import create_backends
from vigil.settings import get_settings
from vigil.slack import (
    parse_slack_interaction_payload,
    slack_action_id,
    slack_action_value,
    slack_user_id,
    verify_slack_signature,
)

setup_telemetry()
_, project_id = google.auth.default()
logging_client = google_cloud_logging.Client()
logger = logging_client.logger(__name__)
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# In-memory session configuration - no persistent storage
session_service_uri = None

artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    otel_to_cloud=True,
)
app.title = "vigil"
app.description = "API for interacting with the Agent vigil"


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


@app.post("/slack/interactions")
async def handle_slack_interaction(request: Request) -> dict[str, str | None]:
    """Verify and acknowledge Slack interactive callbacks."""
    settings = get_settings()
    if not settings.slack_signing_secret:
        raise HTTPException(status_code=503, detail="Slack signing secret is not configured.")

    body = await request.body()
    if not verify_slack_signature(
        signing_secret=settings.slack_signing_secret,
        body=body,
        timestamp=request.headers.get("X-Slack-Request-Timestamp"),
        signature=request.headers.get("X-Slack-Signature"),
    ):
        raise HTTPException(status_code=401, detail="Invalid Slack signature.")

    try:
        payload = parse_slack_interaction_payload(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid Slack interaction payload.") from None

    action_id = slack_action_id(payload)
    action_value = slack_action_value(payload)
    approval_status: str | None = None
    ticket_id: str | None = None
    if action_id == "approve_ticket":
        analysis_id = action_value.get("analysis_id")
        if not isinstance(analysis_id, str) or not analysis_id:
            raise HTTPException(status_code=400, detail="Slack action is missing analysis_id.")
        backends = create_backends()
        if backends.decisions is None:
            raise HTTPException(status_code=503, detail="Decision store is not configured.")
        decision = await backends.decisions.get(analysis_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="Impact decision was not found.")
        approved = await VigilOrchestrator(backends=backends).record_approval(
            decision,
            approved_by=slack_user_id(payload) or "slack-user",
            approved=True,
            idempotency_key=action_value.get("idempotency_key")
            if isinstance(action_value.get("idempotency_key"), str)
            else None,
        )
        approval_status = approved.approval_status
        ticket_id = approved.ticket_id

    logger.log_struct(
        {
            "event": "slack_interaction_verified",
            "action_id": action_id,
            "team_id": (
                payload.get("team", {}).get("id")
                if isinstance(payload.get("team"), dict)
                else None
            ),
            "user_id": (
                payload.get("user", {}).get("id")
                if isinstance(payload.get("user"), dict)
                else None
            ),
        },
        severity="INFO",
    )
    return {
        "status": "acknowledged",
        "action_id": action_id,
        "approval_status": approval_status,
        "ticket_id": ticket_id,
    }


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

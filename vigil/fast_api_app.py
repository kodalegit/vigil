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

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request

import google.auth
from fastapi import FastAPI, HTTPException, Request
from google.adk.cli.fast_api import get_fast_api_app
from google.cloud import logging as google_cloud_logging
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from vigil.app_utils.telemetry import setup_telemetry
from vigil.app_utils.typing import Feedback
from vigil.agents import VigilOrchestrator
from vigil.backends import create_backends
from vigil.backends.org_context import build_context_update_proposal
from vigil.settings import get_settings
from vigil.slack import (
    ONBOARDING_CALLBACK_ID,
    ONBOARDING_CANCEL_ACTION_ID,
    ONBOARDING_CONFIRM_CALLBACK_ID,
    ONBOARDING_CONFIRM_ACTION_ID,
    ONBOARDING_START_ACTION_ID,
    FOLLOW_UP_CALLBACK_ID,
    build_follow_up_complete_blocks,
    build_follow_up_modal,
    build_onboarding_confirmation_blocks,
    build_onboarding_complete_blocks,
    build_onboarding_modal,
    build_onboarding_start_blocks,
    onboarding_confirmation_ids,
    onboarding_confirmation_metadata,
    onboarding_context_updates,
    parse_follow_up_submission,
    parse_onboarding_submission,
    parse_slack_command_payload,
    parse_slack_interaction_payload,
    slack_channel_id,
    slack_action_id,
    slack_action_value,
    slack_org_id,
    slack_team_id,
    slack_enterprise_id,
    slack_trigger_id,
    slack_user_id,
    verify_slack_signature,
)

setup_telemetry()
logger = logging.getLogger(__name__)
try:
    _, project_id = google.auth.default()
    logging_client = google_cloud_logging.Client(project=project_id)
    struct_logger = logging_client.logger(__name__)
except Exception as error:
    project_id = None
    logger.warning("Cloud logging unavailable; using local structured logging: %s", error)
    struct_logger = None
allow_origins = os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None

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
    _log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


@app.post("/slack/interactions")
async def handle_slack_interaction(request: Request) -> dict:
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

    if payload.get("type") == "view_submission":
        return await _handle_slack_view_submission(payload)

    action_id = slack_action_id(payload)
    action_value = slack_action_value(payload)
    if action_id == ONBOARDING_START_ACTION_ID:
        if not settings.slack_bot_token:
            return {
                "response_type": "ephemeral",
                "text": "Slack bot token is not configured, so Vigil cannot open onboarding.",
            }
        await _open_onboarding_modal(payload)
    elif action_id == ONBOARDING_CONFIRM_ACTION_ID:
        asyncio.create_task(_process_slack_interaction(payload))
    elif action_id == ONBOARDING_CANCEL_ACTION_ID:
        await _post_slack_response(payload, "Vigil onboarding was canceled.")
    elif action_id == "ask_follow_up":
        analysis_id = action_value.get("analysis_id")
        if not isinstance(analysis_id, str) or not analysis_id:
            raise HTTPException(status_code=400, detail="Slack action is missing analysis_id.")
        org_id = action_value.get("org_id")
        if not isinstance(org_id, str) or not org_id:
            raise HTTPException(status_code=400, detail="Slack action is missing org_id.")
        if not settings.slack_bot_token:
            return {
                "response_type": "ephemeral",
                "text": "Slack bot token is not configured, so Vigil cannot open follow-up.",
            }
        backends = create_backends()
        if backends.decisions is None:
            raise HTTPException(status_code=503, detail="Decision store is not configured.")
        decision = await backends.decisions.get(analysis_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="Impact decision was not found.")
        try:
            _assert_slack_decision_access(payload, action_value, decision)
        except RuntimeError as error:
            await _post_slack_response(payload, str(error))
            return {"status": "rejected", "action_id": action_id, "detail": str(error)}
        await _open_follow_up_modal(payload, analysis_id=analysis_id, org_id=org_id)
    elif action_id in {"approve_ticket", "ask_follow_up", "mark_false_positive"}:
        analysis_id = action_value.get("analysis_id")
        if not isinstance(analysis_id, str) or not analysis_id:
            raise HTTPException(status_code=400, detail="Slack action is missing analysis_id.")
        asyncio.create_task(_process_slack_interaction(payload))

    _log_struct(
        {
            "event": "slack_interaction_queued",
            "action_id": action_id,
            "team_id": (
                payload.get("team", {}).get("id") if isinstance(payload.get("team"), dict) else None
            ),
            "user_id": (
                payload.get("user", {}).get("id") if isinstance(payload.get("user"), dict) else None
            ),
        },
        severity="INFO",
    )
    return {
        "status": "acknowledged",
        "action_id": action_id,
        "approval_status": None,
        "ticket_id": None,
    }


@app.post("/slack/commands")
async def handle_slack_command(request: Request) -> dict:
    """Verify and acknowledge Slack slash commands."""
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

    payload = parse_slack_command_payload(body)
    org_id = slack_org_id(payload)
    text = payload.get("text", "").strip().lower()
    if text not in {"", "onboard", "setup"}:
        return {
            "response_type": "ephemeral",
            "text": "Try `/vigil onboard` to set up Vigil for this workspace.",
        }

    if settings.slack_bot_token and payload.get("trigger_id"):
        await _open_onboarding_modal(payload)
        return {
            "response_type": "ephemeral",
            "text": "Opening Vigil onboarding.",
        }

    return {
        "response_type": "ephemeral",
        "text": "Set up Vigil for this workspace.",
        "blocks": build_onboarding_start_blocks(org_id),
    }


async def _process_slack_interaction(payload: dict) -> None:
    """Process Slack actions after the request has been acknowledged."""
    action_id = slack_action_id(payload)
    action_value = slack_action_value(payload)
    approval_status: str | None = None
    ticket_id: str | None = None

    try:
        if action_id == ONBOARDING_CONFIRM_ACTION_ID:
            proposal_id = _slack_proposal_id(action_value)
            backends = create_backends()
            if backends.org_context is None:
                raise RuntimeError("Org context registry is not configured.")
            proposal = await backends.org_context.get_proposal(proposal_id)
            if proposal is None:
                raise RuntimeError(f"Context update proposal was not found: {proposal_id}")
            if action_value.get("org_id") and action_value.get("org_id") != proposal.org_id:
                raise RuntimeError("Slack onboarding proposal org mismatch.")
            approved = proposal.model_copy(update={"approved": True})
            await backends.org_context.save_proposal(approved)
            result = await backends.org_context.commit_proposal(proposal_id, approved=True)
            if not result.committed:
                raise RuntimeError(result.message)
            await _post_slack_response(
                payload,
                f"Vigil onboarding is complete for `{proposal.org_id}`.",
            )
        elif action_id == "approve_ticket":
            analysis_id = _slack_analysis_id(action_value)
            backends = create_backends()
            if backends.decisions is None:
                raise RuntimeError("Decision store is not configured.")
            decision = await backends.decisions.get(analysis_id)
            if decision is None:
                raise RuntimeError(f"Impact decision was not found: {analysis_id}")
            _assert_slack_decision_access(payload, action_value, decision)
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
        elif action_id == "mark_false_positive":
            analysis_id = _slack_analysis_id(action_value)
            backends = create_backends()
            if backends.decisions is None:
                raise RuntimeError("Decision store is not configured.")
            decision = await backends.decisions.get(analysis_id)
            if decision is None:
                raise RuntimeError(f"Impact decision was not found: {analysis_id}")
            _assert_slack_decision_access(payload, action_value, decision)
            updated = await VigilOrchestrator(backends=backends).record_false_positive(
                decision,
                marked_by=slack_user_id(payload) or "slack-user",
            )
            approval_status = updated.approval_status
            ticket_id = updated.ticket_id
        elif action_id == "ask_follow_up":
            analysis_id = _slack_analysis_id(action_value)
            backends = create_backends()
            if backends.decisions is None:
                raise RuntimeError("Decision store is not configured.")
            decision = await backends.decisions.get(analysis_id)
            if decision is None:
                raise RuntimeError(f"Impact decision was not found: {analysis_id}")
            _assert_slack_decision_access(payload, action_value, decision)
            await VigilOrchestrator(backends=backends).record_follow_up_requested(
                decision,
                requested_by=slack_user_id(payload) or "slack-user",
            )
            await _post_slack_response(
                payload,
                "Vigil recorded the follow-up request. This decision remains pending review.",
            )
    except Exception as error:
        logger.exception("Slack interaction processing failed")
        await _post_slack_response(
            payload,
            f"Vigil could not complete `{action_id}`: {error}",
        )
        _log_struct(
            {
                "event": "slack_interaction_failed",
                "action_id": action_id,
                "error": str(error),
            },
            severity="ERROR",
        )
        return

    if action_id == "approve_ticket":
        await _post_slack_response(
            payload,
            f"Vigil approved this decision and created ticket `{ticket_id}`.",
        )
    elif action_id == "mark_false_positive":
        await _post_slack_response(
            payload,
            "Vigil recorded this decision as a false positive for future suppression.",
        )

    _log_struct(
        {
            "event": "slack_interaction_processed",
            "action_id": action_id,
            "approval_status": approval_status,
            "ticket_id": ticket_id,
            "team_id": (
                payload.get("team", {}).get("id") if isinstance(payload.get("team"), dict) else None
            ),
            "user_id": (
                payload.get("user", {}).get("id") if isinstance(payload.get("user"), dict) else None
            ),
        },
        severity="INFO",
    )


async def _handle_slack_view_submission(payload: dict) -> dict:
    view = payload.get("view") if isinstance(payload.get("view"), dict) else {}
    if not get_settings().slack_bot_token:
        return _slack_processing_view(
            title="Setup issue",
            message="SLACK_BOT_TOKEN is required so Vigil can update Slack modals.",
        )
    if view.get("callback_id") == ONBOARDING_CONFIRM_CALLBACK_ID:
        asyncio.create_task(_process_slack_onboarding_confirmation(payload))
        return _slack_processing_view(
            title="Approving setup",
            message="Vigil is committing the approved onboarding profile.",
        )
    if view.get("callback_id") == FOLLOW_UP_CALLBACK_ID:
        asyncio.create_task(_process_slack_follow_up_submission(payload))
        return _slack_processing_view(
            title="Saving follow-up",
            message="Vigil is recording this follow-up request.",
        )
    if view.get("callback_id") != ONBOARDING_CALLBACK_ID:
        return {"response_action": "clear"}

    asyncio.create_task(_process_slack_onboarding_submission(payload))
    return _slack_processing_view(
        title="Preparing review",
        message="Vigil is saving your onboarding draft and preparing the review step.",
    )


async def _process_slack_onboarding_submission(payload: dict) -> None:
    view_id = _slack_view_id(payload)
    try:
        submission = parse_onboarding_submission(payload)
        updates = onboarding_context_updates(submission)
        if not updates:
            await _update_slack_modal(
                view_id,
                _slack_message_view(
                    title="Setup issue",
                    message="Enter at least one onboarding value.",
                    callback_id="vigil_onboarding_error",
                ),
            )
            return
        backends = create_backends()
        if backends.org_context is None:
            raise RuntimeError("Org context registry is not configured.")
        proposal = await build_context_update_proposal(
            backends.org_context,
            org_id=submission["org_id"],
            summary="Slack onboarding captured organization context and review preferences.",
            updates=updates,
            requested_by=submission.get("requested_by"),
            approved=False,
        )
    except ValueError as error:
        await _update_slack_modal(
            view_id,
            _slack_message_view(
                title="Setup issue",
                message=str(error),
                callback_id="vigil_onboarding_error",
            ),
        )
        return
    except Exception as error:
        logger.exception("Slack onboarding submission failed")
        await _update_slack_modal(
            view_id,
            _slack_message_view(
                title="Setup issue",
                message=f"Vigil could not save onboarding: {error}",
                callback_id="vigil_onboarding_error",
            ),
        )
        return

    await _update_slack_modal(
        view_id,
        {
            "type": "modal",
            "callback_id": ONBOARDING_CONFIRM_CALLBACK_ID,
            "private_metadata": onboarding_confirmation_metadata(proposal),
            "title": {"type": "plain_text", "text": "Review setup"},
            "submit": {"type": "plain_text", "text": "Approve setup"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": build_onboarding_confirmation_blocks(proposal),
        },
    )


async def _process_slack_onboarding_confirmation(payload: dict) -> None:
    view_id = _slack_view_id(payload)
    ids = onboarding_confirmation_ids(payload)
    proposal_id = ids["proposal_id"]
    if not proposal_id:
        await _update_slack_modal(
            view_id,
            _slack_message_view(
                title="Setup issue",
                message="Vigil could not find the onboarding proposal.",
                callback_id="vigil_onboarding_error",
            ),
        )
        return
    try:
        backends = create_backends()
        if backends.org_context is None:
            raise RuntimeError("Org context registry is not configured.")
        proposal = await backends.org_context.get_proposal(proposal_id)
        if proposal is None:
            raise RuntimeError(f"Context update proposal was not found: {proposal_id}")
        if ids["org_id"] and ids["org_id"] != proposal.org_id:
            raise RuntimeError("Slack onboarding proposal org mismatch.")
        approved = proposal.model_copy(update={"approved": True})
        await backends.org_context.save_proposal(approved)
        result = await backends.org_context.commit_proposal(proposal_id, approved=True)
        if not result.committed:
            raise RuntimeError(result.message)
    except Exception as error:
        logger.exception("Slack onboarding confirmation failed")
        await _update_slack_modal(
            view_id,
            _slack_message_view(
                title="Setup issue",
                message=f"Vigil could not approve onboarding: {error}",
                callback_id="vigil_onboarding_error",
            ),
        )
        return

    await _update_slack_modal(
        view_id,
        {
            "type": "modal",
            "callback_id": "vigil_onboarding_complete",
            "title": {"type": "plain_text", "text": "Setup complete"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": build_onboarding_complete_blocks(proposal.org_id),
        },
    )


def _slack_processing_view(title: str, message: str) -> dict:
    return {
        "response_action": "update",
        "view": _slack_message_view(
            title=title,
            message=message,
            callback_id="vigil_processing",
        ),
    }


def _slack_message_view(title: str, message: str, callback_id: str) -> dict:
    return {
            "type": "modal",
            "callback_id": callback_id,
            "title": {"type": "plain_text", "text": title[:24]},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                }
            ],
    }


async def _process_slack_follow_up_submission(payload: dict) -> None:
    view_id = _slack_view_id(payload)
    submission = parse_follow_up_submission(payload)
    analysis_id = submission["analysis_id"]
    if not analysis_id:
        await _update_slack_modal(
            view_id,
            _slack_message_view(
                title="Follow-up issue",
                message="Vigil could not find the decision for this follow-up.",
                callback_id="vigil_follow_up_error",
            ),
        )
        return
    try:
        backends = create_backends()
        if backends.decisions is None:
            raise RuntimeError("Decision store is not configured.")
        decision = await backends.decisions.get(analysis_id)
        if decision is None:
            raise RuntimeError(f"Impact decision was not found: {analysis_id}")
        _assert_slack_decision_access(
            payload,
            {"org_id": submission["org_id"], "analysis_id": analysis_id},
            decision,
        )
        await VigilOrchestrator(backends=backends).record_follow_up_requested(
            decision,
            requested_by=submission["requested_by"] or "slack-user",
            note=submission["note"],
        )
        if submission["response_url"]:
            await _post_response_url(
                submission["response_url"],
                "Vigil recorded the follow-up request. This decision remains pending review.",
            )
    except Exception as error:
        logger.exception("Slack follow-up submission failed")
        await _update_slack_modal(
            view_id,
            _slack_message_view(
                title="Follow-up issue",
                message=f"Vigil could not record the follow-up: {error}",
                callback_id="vigil_follow_up_error",
            ),
        )
        return

    await _update_slack_modal(
        view_id,
        {
            "type": "modal",
            "callback_id": "vigil_follow_up_complete",
            "title": {"type": "plain_text", "text": "Follow-up saved"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": build_follow_up_complete_blocks(analysis_id),
        },
    )


async def _open_onboarding_modal(payload: dict) -> None:
    trigger_id = slack_trigger_id(payload)
    if not trigger_id:
        raise HTTPException(status_code=400, detail="Slack payload is missing trigger_id.")
    settings = get_settings()
    client = WebClient(token=settings.slack_bot_token)
    view = build_onboarding_modal(
        org_id=slack_org_id(payload),
        channel_id=slack_channel_id(payload),
        user_id=slack_user_id(payload) or payload.get("user_id"),
        team_id=slack_team_id(payload),
        enterprise_id=slack_enterprise_id(payload),
    )
    try:
        await asyncio.to_thread(client.views_open, trigger_id=trigger_id, view=view)
    except SlackApiError as error:
        raise HTTPException(
            status_code=502,
            detail=f"Slack onboarding modal failed: {error.response.get('error', 'unknown_error')}",
        ) from error


async def _open_follow_up_modal(payload: dict, *, analysis_id: str, org_id: str) -> None:
    trigger_id = slack_trigger_id(payload)
    if not trigger_id:
        raise HTTPException(status_code=400, detail="Slack payload is missing trigger_id.")
    settings = get_settings()
    client = WebClient(token=settings.slack_bot_token)
    view = build_follow_up_modal(
        analysis_id=analysis_id,
        org_id=org_id,
        response_url=payload.get("response_url") if isinstance(payload.get("response_url"), str) else None,
    )
    try:
        await asyncio.to_thread(client.views_open, trigger_id=trigger_id, view=view)
    except SlackApiError as error:
        raise HTTPException(
            status_code=502,
            detail=f"Slack follow-up modal failed: {error.response.get('error', 'unknown_error')}",
        ) from error


async def _update_slack_modal(view_id: str | None, view: dict) -> None:
    if not view_id:
        logger.warning("Slack modal update skipped because view_id is missing.")
        return
    settings = get_settings()
    if not settings.slack_bot_token:
        logger.warning("Slack modal update skipped because SLACK_BOT_TOKEN is not configured.")
        return
    client = WebClient(token=settings.slack_bot_token)
    try:
        await asyncio.to_thread(client.views_update, view_id=view_id, view=view)
    except SlackApiError as error:
        logger.warning(
            "Slack modal update failed: %s",
            error.response.get("error", "unknown_error"),
        )


def _slack_view_id(payload: dict) -> str | None:
    view = payload.get("view")
    if not isinstance(view, dict):
        return None
    view_id = view.get("id")
    return str(view_id) if view_id else None


def _assert_slack_decision_access(payload: dict, action_value: dict, decision) -> None:
    action_org_id = action_value.get("org_id")
    if isinstance(action_org_id, str) and action_org_id and action_org_id != decision.org_id:
        raise RuntimeError("Slack action org does not match the stored decision.")
    resolved_org_id = slack_org_id(payload)
    if resolved_org_id != "default-org" and resolved_org_id != decision.org_id:
        raise RuntimeError("Slack workspace is not authorized for this decision.")
    reviewer = slack_user_id(payload)
    if decision.reviewer_user_ids and reviewer not in decision.reviewer_user_ids:
        raise RuntimeError("Slack user is not an authorized reviewer for this decision.")


def _slack_analysis_id(action_value: dict) -> str:
    analysis_id = action_value.get("analysis_id")
    if not isinstance(analysis_id, str) or not analysis_id:
        raise RuntimeError("Slack action is missing analysis_id.")
    return analysis_id


def _slack_proposal_id(action_value: dict) -> str:
    proposal_id = action_value.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id:
        raise RuntimeError("Slack action is missing proposal_id.")
    return proposal_id


async def _post_slack_response(payload: dict, text: str) -> None:
    response_url = payload.get("response_url")
    if not isinstance(response_url, str) or not response_url:
        return
    await _post_response_url(response_url, text)


async def _post_response_url(response_url: str, text: str) -> None:
    body = json.dumps(
        {
            "response_type": "ephemeral",
            "replace_original": False,
            "text": text,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        response_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        await asyncio.to_thread(urllib.request.urlopen, request, timeout=5)
    except (urllib.error.URLError, TimeoutError) as error:
        logger.warning("Slack response_url update failed: %s", error)


def _log_struct(payload: dict, severity: str = "INFO") -> None:
    if struct_logger is not None:
        struct_logger.log_struct(payload, severity=severity)
        return
    level = getattr(logging, severity.upper(), logging.INFO)
    logger.log(level, json.dumps(payload, sort_keys=True, default=str))


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

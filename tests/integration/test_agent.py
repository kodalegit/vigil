import importlib.metadata

from google.adk.workflow import Workflow

from vigil.agent import (
    analyze_regulatory_sources,
    app,
    approve_impact_decision,
    commit_approved_context_update,
    get_current_profile,
    map_enterprise_context,
    propose_context_update,
    root_agent,
    run_regulatory_impact_analysis,
    search_org_memory,
    validate_context_update,
)


def test_agent_is_vigil_app() -> None:
    assert app.name == "vigil"
    assert root_agent.name == "vigil_orchestrator"


def test_adk_2_runtime_is_available() -> None:
    major_version = int(importlib.metadata.version("google-adk").split(".", 1)[0])

    assert major_version >= 2
    assert Workflow.__name__ == "Workflow"


def test_orchestrator_uses_agent_tool_specialists() -> None:
    tool_names = {getattr(tool, "name", "") for tool in root_agent.tools}

    assert "source_monitoring_agent" in tool_names
    assert "enterprise_context_agent" in tool_names
    assert "run_regulatory_impact_analysis" not in tool_names


def test_context_and_memory_tools_are_exposed_on_root_agent() -> None:
    tool_names = {getattr(tool, "name", "") for tool in root_agent.tools}

    assert {
        "get_current_profile",
        "approve_impact_decision",
        "propose_context_update",
        "validate_context_update",
        "commit_approved_context_update",
        "search_org_memory",
        "write_approved_memory",
    }.issubset(tool_names)


async def test_specialist_tools_return_structured_context() -> None:
    source_result = await analyze_regulatory_sources(
        query="EU AI Act high-risk AI deployer obligations"
    )
    enterprise_result = await map_enterprise_context(
        query="EU AI Act high-risk AI deployer obligations",
        source_findings=source_result["source_findings"],
    )

    assert source_result["source_findings"]
    assert enterprise_result["enterprise_findings"]
    finding = enterprise_result["enterprise_findings"][0]
    assert finding["chunks"]
    assert finding["mappings"]
    assert finding["relevant_docs"]


async def test_enterprise_context_tolerates_loose_llm_source_findings() -> None:
    result = await map_enterprise_context(
        query="EU AI Act high-risk AI deployer obligations",
        source_findings=[
            {
                "finding": "Maintain documented human oversight procedures.",
                "confidence": "high",
            }
        ],
    )

    assert result["enterprise_findings"]
    assert result["enterprise_findings"][0]["chunks"]


async def test_regulatory_impact_tool_returns_eu_ai_act_decision() -> None:
    decision = await run_regulatory_impact_analysis(
        query="EU AI Act high-risk AI deployer obligations"
    )

    assert decision["is_actionable"] is True
    assert decision["classification"] == "actionable"
    assert decision["risk_level"] == "high"
    assert "EU AI Act" in decision["summary"]
    assert decision["approval_required"] is True
    assert decision["approval_status"] == "pending"
    assert decision["ticket_status"] == "blocked_pending_approval"
    assert decision["source_findings"]
    assert decision["enterprise_findings"]
    assert decision["enterprise_findings"][0]["chunks"]
    assert decision["action_results"]
    assert any(result["action"] == "create_ticket" for result in decision["action_results"])
    assert any(event["event_type"] == "ticket_blocked" for event in decision["audit_events"])


async def test_approval_tool_creates_ticket_after_human_approval() -> None:
    decision = await run_regulatory_impact_analysis(
        query="EU AI Act high-risk AI deployer obligations"
    )

    approved = await approve_impact_decision(
        decision,
        approved_by="compliance-lead",
        idempotency_key="ticket:integration-approval",
    )
    replay = await approve_impact_decision(
        approved,
        approved_by="compliance-lead",
        idempotency_key="ticket:integration-approval",
    )

    assert approved["approval_status"] == "approved"
    assert approved["ticket_status"] == "created"
    assert approved["ticket_id"]
    assert replay["ticket_id"] == approved["ticket_id"]
    assert any(event["event_type"] == "ticket_created" for event in approved["audit_events"])


async def test_context_tools_require_approval_before_commit_and_memory_write() -> None:
    org_id = "integration-context-org"
    proposal_result = await propose_context_update(
        org_id=org_id,
        requested_by="reviewer-1",
        summary="Route regulatory alerts to legal review.",
        jurisdictions="European Union, United States",
        slack_channel="#legal-review",
        memory_topic="notification_preferences",
        memory_text="Send AI governance alerts to #legal-review.",
        approved=False,
    )
    proposal = proposal_result["proposal"]

    validation = await validate_context_update(proposal["proposal_id"])
    rejected_commit = await commit_approved_context_update(
        proposal["proposal_id"],
        approved=False,
    )
    approved_commit = await commit_approved_context_update(
        proposal["proposal_id"],
        approved=True,
    )
    profile = await get_current_profile(org_id=org_id)
    memories = await search_org_memory(
        org_id=org_id,
        user_id="reviewer-1",
        query="AI governance legal review",
        topics="notification_preferences",
    )

    assert validation["valid"] is True
    assert rejected_commit["committed"] is False
    assert approved_commit["committed"] is True
    assert profile["org_context"]["slack_preferences"]["default_channel"] == "#legal-review"
    assert approved_commit["memories_written"]
    assert memories["memories"]

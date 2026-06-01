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


def test_root_agent_only_exposes_core_monitoring_tools() -> None:
    tool_names = {getattr(tool, "name", "") for tool in root_agent.tools}

    assert tool_names == {"source_monitoring_agent", "enterprise_context_agent"}
    assert not {
        "get_current_profile",
        "approve_impact_decision",
        "propose_context_update",
        "validate_context_update",
        "commit_approved_context_update",
        "search_org_memory",
        "write_approved_memory",
    } & tool_names


def test_root_agent_instruction_matches_actual_orchestration_boundary() -> None:
    instruction = root_agent.instruction

    assert "source_monitoring_agent" in instruction
    assert "enterprise_context_agent" in instruction
    assert "core monitoring and reconciliation loop" in instruction
    assert "Do not create tickets, write memory" in instruction
    assert "application handlers" in instruction
    assert "get_current_profile" not in instruction
    assert "context update proposal" not in instruction
    assert "Python VigilOrchestrator service" not in instruction


async def test_specialist_tools_return_structured_context() -> None:
    source_result = await analyze_regulatory_sources(
        query="EU AI Act high-risk AI deployer obligations"
    )
    enterprise_result = await map_enterprise_context(
        query="EU AI Act high-risk AI deployer obligations",
        source_findings=source_result["source_findings"],
    )

    assert source_result["source_findings"]
    assert source_result["org_context_summary"]
    assert "Organization:" in source_result["org_context_summary"]
    assert enterprise_result["enterprise_findings"]
    assert enterprise_result["org_context_summary"]
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


async def test_profile_tool_reports_incomplete_onboarding_for_new_org() -> None:
    profile = await get_current_profile(org_id="new-onboarding-org")

    status = profile["onboarding_status"]
    assert status["is_configured_for_monitoring"] is False
    assert "profile.jurisdictions" in status["missing_required_fields"]
    assert "source_policy.allowlisted_sources" in status["missing_required_fields"]
    assert "monitoring_profiles" in status["missing_required_fields"]


async def test_context_tool_can_onboard_monitoring_and_retrieval_resources() -> None:
    org_id = "integration-onboarding-resource-org"
    proposal_result = await propose_context_update(
        org_id=org_id,
        requested_by="reviewer-1",
        summary="Configure production monitoring context.",
        display_name="Example Financial Group",
        sectors="financial services",
        products="credit decisioning",
        business_model="Regulated lender using automated decision support.",
        jurisdictions="United States",
        slack_channel="#compliance-review",
        source_name="Primary regulator updates",
        source_url="https://www.regulator.example/updates",
        source_jurisdictions="United States",
        source_domains="financial compliance",
        source_regulators="Primary regulator",
        source_freshness_days=14,
        monitoring_query="New lending compliance obligations",
        monitoring_cadence="weekly",
        retrieval_source_type="rag_engine",
        rag_corpus="projects/example/locations/us-central1/ragCorpora/123",
        approved=False,
    )
    proposal = proposal_result["proposal"]

    validation = await validate_context_update(proposal["proposal_id"])
    approved_commit = await commit_approved_context_update(
        proposal["proposal_id"],
        approved=True,
    )
    profile = await get_current_profile(org_id=org_id)

    assert validation["valid"] is True
    assert approved_commit["committed"] is True
    context = profile["org_context"]
    assert context["monitoring_profiles"][0]["query"] == "New lending compliance obligations"
    assert context["retrieval_resources"][0]["source_type"] == "rag_engine"
    assert context["source_policy"]["allowlisted_sources"][0]["freshness_days"] == 14
    assert profile["onboarding_status"]["is_configured_for_monitoring"] is True

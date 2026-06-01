import os

import google.auth
import google.auth.exceptions
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.tools import agent_tool

from vigil.agents import VigilOrchestrator
from vigil.backends import create_backends
from vigil.backends.org_context import build_context_update_proposal
from vigil.context import ContextCompiler
from vigil.schemas import (
    AuditEvent,
    ImpactDecision,
    MemoryTopic,
    MemoryWriteProposal,
    MonitoringInstruction,
    OrgContext,
    SourceFinding,
    TrustedSource,
)
from vigil.settings import get_settings

settings = get_settings()


def configure_google_model_auth() -> None:
    if settings.google_api_key:
        os.environ.setdefault("GOOGLE_API_KEY", settings.google_api_key)
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "False")
        return

    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.google_cloud_location)

    if settings.google_cloud_project:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.google_cloud_project)
        return

    try:
        _, project_id = google.auth.default()
    except google.auth.exceptions.DefaultCredentialsError:
        return

    if project_id:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)


configure_google_model_auth()


def _parse_sources(sources: str | None) -> list[str]:
    if not sources:
        return []
    return [source.strip() for source in sources.split(",") if source.strip()]


async def analyze_regulatory_sources(
    query: str,
    jurisdiction: str | None = None,
    domain: str | None = None,
    sources: str | None = None,
    org_id: str = "default-org",
    user_id: str | None = None,
) -> dict:
    """Extract regulatory changes and obligations from trusted sources.

    Args:
        query: Regulatory change, topic, or monitoring instruction to investigate.
        jurisdiction: Jurisdiction to focus on.
        domain: Compliance domain to focus on.
        sources: Optional comma-separated source URLs or source names.

    Returns:
        Source findings with obligation text, citations, and confidence scores.
    """
    instruction = MonitoringInstruction(
        query=query,
        jurisdiction=jurisdiction,
        domain=domain,
        sources=_parse_sources(sources),
        org_id=org_id,
        user_id=user_id,
    )
    backends = create_backends()
    assert backends.org_context is not None
    assert backends.memory is not None
    context_pack = await ContextCompiler(
        registry=backends.org_context,
        memory=backends.memory,
    ).compile(instruction)
    findings = await backends.source.search(context_pack.instruction)
    return {
        "source_findings": [finding.model_dump(mode="json") for finding in findings],
        "org_context_summary": context_pack.instruction.org_context_summary,
        "context_provenance": [
            item.model_dump(mode="json") for item in context_pack.provenance
        ],
    }


async def map_enterprise_context(
    query: str,
    source_findings: list[dict] | None = None,
    jurisdiction: str | None = None,
    domain: str | None = None,
    sources: str | None = None,
    org_id: str = "default-org",
    user_id: str | None = None,
) -> dict:
    """Map regulatory obligations to internal policies, controls, and SOPs.

    Args:
        query: Regulatory change, topic, or monitoring instruction to investigate.
        source_findings: Source findings from the source monitoring agent.
        jurisdiction: Jurisdiction to focus on.
        domain: Compliance domain to focus on.

    Returns:
        Enterprise findings with affected artifacts, snippets, citations, and confidence scores.
    """
    instruction = MonitoringInstruction(
        query=query,
        jurisdiction=jurisdiction,
        domain=domain,
        sources=_parse_sources(sources),
        org_id=org_id,
        user_id=user_id,
    )
    parsed_source_findings = _parse_source_finding_dicts(source_findings)
    backends = create_backends()
    assert backends.org_context is not None
    assert backends.memory is not None
    context_pack = await ContextCompiler(
        registry=backends.org_context,
        memory=backends.memory,
    ).compile(instruction)
    findings = await backends.retrieval.search(
        context_pack.instruction, parsed_source_findings
    )
    return {
        "enterprise_findings": [
            finding.model_dump(mode="json") for finding in findings
        ],
        "org_context_summary": context_pack.instruction.org_context_summary,
        "context_provenance": [
            item.model_dump(mode="json") for item in context_pack.provenance
        ],
    }


async def run_regulatory_impact_analysis(
    query: str,
    jurisdiction: str | None = None,
    domain: str | None = None,
    sources: str | None = None,
    org_id: str = "default-org",
    user_id: str | None = None,
) -> dict:
    """Run Vigil's local regulatory impact loop.

    Args:
        query: Regulatory change, topic, or monitoring instruction to investigate.
        jurisdiction: Jurisdiction to focus on.
        domain: Compliance domain to focus on.

    Returns:
        A structured impact decision with source evidence, enterprise mappings,
        recommended actions, and simulated Slack/report actions.
    """
    instruction = MonitoringInstruction(
        query=query,
        jurisdiction=jurisdiction,
        domain=domain,
        sources=_parse_sources(sources),
        org_id=org_id,
        user_id=user_id,
    )
    decision = await VigilOrchestrator().analyze(instruction)
    return decision.model_dump(mode="json")


async def approve_impact_decision(
    decision: dict,
    approved_by: str,
    approved: bool = True,
    idempotency_key: str | None = None,
) -> dict:
    """Record human approval or rejection for a pending impact decision.

    Args:
        decision: Impact decision returned by run_regulatory_impact_analysis.
        approved_by: Human reviewer identifier.
        approved: Whether the reviewer approved remediation ticket creation.
        idempotency_key: Optional key to make approval/ticket creation replay-safe.

    Returns:
        Updated impact decision with approval, ticket, action, and audit state.
    """
    parsed_decision = ImpactDecision.model_validate(decision)
    approved_decision = await VigilOrchestrator().record_approval(
        parsed_decision,
        approved_by=approved_by,
        approved=approved,
        idempotency_key=idempotency_key,
    )
    return approved_decision.model_dump(mode="json")


async def get_current_profile(org_id: str = "default-org") -> dict:
    """Get the approved organization context registry profile.

    Args:
        org_id: Organization identifier.

    Returns:
        The approved org profile, source policy, Slack preferences, monitoring
        profiles, and obligation inventory.
    """
    backends = create_backends()
    assert backends.org_context is not None
    context = await backends.org_context.get_context(org_id)
    return {
        "org_context": context.model_dump(mode="json"),
        "onboarding_status": _onboarding_status(context),
    }


async def propose_context_update(
    summary: str,
    org_id: str = "default-org",
    requested_by: str | None = None,
    display_name: str | None = None,
    sectors: str | None = None,
    products: str | None = None,
    business_model: str | None = None,
    jurisdictions: str | None = None,
    risk_tolerance: str | None = None,
    slack_channel: str | None = None,
    reviewers: str | None = None,
    source_name: str | None = None,
    source_url: str | None = None,
    source_jurisdictions: str | None = None,
    source_domains: str | None = None,
    source_regulators: str | None = None,
    source_freshness_days: int | None = None,
    monitoring_query: str | None = None,
    monitoring_cadence: str | None = None,
    retrieval_source_type: str | None = None,
    rag_corpus: str | None = None,
    drive_folder_id: str | None = None,
    gcs_uri: str | None = None,
    memory_text: str | None = None,
    memory_topic: str = "other",
    approved: bool = False,
) -> dict:
    """Draft an organization context update for human review.

    Args:
        summary: Human-readable summary of the proposed change.
        org_id: Organization identifier.
        requested_by: User who requested the change.
        display_name: Optional organization display name.
        sectors: Optional comma-separated sectors.
        products: Optional comma-separated products or systems.
        business_model: Optional business model context.
        jurisdictions: Optional comma-separated jurisdictions.
        risk_tolerance: Optional low, medium, high, or critical value.
        slack_channel: Optional default Slack review channel.
        reviewers: Optional comma-separated Slack reviewer user IDs.
        source_name: Optional allowlisted source name.
        source_url: Optional allowlisted source URL.
        source_jurisdictions: Optional comma-separated source jurisdictions.
        source_domains: Optional comma-separated source domains.
        source_regulators: Optional comma-separated source regulators.
        source_freshness_days: Optional freshness window for this source.
        monitoring_query: Optional first recurring monitoring query.
        monitoring_cadence: Optional monitoring cadence such as daily, weekly, or monthly.
        retrieval_source_type: Optional rag_engine, drive, or gcs retrieval resource type.
        rag_corpus: Optional RAG Engine corpus resource name.
        drive_folder_id: Optional Google Drive folder ID.
        gcs_uri: Optional Cloud Storage URI.
        memory_text: Optional approved-memory draft to write only after commit.
        memory_topic: Memory topic for the optional memory draft.
        approved: Whether the human has explicitly approved this proposal.

    Returns:
        A stored proposal with a diff and approval state.
    """
    backends = create_backends()
    assert backends.org_context is not None
    assert backends.memory is not None
    current = await backends.org_context.get_context(org_id)
    updates: dict = {}
    profile_updates = {
        key: value
        for key, value in {
            "display_name": display_name,
            "sectors": _parse_csv(sectors),
            "products": _parse_csv(products),
            "business_model": business_model,
            "jurisdictions": _parse_csv(jurisdictions),
            "risk_tolerance": risk_tolerance,
        }.items()
        if value not in (None, [])
    }
    if profile_updates:
        updates["profile"] = profile_updates

    slack_updates = {
        key: value
        for key, value in {
            "default_channel": slack_channel,
            "reviewer_user_ids": _parse_csv(reviewers),
        }.items()
        if value not in (None, [])
    }
    if slack_updates:
        updates["slack_preferences"] = slack_updates

    if source_name and source_url:
        source = TrustedSource(
            source_id=_slug(source_name),
            name=source_name,
            url=source_url,
            jurisdictions=_parse_csv(source_jurisdictions),
            domains=_parse_csv(source_domains),
            regulators=_parse_csv(source_regulators),
            trust_level="trusted",
            freshness_days=source_freshness_days,
        )
        source_policy = current.source_policy.model_copy(deep=True)
        sources = [
            item for item in source_policy.allowlisted_sources if item.url != source.url
        ]
        sources.append(source)
        updates["source_policy"] = {
            "allowlisted_sources": [item.model_dump(mode="python") for item in sources]
        }

    if monitoring_query:
        source_id = _slug(source_name) if source_name else ""
        updates["monitoring_profiles"] = [
            {
                "profile_id": _slug(monitoring_query)[:64] or "default-monitoring",
                "name": monitoring_query,
                "query": monitoring_query,
                "jurisdictions": _parse_csv(jurisdictions),
                "domains": _parse_csv(source_domains),
                "cadence": monitoring_cadence or "weekly",
                "threshold": "medium",
                "source_ids": [source_id] if source_id else [],
                "enabled": True,
            }
        ]

    retrieval_updates = _retrieval_resource_updates(
        retrieval_source_type=retrieval_source_type,
        rag_corpus=rag_corpus,
        drive_folder_id=drive_folder_id,
        gcs_uri=gcs_uri,
    )
    if retrieval_updates:
        updates["retrieval_resources"] = retrieval_updates

    memory_writes = []
    if memory_text:
        memory_writes.append(
            MemoryWriteProposal(
                topic=_memory_topic(memory_topic),
                text=memory_text,
                org_id=org_id,
                user_id=requested_by,
                approved=approved,
            )
        )

    proposal = await build_context_update_proposal(
        backends.org_context,
        org_id=org_id,
        summary=summary,
        updates=updates,
        requested_by=requested_by,
        memory_writes=memory_writes,
        approved=approved,
    )
    await backends.audit.record(
        AuditEvent(
            event_type="context_proposal_drafted",
            message="Drafted organization context update proposal.",
            metadata={"proposal_id": proposal.proposal_id, "org_id": org_id},
        )
    )
    return {"proposal": proposal.model_dump(mode="json")}


async def validate_context_update(proposal_id: str) -> dict:
    """Validate a stored organization context update proposal.

    Args:
        proposal_id: Proposal identifier returned by propose_context_update.

    Returns:
        Validation errors, if any.
    """
    registry = create_backends().org_context
    assert registry is not None
    proposal = await registry.get_proposal(proposal_id)
    if not proposal:
        return {"valid": False, "errors": ["Proposal not found."]}
    errors = await registry.validate_proposal(proposal)
    return {"valid": not errors, "errors": errors, "proposal_id": proposal_id}


async def commit_approved_context_update(
    proposal_id: str, approved: bool = False
) -> dict:
    """Commit a human-approved org context proposal and its approved memories.

    Args:
        proposal_id: Proposal identifier returned by propose_context_update.
        approved: True only after explicit human approval.

    Returns:
        Commit result and any memories written.
    """
    backends = create_backends()
    assert backends.org_context is not None
    assert backends.memory is not None
    proposal = await backends.org_context.get_proposal(proposal_id)
    if not proposal:
        return {
            "committed": False,
            "message": "Context update proposal was not found.",
            "memories_written": [],
        }
    if approved:
        proposal = proposal.model_copy(update={"approved": True})
        await backends.org_context.save_proposal(proposal)
    result = await backends.org_context.commit_proposal(proposal_id, approved=approved)
    memories = []
    if result.committed:
        for memory_proposal in proposal.memory_writes:
            if approved and not memory_proposal.approved:
                memory_proposal = memory_proposal.model_copy(update={"approved": True})
            memories.append(
                (await backends.memory.write_approved(memory_proposal)).model_dump(
                    mode="json"
                )
            )
        await backends.audit.record(
            AuditEvent(
                event_type="context_proposal_approved",
                message="Committed approved organization context update.",
                metadata={
                    "proposal_id": proposal_id,
                    "org_id": proposal.org_id,
                    "memories_written": str(len(memories)),
                },
            )
        )
    return {
        "committed": result.committed,
        "message": result.message,
        "context": result.context.model_dump(mode="json") if result.context else None,
        "memories_written": memories,
    }


async def search_org_memory(
    query: str,
    org_id: str = "default-org",
    user_id: str | None = None,
    topics: str | None = None,
) -> dict:
    """Search approved organization and user memories.

    Args:
        query: Search query.
        org_id: Organization identifier.
        user_id: Optional user identifier for reviewer-specific memories.
        topics: Optional comma-separated memory topics.

    Returns:
        Matching advisory memory records.
    """
    backends = create_backends()
    assert backends.memory is not None
    memories = await backends.memory.search(
        org_id=org_id,
        user_id=user_id,
        query=query,
        topics=_parse_csv(topics) or None,
    )
    return {"memories": [memory.model_dump(mode="json") for memory in memories]}


async def write_approved_memory(
    text: str,
    topic: str = "other",
    org_id: str = "default-org",
    user_id: str | None = None,
    registry_refs: str | None = None,
    approved: bool = False,
) -> dict:
    """Write a durable memory only after explicit approval.

    Args:
        text: Memory text.
        topic: Memory topic.
        org_id: Organization identifier.
        user_id: Optional user identifier.
        registry_refs: Optional comma-separated registry references.
        approved: True only after explicit human approval.

    Returns:
        The written memory record, or an approval error.
    """
    proposal = MemoryWriteProposal(
        topic=_memory_topic(topic),
        text=text,
        org_id=org_id,
        user_id=user_id,
        registry_refs=_parse_csv(registry_refs),
        approved=approved,
    )
    backends = create_backends()
    assert backends.memory is not None
    memory = await backends.memory.write_approved(proposal)
    return {"memory": memory.model_dump(mode="json")}


def _parse_source_finding_dicts(
    source_findings: list[dict] | None,
) -> list[SourceFinding]:
    parsed: list[SourceFinding] = []
    for item in source_findings or []:
        if "source_findings" in item and isinstance(item["source_findings"], list):
            parsed.extend(_parse_source_finding_dicts(item["source_findings"]))
            continue
        try:
            parsed.append(SourceFinding.model_validate(item))
        except ValueError:
            continue
    return parsed


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _retrieval_resource_updates(
    *,
    retrieval_source_type: str | None,
    rag_corpus: str | None,
    drive_folder_id: str | None,
    gcs_uri: str | None,
) -> list[dict]:
    if not any([retrieval_source_type, rag_corpus, drive_folder_id, gcs_uri]):
        return []
    source_type = retrieval_source_type or (
        "rag_engine" if rag_corpus else "drive" if drive_folder_id else "gcs"
    )
    name = (
        "RAG Engine corpus"
        if source_type == "rag_engine"
        else (
            "Google Drive policy folder"
            if source_type == "drive"
            else "Cloud Storage policy prefix"
        )
    )
    return [
        {
            "resource_id": _slug(
                str(rag_corpus or drive_folder_id or gcs_uri or source_type)
            ),
            "name": name,
            "source_type": source_type,
            "rag_corpus": rag_corpus,
            "drive_folder_id": drive_folder_id,
            "gcs_uri": gcs_uri,
            "refresh_cadence": "manual",
            "enabled": True,
        }
    ]


def _memory_topic(value: str) -> MemoryTopic:
    if value == "source_policy":
        return "source_policy"
    if value == "notification_preferences":
        return "notification_preferences"
    if value == "false_positive_patterns":
        return "false_positive_patterns"
    if value == "regulatory_scope":
        return "regulatory_scope"
    if value == "obligation_summaries":
        return "obligation_summaries"
    return "other"


def _slug(value: str) -> str:
    return "-".join(part for part in value.lower().replace("/", " ").split() if part)


def _onboarding_status(context: OrgContext) -> dict:
    missing: list[str] = []
    if not context.profile.jurisdictions:
        missing.append("profile.jurisdictions")
    if not context.source_policy.allowlisted_sources:
        missing.append("source_policy.allowlisted_sources")
    if not any(profile.enabled for profile in context.monitoring_profiles):
        missing.append("monitoring_profiles")
    if not context.slack_preferences.default_channel:
        missing.append("slack_preferences.default_channel")

    optional_missing: list[str] = []
    if not context.profile.sectors and not context.profile.products:
        optional_missing.append("profile.sectors_or_products")
    if not any(resource.enabled for resource in context.retrieval_resources):
        optional_missing.append("retrieval_resources")
    if not context.slack_preferences.reviewer_user_ids:
        optional_missing.append("slack_preferences.reviewer_user_ids")

    return {
        "is_configured_for_monitoring": not missing,
        "missing_required_fields": missing,
        "missing_optional_fields": optional_missing,
        "recommended_next_action": (
            "Draft and review an organization context update before production monitoring."
            if missing
            else "Profile is ready for monitored analysis; review optional fields for production hardening."
        ),
    }


source_monitoring_agent = Agent(
    name="source_monitoring_agent",
    model=settings.vigil_model,
    description=(
        "Extracts trusted regulatory source changes and concise obligation evidence "
        "for a requested jurisdiction and compliance domain."
    ),
    instruction=(
        "You are Vigil's source monitoring and obligation extraction subagent. "
        "For every request, call analyze_regulatory_sources. Return a compact, "
        "cited summary of what changed, obligations, source URLs, confidence, and "
        "remaining uncertainty. Do not map internal enterprise artifacts."
    ),
    tools=[analyze_regulatory_sources],
)

enterprise_context_agent = Agent(
    name="enterprise_context_agent",
    model=settings.vigil_model,
    description=(
        "Maps regulatory obligations to internal policies, controls, SOPs, owners, "
        "and evidence snippets from enterprise context."
    ),
    instruction=(
        "You are Vigil's enterprise context mapping subagent. For every request, "
        "call map_enterprise_context using the regulatory topic and any obligation "
        "evidence provided by the orchestrator. Return affected artifacts, snippets, "
        "citations, confidence, and mapping rationale. Do not make the final risk or "
        "approval decision."
    ),
    tools=[map_enterprise_context],
)

root_agent = Agent(
    name="vigil_orchestrator",
    model=settings.vigil_model,
    instruction=(
        "You are Vigil, an autonomous regulatory impact assistant for enterprise legal, "
        "risk, compliance, and governance teams across regulated domains. Adapt to the "
        "organization's approved context, jurisdictions, source allowlists, monitored "
        "domains, retrieval resources, and reviewer preferences instead of assuming a "
        "specific law, industry, or geography. Approved organization context is compiled "
        "into the specialist tool calls and returned in their results, including profile, "
        "source policy, monitoring scope, and retrieval context. Your job is to run the "
        "core monitoring and reconciliation loop: call source_monitoring_agent to extract "
        "regulatory changes and obligations, call enterprise_context_agent to map those "
        "obligations to internal artifacts, then synthesize the final user-facing answer "
        "with citations, uncertainty, impact classification, and recommended next steps. "
        "Do not present legal advice as final counsel. "
    ),
    tools=[
        agent_tool.AgentTool(agent=source_monitoring_agent),
        agent_tool.AgentTool(agent=enterprise_context_agent),
    ],
)

app = App(
    root_agent=root_agent,
    name="vigil",
)

import os

import google.auth
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.tools import FunctionTool
from google.adk.tools import agent_tool

from vigil.agents import VigilOrchestrator
from vigil.backends import create_backends
from vigil.backends.org_context import build_context_update_proposal
from vigil.schemas import (
    AuditEvent,
    MemoryWriteProposal,
    MonitoringInstruction,
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
        return ["https://artificialintelligenceact.eu/"]
    return [source.strip() for source in sources.split(",") if source.strip()]


async def analyze_regulatory_sources(
    query: str,
    jurisdiction: str = "European Union",
    domain: str = "AI governance",
    sources: str | None = None,
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
    )
    findings = await create_backends().source.search(instruction)
    return {"source_findings": [finding.model_dump(mode="json") for finding in findings]}


async def map_enterprise_context(
    query: str,
    source_findings: list[dict] | None = None,
    jurisdiction: str = "European Union",
    domain: str = "AI governance",
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
        sources=["https://artificialintelligenceact.eu/"],
    )
    parsed_source_findings = _parse_source_finding_dicts(source_findings)
    findings = await create_backends().retrieval.search(instruction, parsed_source_findings)
    return {
        "enterprise_findings": [
            finding.model_dump(mode="json") for finding in findings
        ]
    }


async def run_regulatory_impact_analysis(
    query: str,
    jurisdiction: str = "European Union",
    domain: str = "AI governance",
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
        sources=["https://artificialintelligenceact.eu/"],
    )
    decision = await VigilOrchestrator().analyze(instruction)
    return decision.model_dump(mode="json")


async def get_current_profile(org_id: str = "default-org") -> dict:
    """Get the approved organization context registry profile.

    Args:
        org_id: Organization identifier.

    Returns:
        The approved org profile, source policy, Slack preferences, monitoring
        profiles, and obligation inventory.
    """
    context = await create_backends().org_context.get_context(org_id)
    return {"org_context": context.model_dump(mode="json")}


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
        memory_text: Optional approved-memory draft to write only after commit.
        memory_topic: Memory topic for the optional memory draft.
        approved: Whether the human has explicitly approved this proposal.

    Returns:
        A stored proposal with a diff and approval state.
    """
    backends = create_backends()
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
        )
        source_policy = current.source_policy.model_copy(deep=True)
        sources = [
            item for item in source_policy.allowlisted_sources if item.url != source.url
        ]
        sources.append(source)
        updates["source_policy"] = {
            "allowlisted_sources": [item.model_dump(mode="python") for item in sources]
        }

    memory_writes = []
    if memory_text:
        memory_writes.append(
            MemoryWriteProposal(
                topic=memory_topic,
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
    proposal = await registry.get_proposal(proposal_id)
    if not proposal:
        return {"valid": False, "errors": ["Proposal not found."]}
    errors = await registry.validate_proposal(proposal)
    return {"valid": not errors, "errors": errors, "proposal_id": proposal_id}


async def commit_approved_context_update(proposal_id: str, approved: bool = False) -> dict:
    """Commit a human-approved org context proposal and its approved memories.

    Args:
        proposal_id: Proposal identifier returned by propose_context_update.
        approved: True only after explicit human approval.

    Returns:
        Commit result and any memories written.
    """
    backends = create_backends()
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
                (await backends.memory.write_approved(memory_proposal)).model_dump(mode="json")
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
    memories = await create_backends().memory.search(
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
        topic=topic,
        text=text,
        org_id=org_id,
        user_id=user_id,
        registry_refs=_parse_csv(registry_refs),
        approved=approved,
    )
    memory = await create_backends().memory.write_approved(proposal)
    return {"memory": memory.model_dump(mode="json")}


def _parse_source_finding_dicts(source_findings: list[dict] | None) -> list[SourceFinding]:
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


def _slug(value: str) -> str:
    return "-".join(part for part in value.lower().replace("/", " ").split() if part)


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
        "You are Vigil, an autonomous regulatory impact assistant for lean legal and "
        "compliance teams at mid-size SaaS companies. Your flagship local demo is EU AI "
        "Act governance impact analysis. Use hierarchical task decomposition: first "
        "call source_monitoring_agent to extract regulatory changes and obligations, "
        "then call enterprise_context_agent to map those obligations to internal "
        "artifacts. You own the final synthesis, impact classification, recommended "
        "actions, approval status, and audit narrative. Do not present legal advice "
        "as final counsel. Require human approval before remediation ticket creation. "
        "For onboarding or context refinement, inspect the current profile, draft a "
        "context update proposal, show the diff, validate it, and commit it only after "
        "explicit human approval. Durable memories are advisory and must only be written "
        "from approved context or approved reviewer preferences."
    ),
    tools=[
        agent_tool.AgentTool(agent=source_monitoring_agent),
        agent_tool.AgentTool(agent=enterprise_context_agent),
        FunctionTool(func=get_current_profile),
        FunctionTool(func=propose_context_update),
        FunctionTool(func=validate_context_update),
        FunctionTool(func=commit_approved_context_update),
        FunctionTool(func=search_org_memory),
        FunctionTool(func=write_approved_memory),
    ],
)

app = App(
    root_agent=root_agent,
    name="vigil",
)

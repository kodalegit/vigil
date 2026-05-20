import os

import google.auth
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.tools import agent_tool

from vigil.agents import VigilOrchestrator
from vigil.backends import create_backends
from vigil.schemas import MonitoringInstruction, SourceFinding
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
        "as final counsel. Require human approval before remediation ticket creation."
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

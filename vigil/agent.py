import os

import google.auth
from google.adk.agents import Agent
from google.adk.apps import App

from vigil.agents import VigilOrchestrator
from vigil.schemas import MonitoringInstruction
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


source_monitoring_agent = Agent(
    name="source_monitoring_agent",
    model=settings.vigil_model,
    instruction=(
        "You are Vigil's source monitoring subagent. Identify trusted regulatory "
        "changes and compress them into cited obligations. For the local prototype, "
        "use the regulatory impact analysis tool when evidence is needed."
    ),
    tools=[run_regulatory_impact_analysis],
)

enterprise_context_agent = Agent(
    name="enterprise_context_agent",
    model=settings.vigil_model,
    instruction=(
        "You are Vigil's enterprise context subagent. Map obligations to internal "
        "policies, controls, SOPs, owners, and evidence snippets. Be concise and cite "
        "specific artifacts."
    ),
)

root_agent = Agent(
    name="vigil_orchestrator",
    model=settings.vigil_model,
    instruction=(
        "You are Vigil, an autonomous regulatory impact assistant for lean legal and "
        "compliance teams at mid-size SaaS companies. Your flagship local demo is EU AI "
        "Act governance impact analysis. When a user asks about a regulatory change, "
        "call run_regulatory_impact_analysis, then explain: what changed, why it "
        "matters, affected internal artifacts, recommended actions, approval status, "
        "and audit evidence. Do not present legal advice as final counsel. Require "
        "human approval before remediation ticket creation."
    ),
    tools=[run_regulatory_impact_analysis],
    sub_agents=[source_monitoring_agent, enterprise_context_agent],
)

app = App(
    root_agent=root_agent,
    name="vigil",
)

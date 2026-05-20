from vigil.agent import (
    analyze_regulatory_sources,
    app,
    map_enterprise_context,
    root_agent,
    run_regulatory_impact_analysis,
)


def test_agent_is_vigil_app() -> None:
    assert app.name == "vigil"
    assert root_agent.name == "vigil_orchestrator"


def test_orchestrator_uses_agent_tool_specialists() -> None:
    tool_names = {tool.name for tool in root_agent.tools}

    assert "source_monitoring_agent" in tool_names
    assert "enterprise_context_agent" in tool_names
    assert "run_regulatory_impact_analysis" not in tool_names


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
    assert decision["risk_level"] == "high"
    assert "EU AI Act" in decision["summary"]
    assert decision["source_findings"]
    assert decision["enterprise_findings"]
    assert decision["enterprise_findings"][0]["chunks"]
    assert decision["action_results"]

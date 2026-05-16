from vigil.agent import app, root_agent, run_regulatory_impact_analysis


def test_agent_is_vigil_app() -> None:
    assert app.name == "vigil"
    assert root_agent.name == "vigil_orchestrator"


async def test_regulatory_impact_tool_returns_eu_ai_act_decision() -> None:
    decision = await run_regulatory_impact_analysis(
        query="EU AI Act high-risk AI deployer obligations"
    )

    assert decision["is_actionable"] is True
    assert decision["risk_level"] == "high"
    assert "EU AI Act" in decision["summary"]
    assert decision["source_findings"]
    assert decision["enterprise_findings"]
    assert decision["action_results"]

from vigil.backends.source import MockSourceBackend
from vigil.schemas import MonitoringInstruction


async def test_mock_source_backend_returns_structured_obligations_and_evidence() -> None:
    findings = await MockSourceBackend().search(
        MonitoringInstruction(
            query="EU AI Act high-risk AI deployer obligations",
            jurisdiction="European Union",
            domain="AI governance",
            sources=["https://artificialintelligenceact.eu/"],
        )
    )

    finding = findings[0]
    assert finding.obligations
    assert finding.evidence
    assert finding.citations[0].source_type == "web"
    assert all(obligation.source_quote for obligation in finding.obligations)
    assert all(obligation.jurisdiction == "European Union" for obligation in finding.obligations)

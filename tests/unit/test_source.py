from vigil.backends.source import (
    MockSourceBackend,
    _fallback_obligations_from_grounded_text,
    _parse_obligation_extraction_response,
)
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


def test_parse_obligation_extraction_response_validates_structured_model_output() -> None:
    extraction = _parse_obligation_extraction_response(
        text="""
        {
          "summary": "EU AI Act deployers must document oversight.",
          "confidence": 0.82,
          "uncertainty": "Effective date not present in excerpt.",
          "obligations": [
            {
              "id": "obl-human-oversight",
              "text": "Document human oversight for high-risk AI workflows.",
              "jurisdiction": "European Union",
              "topics": ["human oversight", "AI governance"],
              "risk_level": "high",
              "source_quote": "Deployers shall assign human oversight.",
              "confidence": "high"
            }
          ]
        }
        """,
        instruction=MonitoringInstruction(
            query="EU AI Act deployer obligations",
            jurisdiction="European Union",
            domain="AI governance",
        ),
        default_source_url="https://example.com/source",
    )

    assert extraction.confidence == 0.82
    assert extraction.obligations[0].source_url == "https://example.com/source"
    assert extraction.obligations[0].text == "Document human oversight for high-risk AI workflows."


def test_parse_obligation_extraction_response_accepts_fenced_json() -> None:
    extraction = _parse_obligation_extraction_response(
        text="""
        ```json
        {
          "summary": "Incident reporting duties are discussed.",
          "confidence": 0.7,
          "obligations": [
            {
              "id": "obl-incident-reporting",
              "text": "Escalate AI incidents through the incident response process.",
              "jurisdiction": "European Union",
              "topics": ["incident response"],
              "risk_level": "high",
              "source_quote": "Deployers shall monitor incidents.",
              "confidence": "medium"
            }
          ]
        }
        ```
        """,
        instruction=MonitoringInstruction(
            query="EU AI Act deployer obligations",
            jurisdiction="European Union",
            domain="AI governance",
        ),
        default_source_url="https://example.com/source",
    )

    assert extraction.obligations[0].id == "obl-incident-reporting"


def test_parse_obligation_extraction_response_falls_back_on_invalid_json() -> None:
    extraction = _parse_obligation_extraction_response(
        text="human oversight and evidence retention are discussed",
        instruction=MonitoringInstruction(
            query="EU AI Act deployer obligations",
            jurisdiction="European Union",
            domain="AI governance",
        ),
        default_source_url="https://example.com/source",
    )

    assert extraction.obligations
    assert "fallback" in (extraction.uncertainty or "")


def test_fallback_obligation_extraction_is_low_confidence() -> None:
    extraction = _fallback_obligations_from_grounded_text(
        text="No specific duties are available in this source.",
        instruction=MonitoringInstruction(query="new AI policy update"),
        source_url=None,
    )

    assert extraction.obligations == []
    assert extraction.confidence == 0.2

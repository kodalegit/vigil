from types import SimpleNamespace

from vigil.backends.source import (
    MockSourceBackend,
    _apply_source_quality_guardrails,
    _build_grounded_search_prompt,
    _extract_obligations_with_model,
    _fallback_obligations_from_grounded_text,
    _grounding_evidence,
    _normalize_source_date,
    _parse_obligation_extraction_response,
)
from vigil.schemas import (
    Citation,
    MonitoringInstruction,
    RegulatoryObligation,
    SourceEvidence,
    SourceFinding,
)


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


async def test_mock_source_backend_returns_unrelated_shipping_obligation_for_shipping_query() -> (
    None
):
    findings = await MockSourceBackend().search(
        MonitoringInstruction(
            query="maritime ballast water discharge reporting",
            jurisdiction="European Union",
            domain="shipping compliance",
        )
    )

    assert findings[0].obligations
    assert findings[0].obligations[0].id == "obl-shipping-ballast-reporting"
    assert "ballast water" in findings[0].obligations[0].text


async def test_mock_source_backend_returns_ambiguous_for_consultation_query() -> None:
    findings = await MockSourceBackend().search(
        MonitoringInstruction(query="ambiguous AI governance consultation")
    )

    assert findings[0].obligations == []
    assert findings[0].uncertainty


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


def test_grounded_search_prompt_includes_allowlist_policy() -> None:
    prompt = _build_grounded_search_prompt(
        MonitoringInstruction(
            query="EU AI Act obligations",
            jurisdiction="European Union",
            domain="AI governance",
            sources=["https://official.example/regulation"],
        )
    )

    assert "Configured trusted sources: https://official.example/regulation" in prompt
    assert "Use only these configured trusted sources when possible" in prompt
    assert "do not substitute unrelated sources" in prompt
    assert "Freshness policy" in prompt


def test_grounding_evidence_handles_missing_support_snippets() -> None:
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                grounding_metadata=SimpleNamespace(
                    grounding_chunks=[
                        SimpleNamespace(
                            web=SimpleNamespace(
                                title="Official source",
                                uri="https://official.example/update",
                            )
                        )
                    ],
                    grounding_supports=[],
                )
            )
        ]
    )

    evidence = _grounding_evidence(response)

    assert len(evidence) == 1
    assert evidence[0].title == "Official source"
    assert evidence[0].url == "https://official.example/update"
    assert evidence[0].snippet == "Grounded source returned by Gemini Google Search."


def test_grounding_evidence_normalizes_source_dates_from_snippets() -> None:
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                grounding_metadata=SimpleNamespace(
                    grounding_chunks=[
                        SimpleNamespace(
                            web=SimpleNamespace(
                                title="Official update",
                                uri="https://official.example/update",
                            )
                        )
                    ],
                    grounding_supports=[
                        SimpleNamespace(
                            grounding_chunk_indices=[0],
                            segment=SimpleNamespace(
                                text="Published 12 May 2024. Deployers must monitor systems."
                            ),
                        )
                    ],
                )
            )
        ]
    )

    evidence = _grounding_evidence(response)

    assert evidence[0].published_at == "2024-05-12"


def test_normalize_source_date_accepts_common_web_formats() -> None:
    assert _normalize_source_date("2026-05-26") == "2026-05-26"
    assert _normalize_source_date("May 26, 2026") == "2026-05-26"
    assert _normalize_source_date("26 May 2026") == "2026-05-26"
    assert _normalize_source_date("not a date") is None


def test_source_quality_guardrails_dedupe_and_suppress_stale_obligations() -> None:
    evidence = SourceEvidence(
        title="Old official update",
        url="https://official.example/old-update",
        snippet="Published 1 January 2020. Deployers must monitor systems.",
        published_at="2020-01-01",
    )
    citation = Citation(
        source="https://official.example/old-update",
        title="Old official update",
        snippet=evidence.snippet,
        source_type="web",
        url="https://official.example/old-update",
    )
    finding = SourceFinding(
        summary="Old source found a duty.",
        obligations=[
            RegulatoryObligation(
                id="obl-old-monitoring",
                text="Monitor covered systems.",
                jurisdiction="European Union",
                source_quote=evidence.snippet,
                confidence="medium",
            )
        ],
        evidence=[evidence, evidence],
        citations=[citation, citation],
        confidence=0.8,
    )

    guarded = _apply_source_quality_guardrails(
        finding,
        MonitoringInstruction(
            query="stale source",
            source_freshness_days=30,
        ),
    )

    assert guarded.obligations == []
    assert len(guarded.evidence) == 1
    assert len(guarded.citations) == 1
    assert guarded.confidence == 0.25
    assert "stale" in (guarded.uncertainty or "")


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


async def test_extract_obligations_falls_back_when_model_raises() -> None:
    class FailingModels:
        async def generate_content(self, **kwargs):  # noqa: ANN003
            raise RuntimeError("model unavailable")

    client = SimpleNamespace(aio=SimpleNamespace(models=FailingModels()))
    settings = SimpleNamespace(vigil_model="gemini-2.5-flash")

    extraction = await _extract_obligations_with_model(
        client=client,
        settings=settings,
        instruction=MonitoringInstruction(
            query="EU AI Act deployer obligations",
            jurisdiction="European Union",
            domain="AI governance",
        ),
        grounded_text="Deployers must maintain human oversight and retain logs.",
        evidence=[
            SourceEvidence(
                title="Official source",
                url="https://official.example/ai-act",
                snippet="Deployers must maintain human oversight and retain logs.",
            )
        ],
    )

    assert extraction.obligations
    assert extraction.confidence == 0.45
    assert "fallback" in (extraction.uncertainty or "")


async def test_extract_obligations_includes_org_context_in_model_prompt() -> None:
    class CapturingModels:
        def __init__(self) -> None:
            self.contents = ""

        async def generate_content(self, **kwargs):  # noqa: ANN003
            self.contents = kwargs["contents"]
            return SimpleNamespace(
                text="""
                {
                  "summary": "Privacy duties apply.",
                  "confidence": 0.8,
                  "obligations": [
                    {
                      "id": "obl-privacy-notice",
                      "text": "Maintain privacy notices for covered customer data uses.",
                      "jurisdiction": "United States",
                      "topics": ["privacy"],
                      "risk_level": "medium",
                      "source_quote": "Covered businesses must disclose customer data uses.",
                      "confidence": "high"
                    }
                  ]
                }
                """
            )

    models = CapturingModels()
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    settings = SimpleNamespace(vigil_model="gemini-2.5-flash")

    extraction = await _extract_obligations_with_model(
        client=client,
        settings=settings,
        instruction=MonitoringInstruction(
            query="customer data privacy update",
            jurisdiction="United States",
            domain="privacy",
            org_context_summary=(
                "Organization: Example Financial Group\n"
                "Sectors: financial services\n"
                "Products or systems: credit decisioning"
            ),
        ),
        grounded_text="Covered businesses must disclose customer data uses.",
        evidence=[
            SourceEvidence(
                title="Official privacy source",
                url="https://official.example/privacy",
                snippet="Covered businesses must disclose customer data uses.",
            )
        ],
    )

    assert extraction.obligations
    assert "Organization context:" in models.contents
    assert "Example Financial Group" in models.contents
    assert "credit decisioning" in models.contents
    assert "never invent or discard obligations solely from organization context" in models.contents

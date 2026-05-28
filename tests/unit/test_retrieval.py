from vigil.backends.retrieval import LocalRetrievalBackend
from vigil.schemas import MonitoringInstruction, RegulatoryObligation, RiskLevel, SourceFinding


async def test_local_retrieval_returns_relevant_chunks_for_eu_ai_act_obligations() -> None:
    source_findings = [
        SourceFinding(
            summary="EU AI Act obligations",
            obligations=[
                RegulatoryObligation(
                    id="obl-human-oversight",
                    text="Maintain documented human oversight procedures for high-risk AI workflows.",
                    jurisdiction="European Union",
                    topics=["human oversight", "AI governance"],
                    risk_level=RiskLevel.high,
                    source_quote="Human oversight is required.",
                    confidence="high",
                ),
                RegulatoryObligation(
                    id="obl-evidence-retention",
                    text="Keep technical and compliance evidence available for auditor review.",
                    jurisdiction="European Union",
                    topics=["evidence retention", "audit"],
                    risk_level=RiskLevel.high,
                    source_quote="Evidence must be retained.",
                    confidence="medium",
                ),
            ],
        )
    ]

    findings = await LocalRetrievalBackend(top_k=4).search(
        MonitoringInstruction(
            query="EU AI Act high-risk AI deployer obligations",
            jurisdiction="European Union",
            domain="AI governance",
        ),
        source_findings,
    )

    assert findings
    finding = findings[0]
    assert finding.chunks
    assert finding.mappings
    assert any(chunk.document.title == "AI Governance Policy" for chunk in finding.chunks)
    assert any(chunk.document.owner for chunk in finding.chunks)
    assert all(chunk.citation.retrieved_at for chunk in finding.chunks)


async def test_local_retrieval_preserves_document_metadata() -> None:
    findings = await LocalRetrievalBackend(top_k=2).search(
        MonitoringInstruction(query="incident escalation logs evidence"),
        [],
    )

    chunk = findings[0].chunks[0]
    assert chunk.document.doc_id
    assert chunk.document.title
    assert chunk.document.artifact_type in {"policy", "control", "sop", "template", "inventory"}
    assert chunk.document.jurisdiction == "European Union"
    assert chunk.document.product
    assert chunk.document.system_class
    assert chunk.document.review_cadence
    assert chunk.section_ref
    assert chunk.text


async def test_local_retrieval_applies_metadata_filters() -> None:
    findings = await LocalRetrievalBackend(top_k=6).search(
        MonitoringInstruction(query="incident escalation logs evidence"),
        [],
        metadata_filters={"artifact_type": "sop", "business_unit": "Security"},
    )

    assert findings
    assert findings[0].chunks
    assert {chunk.document.artifact_type for chunk in findings[0].chunks} == {"sop"}
    assert {chunk.document.business_unit for chunk in findings[0].chunks} == {"Security"}


async def test_local_retrieval_drops_weak_unrelated_matches() -> None:
    findings = await LocalRetrievalBackend(top_k=4, min_score=0.08).search(
        MonitoringInstruction(
            query="maritime ballast water discharge reporting",
            jurisdiction="European Union",
            domain="shipping compliance",
        ),
        [],
    )

    assert findings == []


async def test_local_retrieval_mapping_rationale_names_matched_terms() -> None:
    source_findings = [
        SourceFinding(
            summary="AI incident obligations",
            obligations=[
                RegulatoryObligation(
                    id="obl-incident-logs",
                    text="Escalate material AI incidents and preserve supporting logs.",
                    jurisdiction="European Union",
                    topics=["incident response", "logs"],
                    risk_level=RiskLevel.high,
                    source_quote="Material incidents require supporting logs.",
                    confidence="high",
                )
            ],
        )
    ]

    findings = await LocalRetrievalBackend(top_k=4).search(
        MonitoringInstruction(query="AI incident escalation logs"),
        source_findings,
    )

    assert findings
    assert findings[0].mappings
    assert any("Matches obligation terms" in mapping.reason for mapping in findings[0].mappings)

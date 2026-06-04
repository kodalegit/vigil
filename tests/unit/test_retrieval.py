from types import SimpleNamespace

import pytest

from vigil.backends.retrieval import LocalRetrievalBackend, _effective_rag_corpus
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


async def test_local_retrieval_does_not_map_privacy_obligations_to_ai_corpus() -> None:
    source_findings = [
        SourceFinding(
            summary="Privacy transfer obligations",
            obligations=[
                RegulatoryObligation(
                    id="obl-privacy-transfer-assessment",
                    text="Document cross-border customer data transfer assessments.",
                    jurisdiction="United States",
                    topics=["privacy", "data transfer"],
                    risk_level=RiskLevel.high,
                    source_quote="Document customer data transfer assessments.",
                    confidence="high",
                )
            ],
        )
    ]

    findings = await LocalRetrievalBackend(top_k=6).search(
        MonitoringInstruction(query="customer data transfer assessments"),
        source_findings,
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


async def test_local_retrieval_maps_sec_ai_cyber_obligations_to_us_control() -> None:
    source_findings = [
        SourceFinding(
            summary="SEC AI and cybersecurity governance update",
            obligations=[
                RegulatoryObligation(
                    id="obl-sec-ai-cyber",
                    text=(
                        "Maintain AI model governance, cybersecurity incident escalation, "
                        "vendor oversight, and retained audit evidence for financial "
                        "services controls."
                    ),
                    jurisdiction="United States",
                    topics=["AI governance", "cybersecurity", "vendor oversight"],
                    risk_level=RiskLevel.high,
                    source_quote="SEC update describes AI and cyber governance controls.",
                    confidence="high",
                )
            ],
        )
    ]

    findings = await LocalRetrievalBackend(top_k=6).search(
        MonitoringInstruction(
            query=(
                "SEC financial services update requiring AI model governance, "
                "cybersecurity incident escalation, vendor oversight, and audit evidence"
            ),
            jurisdiction="United States",
            domain="AI governance",
        ),
        source_findings,
    )

    assert findings
    assert any(
        chunk.document.title == "SEC AI and Cyber Governance Control"
        for chunk in findings[0].chunks
    )
    assert findings[0].mappings


def test_rag_corpus_prefers_instruction_over_global_setting() -> None:
    settings = SimpleNamespace(vigil_rag_corpus="global-corpus")

    assert (
        _effective_rag_corpus(
            MonitoringInstruction(
                query="privacy notice obligations",
                rag_corpus="org-approved-corpus",
            ),
            settings,
        )
        == "org-approved-corpus"
    )


def test_rag_corpus_falls_back_to_global_setting() -> None:
    settings = SimpleNamespace(vigil_rag_corpus="global-corpus")

    assert _effective_rag_corpus(MonitoringInstruction(query="privacy"), settings) == (
        "global-corpus"
    )


def test_rag_corpus_requires_instruction_or_global_setting() -> None:
    settings = SimpleNamespace(vigil_rag_corpus=None)

    with pytest.raises(ValueError, match="approved org retrieval resource"):
        _effective_rag_corpus(MonitoringInstruction(query="privacy"), settings)

from vigil.backends.retrieval import LocalRetrievalBackend
from vigil.schemas import MonitoringInstruction, SourceFinding


async def test_local_retrieval_returns_relevant_chunks_for_eu_ai_act_obligations() -> None:
    source_findings = [
        SourceFinding(
            summary="EU AI Act obligations",
            obligations=[
                {
                    "id": "obl-human-oversight",
                    "text": "Maintain documented human oversight procedures for high-risk AI workflows.",
                    "jurisdiction": "European Union",
                    "topics": ["human oversight", "AI governance"],
                    "risk_level": "high",
                    "source_quote": "Human oversight is required.",
                    "confidence": "high",
                },
                {
                    "id": "obl-evidence-retention",
                    "text": "Keep technical and compliance evidence available for auditor review.",
                    "jurisdiction": "European Union",
                    "topics": ["evidence retention", "audit"],
                    "risk_level": "high",
                    "source_quote": "Evidence must be retained.",
                    "confidence": "medium",
                },
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
    assert chunk.section_ref
    assert chunk.text

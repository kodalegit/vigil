import json
from typing import Protocol

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from vigil.schemas import (
    Citation,
    MonitoringInstruction,
    RegulatoryObligation,
    SourceEvidence,
    SourceFinding,
)
from vigil.settings import Settings, get_settings


class SourceBackend(Protocol):
    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]: ...


class ObligationExtractionResult(BaseModel):
    summary: str
    obligations: list[RegulatoryObligation] = Field(default_factory=list)
    uncertainty: str | None = None
    confidence: float = 0.0


class MockSourceBackend:
    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]:
        topic = instruction.query
        jurisdiction = instruction.jurisdiction or "European Union"
        domain = instruction.domain or "AI governance"
        source = instruction.sources[0] if instruction.sources else "mock regulatory source"
        source_quote = (
            "Deployers of high-risk AI systems must use them according to instructions, "
            "assign human oversight, monitor operation, and retain relevant logs."
        )

        return [
            SourceFinding(
                summary=(
                    f"Potential {domain} update relevant to {topic} in {jurisdiction}. "
                    "The update indicates that deployers of high-risk AI systems need clearer "
                    "human oversight, monitoring, incident escalation, and evidence retention."
                ),
                obligations=[
                    RegulatoryObligation(
                        id="obl-human-oversight",
                        text="Maintain documented human oversight procedures for high-risk AI workflows.",
                        section_id="deployer-obligations",
                        jurisdiction=jurisdiction,
                        topics=["human oversight", domain],
                        risk_level="high",
                        source_url=source if source.startswith("http") else None,
                        source_quote=source_quote,
                        confidence="high",
                    ),
                    RegulatoryObligation(
                        id="obl-monitoring-incidents",
                        text=(
                            "Monitor AI system performance and log incidents that may create "
                            "material risk."
                        ),
                        section_id="deployer-obligations",
                        jurisdiction=jurisdiction,
                        topics=["monitoring", "incident response", domain],
                        risk_level="high",
                        source_url=source if source.startswith("http") else None,
                        source_quote=source_quote,
                        confidence="high",
                    ),
                    RegulatoryObligation(
                        id="obl-evidence-retention",
                        text=(
                            "Keep technical and compliance evidence available for regulator "
                            "or auditor review."
                        ),
                        section_id="deployer-obligations",
                        jurisdiction=jurisdiction,
                        topics=["evidence retention", "audit", domain],
                        risk_level="high",
                        source_url=source if source.startswith("http") else None,
                        source_quote=source_quote,
                        confidence="medium",
                    ),
                ],
                evidence=[
                    SourceEvidence(
                        title="EU AI Act deployer obligations briefing",
                        url=source if source.startswith("http") else None,
                        source_type="mock",
                        snippet=source_quote,
                        confidence="high",
                    )
                ],
                citations=[
                    Citation(
                        source=source,
                        title="EU AI Act deployer obligations briefing",
                        snippet=source_quote,
                        source_type="web" if source.startswith("http") else "other",
                        url=source if source.startswith("http") else None,
                    )
                ],
                confidence=0.78,
                uncertainty=(
                    "Local mock source does not verify current legal text; use Gemini web search "
                    "or configured official sources before production action."
                ),
            )
        ]


class GeminiWebSourceBackend:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]:
        client = genai.Client()
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        prompt = (
            "Search official or highly trusted sources for this regulatory monitoring task. "
            "Return a concise compliance analysis, not legal advice. Include source URLs, "
            "publication dates if available, obligations, and uncertainty.\n\n"
            f"Topic: {instruction.query}\n"
            f"Jurisdiction: {instruction.jurisdiction or 'unspecified'}\n"
            f"Domain: {instruction.domain or 'compliance'}\n"
            f"Preferred sources: {', '.join(instruction.sources) or 'official regulatory sources'}\n"
        )
        response = await client.aio.models.generate_content(
            model=self.settings.vigil_model,
            contents=prompt,
            config=types.GenerateContentConfig(tools=[grounding_tool]),
        )

        text = response.text or ""
        evidence = _grounding_evidence(response)
        citations = [
            Citation(
                source=item.url or item.title,
                title=item.title,
                snippet=item.snippet,
                source_type="web",
                url=item.url,
                retrieved_at=item.retrieved_at,
            )
            for item in evidence
        ]
        extraction = await _extract_obligations_with_model(
            client=client,
            settings=self.settings,
            instruction=instruction,
            grounded_text=text,
            evidence=evidence,
        )
        return [
            SourceFinding(
                summary=extraction.summary
                or text.strip()
                or f"Grounded search completed for {instruction.query}.",
                obligations=extraction.obligations,
                evidence=evidence,
                citations=citations,
                confidence=extraction.confidence or (0.66 if evidence else 0.35),
                uncertainty=extraction.uncertainty
                or (
                    "Grounded web results should be reviewed against official source text "
                    "before external remediation."
                ),
            )
        ]


async def _extract_obligations_with_model(
    client: genai.Client,
    settings: Settings,
    instruction: MonitoringInstruction,
    grounded_text: str,
    evidence: list[SourceEvidence],
) -> ObligationExtractionResult:
    source_url = evidence[0].url if evidence else None
    if not grounded_text.strip():
        return _fallback_obligations_from_grounded_text("", instruction, source_url)

    evidence_block = "\n".join(
        f"- {item.title} ({item.url or 'no url'}): {item.snippet}" for item in evidence[:8]
    )
    prompt = (
        "Extract candidate regulatory obligations from the grounded source analysis. "
        "Return only obligations that are supported by the provided source text or evidence. "
        "Do not invent duties, dates, sections, or citations. If the source is informational "
        "or ambiguous, return an empty obligations list and explain uncertainty. This is not "
        "legal advice.\n\n"
        f"Monitoring topic: {instruction.query}\n"
        f"Jurisdiction: {instruction.jurisdiction or 'unspecified'}\n"
        f"Compliance domain: {instruction.domain or 'compliance'}\n\n"
        f"Grounded source analysis:\n{grounded_text}\n\n"
        f"Grounding evidence:\n{evidence_block or 'No grounding evidence returned.'}\n\n"
        "For each obligation, include a stable id, concise obligation text, jurisdiction, "
        "topics, risk_level, source_url, exact source_quote, and confidence."
    )
    try:
        response = await client.aio.models.generate_content(
            model=settings.vigil_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ObligationExtractionResult,
                temperature=0.0,
            ),
        )
        extraction = _parse_obligation_extraction_response(
            text=response.text or "",
            instruction=instruction,
            default_source_url=source_url,
        )
    except Exception:
        return _fallback_obligations_from_grounded_text(
            grounded_text,
            instruction,
            source_url,
        )

    if extraction.obligations:
        return extraction
    return extraction.model_copy(
        update={
            "summary": extraction.summary or grounded_text[:500],
            "uncertainty": extraction.uncertainty
            or "The model did not find evidence-backed obligations in the grounded source text.",
        }
    )


def _parse_obligation_extraction_response(
    text: str,
    instruction: MonitoringInstruction,
    default_source_url: str | None,
) -> ObligationExtractionResult:
    try:
        data = _load_json_object(text)
        extraction = ObligationExtractionResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return _fallback_obligations_from_grounded_text(text, instruction, default_source_url)

    obligations = [
        obligation.model_copy(
            update={
                "source_url": obligation.source_url or default_source_url,
                "jurisdiction": obligation.jurisdiction
                or instruction.jurisdiction
                or "unspecified",
                "topics": obligation.topics or [instruction.domain or "compliance"],
            }
        )
        for obligation in extraction.obligations
        if obligation.text.strip() and obligation.source_quote.strip()
    ]
    return extraction.model_copy(update={"obligations": obligations})


def _load_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()
    return json.loads(stripped)


def _grounding_evidence(response: types.GenerateContentResponse) -> list[SourceEvidence]:
    candidates = response.candidates or []
    if not candidates or not candidates[0].grounding_metadata:
        return []

    metadata = candidates[0].grounding_metadata
    chunks = metadata.grounding_chunks or []
    supports = metadata.grounding_supports or []
    evidence: list[SourceEvidence] = []
    for index, chunk in enumerate(chunks):
        if not chunk.web:
            continue
        snippet = ""
        for support in supports:
            if support.grounding_chunk_indices and index in support.grounding_chunk_indices:
                snippet = support.segment.text if support.segment else ""
                break
        evidence.append(
            SourceEvidence(
                title=chunk.web.title or chunk.web.uri or "Grounded web source",
                url=chunk.web.uri,
                source_type="web",
                snippet=snippet or "Grounded source returned by Gemini Google Search.",
                confidence="medium",
            )
        )
    return evidence


def _fallback_obligations_from_grounded_text(
    text: str,
    instruction: MonitoringInstruction,
    source_url: str | None,
) -> ObligationExtractionResult:
    jurisdiction = instruction.jurisdiction or "unspecified"
    domain = instruction.domain or "compliance"
    lower_text = text.lower()
    candidates = [
        (
            "obl-human-oversight",
            "Maintain documented human oversight procedures for high-risk AI workflows.",
            ["human oversight", domain],
            ["human oversight", "oversight procedures", "human-in-the-loop"],
        ),
        (
            "obl-monitoring-incidents",
            "Monitor AI system performance and log incidents that may create material risk.",
            ["monitoring", "incident response", domain],
            ["monitor", "monitoring", "incident", "incident response"],
        ),
        (
            "obl-evidence-retention",
            "Keep technical and compliance evidence available for regulator or auditor review.",
            ["evidence retention", "audit", domain],
            ["evidence retention", "retain", "retention", "audit", "logs"],
        ),
    ]
    obligations = [
        RegulatoryObligation(
            id=obligation_id,
            text=obligation_text,
            jurisdiction=jurisdiction,
            topics=topics,
            risk_level="high",
            source_url=source_url,
            source_quote=text[:500] or obligation_text,
            confidence="medium",
        )
        for obligation_id, obligation_text, topics, match_terms in candidates
        if any(term in lower_text for term in match_terms)
    ]
    return ObligationExtractionResult(
        summary=text.strip() or f"Grounded source analysis completed for {instruction.query}.",
        obligations=obligations,
        uncertainty=(
            "Used deterministic fallback extraction because structured obligation extraction "
            "was unavailable or invalid."
            if obligations
            else (
                "Structured obligation extraction was unavailable or invalid, and the fallback "
                "did not find evidence-backed obligation terms."
            )
        ),
        confidence=0.45 if obligations else 0.2,
    )

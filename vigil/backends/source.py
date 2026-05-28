import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from vigil.schemas import (
    Citation,
    MonitoringInstruction,
    RegulatoryObligation,
    RiskLevel,
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
        lower_topic = topic.lower()
        if any(term in lower_topic for term in {"maritime", "ballast", "shipping", "vessel"}):
            return [_mock_shipping_finding(topic, jurisdiction, domain, source)]
        if any(term in lower_topic for term in {"consultation", "ambiguous", "rumor", "rumour"}):
            return [
                SourceFinding(
                    summary=(
                        f"Mock source found ambiguous material for {topic}, but did not find "
                        "evidence-backed obligations."
                    ),
                    obligations=[],
                    evidence=[],
                    citations=[],
                    confidence=0.2,
                    uncertainty="No evidence-backed obligations were found in the mock source.",
                )
            ]
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
                        risk_level=RiskLevel.high,
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
                        risk_level=RiskLevel.high,
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
                        risk_level=RiskLevel.high,
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


def _mock_shipping_finding(
    topic: str,
    jurisdiction: str,
    domain: str,
    source: str,
) -> SourceFinding:
    source_quote = (
        "Covered vessel operators must report maritime ballast water discharge events "
        "to the port authority and retain voyage records."
    )
    return SourceFinding(
        summary=(
            f"Potential {domain} update relevant to {topic} in {jurisdiction}. "
            "The update concerns vessel discharge reporting and voyage record retention."
        ),
        obligations=[
            RegulatoryObligation(
                id="obl-shipping-ballast-reporting",
                text="Report maritime ballast water discharge events to the port authority.",
                section_id="vessel-discharge-reporting",
                jurisdiction=jurisdiction,
                topics=["shipping compliance", domain],
                risk_level=RiskLevel.medium,
                source_url=source if source.startswith("http") else None,
                source_quote=source_quote,
                confidence="high",
            )
        ],
        evidence=[
            SourceEvidence(
                title="Mock maritime discharge reporting update",
                url=source if source.startswith("http") else None,
                source_type="mock",
                snippet=source_quote,
                confidence="high",
            )
        ],
        citations=[
            Citation(
                source=source,
                title="Mock maritime discharge reporting update",
                snippet=source_quote,
                source_type="web" if source.startswith("http") else "other",
                url=source if source.startswith("http") else None,
            )
        ],
        confidence=0.7,
        uncertainty=(
            "Local mock source does not verify current legal text; use Gemini web search "
            "or configured official sources before production action."
        ),
    )


class GeminiWebSourceBackend:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]:
        client = genai.Client()
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        prompt = _build_grounded_search_prompt(instruction)
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
            _apply_source_quality_guardrails(
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
                ),
                instruction,
            )
        ]


def _build_grounded_search_prompt(instruction: MonitoringInstruction) -> str:
    preferred_sources = ", ".join(instruction.sources)
    freshness_policy = (
        f"Treat source items older than {instruction.source_freshness_days} day(s) as stale."
        if instruction.source_freshness_days is not None
        else "Call out publication dates when available so freshness can be reviewed."
    )
    source_policy = (
        "Use only these configured trusted sources when possible. If none of them contain "
        "relevant current material, say that clearly and do not substitute unrelated sources."
        if preferred_sources
        else "Prefer official regulator, statutory, or highly trusted primary sources."
    )
    return (
        "Search official or highly trusted sources for this regulatory monitoring task. "
        "Return a concise compliance analysis, not legal advice. Include source URLs, "
        "publication dates if available, obligations, and uncertainty. Only identify "
        "obligations that are supported by retrieved source evidence.\n\n"
        f"Topic: {instruction.query}\n"
        f"Jurisdiction: {instruction.jurisdiction or 'unspecified'}\n"
        f"Domain: {instruction.domain or 'compliance'}\n"
        f"Configured trusted sources: {preferred_sources or 'none provided'}\n"
        f"Source policy: {source_policy}\n"
        f"Freshness policy: {freshness_policy}\n"
    )


def _apply_source_quality_guardrails(
    finding: SourceFinding,
    instruction: MonitoringInstruction,
) -> SourceFinding:
    evidence, duplicate_evidence_count = _dedupe_evidence(finding.evidence)
    citations, duplicate_citation_count = _dedupe_citations(finding.citations)
    notes: list[str] = []
    duplicate_count = duplicate_evidence_count + duplicate_citation_count
    if duplicate_count:
        notes.append(f"Removed {duplicate_count} duplicate source item(s) from grounded results.")

    stale = _stale_evidence(evidence, instruction.source_freshness_days)
    dated_count = sum(1 for item in evidence if item.published_at)
    obligations = finding.obligations
    confidence = finding.confidence
    if stale:
        notes.append(
            "One or more dated source items are older than the configured freshness window."
        )
    if stale and dated_count and len(stale) == dated_count:
        obligations = []
        confidence = min(confidence, 0.25)
        notes.append("All dated source evidence is stale, so no current obligations were retained.")

    return finding.model_copy(
        update={
            "obligations": obligations,
            "evidence": evidence,
            "citations": citations,
            "confidence": confidence,
            "uncertainty": _append_uncertainty(finding.uncertainty, notes),
        }
    )


def _dedupe_evidence(evidence: list[SourceEvidence]) -> tuple[list[SourceEvidence], int]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[SourceEvidence] = []
    for item in evidence:
        key = ((item.url or "").lower(), item.title.lower(), item.snippet.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped, len(evidence) - len(deduped)


def _dedupe_citations(citations: list[Citation]) -> tuple[list[Citation], int]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[Citation] = []
    for item in citations:
        key = ((item.url or item.source).lower(), item.title.lower(), item.snippet.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped, len(citations) - len(deduped)


def _stale_evidence(
    evidence: list[SourceEvidence],
    freshness_days: int | None,
) -> list[SourceEvidence]:
    if freshness_days is None:
        return []
    cutoff = datetime.now(UTC).date() - timedelta(days=freshness_days)
    stale: list[SourceEvidence] = []
    for item in evidence:
        if not item.published_at:
            continue
        published = _parse_normalized_date(item.published_at)
        if published and published.date() < cutoff:
            stale.append(item)
    return stale


def _append_uncertainty(current: str | None, notes: list[str]) -> str | None:
    if not notes:
        return current
    if not current:
        return " ".join(notes)
    return f"{current} {' '.join(notes)}"


async def _extract_obligations_with_model(
    client: Any,
    settings: Any,
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


def _grounding_evidence(response: Any) -> list[SourceEvidence]:
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
                snippet = support.segment.text if support.segment and support.segment.text else ""
                break
        evidence.append(
            SourceEvidence(
                title=chunk.web.title or chunk.web.uri or "Grounded web source",
                url=chunk.web.uri,
                source_type="web",
                snippet=snippet or "Grounded source returned by Gemini Google Search.",
                published_at=_normalize_source_date(f"{chunk.web.title or ''}\n{snippet}"),
                confidence="medium",
            )
        )
    return evidence


def _normalize_source_date(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None

    iso_match = re.search(r"\b(20\d{2}|19\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", value)
    if iso_match:
        year, month, day = (int(part) for part in iso_match.groups())
        return _format_date(year, month, day)

    dmy_match = re.search(
        r"\b(\d{1,2})\s+"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(20\d{2}|19\d{2})\b",
        value,
        flags=re.IGNORECASE,
    )
    if dmy_match:
        day = int(dmy_match.group(1))
        month = _MONTHS[dmy_match.group(2).lower()[:3]]
        year = int(dmy_match.group(3))
        return _format_date(year, month, day)

    mdy_match = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(\d{1,2}),?\s+(20\d{2}|19\d{2})\b",
        value,
        flags=re.IGNORECASE,
    )
    if mdy_match:
        month = _MONTHS[mdy_match.group(1).lower()[:3]]
        day = int(mdy_match.group(2))
        year = int(mdy_match.group(3))
        return _format_date(year, month, day)

    return None


def _format_date(year: int, month: int, day: int) -> str | None:
    try:
        return datetime(year, month, day, tzinfo=UTC).date().isoformat()
    except ValueError:
        return None


def _parse_normalized_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


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
            risk_level=RiskLevel.high,
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

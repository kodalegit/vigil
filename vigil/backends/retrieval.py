import re
from pathlib import Path
from typing import Any, Literal, Protocol

from vigil.schemas import (
    Citation,
    EnterpriseChunk,
    EnterpriseDocument,
    EnterpriseFinding,
    MonitoringInstruction,
    ObligationMapping,
    SourceFinding,
)
from vigil.settings import Settings, get_settings


class RetrievalBackend(Protocol):
    async def search(
        self,
        instruction: MonitoringInstruction,
        source_findings: list[SourceFinding],
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[EnterpriseFinding]: ...


class LocalRetrievalBackend:
    def __init__(
        self,
        corpus_dir: Path | None = None,
        top_k: int = 6,
        min_score: float = 0.08,
    ) -> None:
        self.corpus_dir = corpus_dir or Path(__file__).resolve().parents[1] / "data" / "corpus"
        self.top_k = top_k
        self.min_score = min_score

    async def search(
        self,
        instruction: MonitoringInstruction,
        source_findings: list[SourceFinding],
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[EnterpriseFinding]:
        chunks = self._load_chunks()
        filters = _metadata_filters(instruction, source_findings, metadata_filters)
        chunks = _filter_chunks(chunks, filters)
        chunks = _filter_domain_mismatched_chunks(chunks, instruction, source_findings)
        queries = _retrieval_queries(instruction, source_findings)
        ranked_chunks = self._rank_chunks(chunks, queries)[: self.top_k]
        if not ranked_chunks:
            return []

        obligations = [
            obligation for finding in source_findings for obligation in finding.obligations
        ]
        mappings = _build_mappings(ranked_chunks, obligations)
        if obligations and not mappings:
            return []
        documents = _unique_documents(ranked_chunks)
        citations = [chunk.citation for chunk in ranked_chunks]
        affected_artifacts = [document.title for document in documents]

        return [
            EnterpriseFinding(
                summary=(
                    "Local indexed corpus retrieval found likely affected enterprise artifacts: "
                    + ", ".join(affected_artifacts)
                    + "."
                ),
                relevant_docs=documents,
                chunks=ranked_chunks,
                mappings=mappings,
                affected_artifacts=affected_artifacts,
                citations=citations,
                confidence=_average_score(ranked_chunks),
            )
        ]

    def _load_chunks(self) -> list[EnterpriseChunk]:
        chunks: list[EnterpriseChunk] = []
        for path in sorted(self.corpus_dir.glob("*.md")):
            metadata, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
            document = EnterpriseDocument(
                doc_id=metadata.get("doc_id", path.stem),
                title=metadata.get("title", path.stem.replace("-", " ").title()),
                owner=metadata.get("owner"),
                business_unit=metadata.get("business_unit"),
                artifact_type=_artifact_type(metadata.get("artifact_type")),
                source_type="local",
                uri=str(path),
                last_reviewed_at=metadata.get("last_reviewed_at"),
                jurisdiction=metadata.get("jurisdiction"),
                product=metadata.get("product"),
                system_class=metadata.get("system_class"),
                review_cadence=metadata.get("review_cadence"),
            )
            chunks.extend(_chunk_markdown(document, body))
        return chunks

    def _rank_chunks(
        self,
        chunks: list[EnterpriseChunk],
        queries: list[str],
    ) -> list[EnterpriseChunk]:
        query_terms = set(_tokenize(" ".join(queries)))
        expanded_terms = query_terms | _expand_terms(query_terms)
        ranked: list[EnterpriseChunk] = []
        for chunk in chunks:
            chunk_terms = set(_tokenize(f"{chunk.document.title} {chunk.section_ref} {chunk.text}"))
            overlap = expanded_terms & chunk_terms
            phrase_bonus = sum(
                0.1
                for query in queries
                if query.lower() in chunk.text.lower()
                or any(term in chunk.text.lower() for term in _important_phrases(query))
            )
            score = min(1.0, (len(overlap) / max(len(expanded_terms), 1)) + phrase_bonus)
            if score < self.min_score:
                continue
            ranked.append(chunk.model_copy(update={"relevance_score": round(score, 3)}))
        return sorted(ranked, key=lambda item: item.relevance_score, reverse=True)


class RagEngineRetrievalBackend:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def search(
        self,
        instruction: MonitoringInstruction,
        source_findings: list[SourceFinding],
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[EnterpriseFinding]:
        from vertexai import rag
        from vertexai.rag.utils import resources as rag_resources
        import vertexai

        vertexai.init(
            project=self.settings.google_cloud_project,
            location=self.settings.google_cloud_location,
        )
        rag_corpus = _effective_rag_corpus(instruction, self.settings)
        query = " ".join(_retrieval_queries(instruction, source_findings))
        response = rag.retrieval_query(
            rag_resources=[rag.RagResource(rag_corpus=rag_corpus)],
            text=query,
            rag_retrieval_config=rag.RagRetrievalConfig(
                top_k=self.settings.vigil_retrieval_top_k,
                filter=rag_resources.Filter(
                    vector_distance_threshold=self.settings.vigil_rag_distance_threshold
                ),
            ),
        )
        chunks = _rag_response_to_chunks(response)
        chunks = _filter_chunks(
            chunks,
            _metadata_filters(instruction, source_findings, metadata_filters),
        )
        chunks = _filter_domain_mismatched_chunks(chunks, instruction, source_findings)
        if not chunks:
            return []
        documents = _unique_documents(chunks)
        mappings = _build_mappings(
            chunks,
            [obligation for finding in source_findings for obligation in finding.obligations],
        )
        if source_findings and not mappings:
            return []
        return [
            EnterpriseFinding(
                summary="RAG Engine retrieval returned enterprise context for the regulatory update.",
                relevant_docs=documents,
                chunks=chunks,
                mappings=mappings,
                affected_artifacts=[document.title for document in documents],
                citations=[chunk.citation for chunk in chunks],
                confidence=_average_score(chunks),
            )
        ]


def _effective_rag_corpus(
    instruction: MonitoringInstruction,
    settings: Settings,
) -> str:
    rag_corpus = instruction.rag_corpus or settings.vigil_rag_corpus
    if not rag_corpus:
        raise ValueError(
            "RAG Engine retrieval requires an approved org retrieval resource "
            "or VIGIL_RAG_CORPUS."
        )
    return rag_corpus


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    _, metadata_text, body = text.split("---", 2)
    metadata: dict[str, str] = {}
    for line in metadata_text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, body.strip()


def _metadata_filters(
    instruction: MonitoringInstruction,
    source_findings: list[SourceFinding] | None,
    explicit_filters: dict[str, Any] | None,
) -> dict[str, Any]:
    filters = dict(explicit_filters or {})
    if instruction.jurisdiction:
        filters.setdefault("jurisdiction", instruction.jurisdiction)
    domain = instruction.domain or _domain_from_source_findings(source_findings or [])
    if domain:
        filters.setdefault("domain", domain)
    return filters


def _domain_from_source_findings(source_findings: list[SourceFinding]) -> str | None:
    ignored_topics = {
        "audit",
        "compliance",
        "controls",
        "evidence retention",
        "incident reporting",
        "monitoring",
        "records",
    }
    for finding in source_findings:
        for obligation in finding.obligations:
            for topic in obligation.topics:
                normalized = topic.strip()
                if normalized and normalized.lower() not in ignored_topics:
                    return normalized
    return None


def _filter_chunks(
    chunks: list[EnterpriseChunk],
    filters: dict[str, Any],
) -> list[EnterpriseChunk]:
    if not filters:
        return chunks
    return [
        chunk
        for chunk in chunks
        if all(_matches_filter(chunk.document, key, value) for key, value in filters.items())
    ]


def _filter_domain_mismatched_chunks(
    chunks: list[EnterpriseChunk],
    instruction: MonitoringInstruction,
    source_findings: list[SourceFinding],
) -> list[EnterpriseChunk]:
    domain = (instruction.domain or _domain_from_source_findings(source_findings) or "").lower()
    if not domain:
        return chunks
    if _is_ai_domain(domain) or _is_ai_query(instruction.query, source_findings):
        return chunks
    return [chunk for chunk in chunks if not _is_ai_chunk(chunk)]


def _is_ai_domain(domain: str) -> bool:
    return "ai" in domain or "artificial intelligence" in domain or "model" in domain


def _is_ai_query(query: str, source_findings: list[SourceFinding]) -> bool:
    haystack = " ".join(
        [
            query,
            *[
                obligation.text
                for finding in source_findings
                for obligation in finding.obligations
            ],
            *[
                topic
                for finding in source_findings
                for obligation in finding.obligations
                for topic in obligation.topics
            ],
        ]
    ).lower()
    return _is_ai_domain(haystack)


def _is_ai_chunk(chunk: EnterpriseChunk) -> bool:
    haystack = " ".join(
        item or ""
        for item in [
            chunk.document.title,
            chunk.document.product,
            chunk.document.system_class,
            chunk.document.business_unit,
            chunk.text[:500],
        ]
    ).lower()
    return _is_ai_domain(haystack)


def _matches_filter(document: EnterpriseDocument, key: str, value: Any) -> bool:
    if value in (None, "", []):
        return True
    values = (
        {str(item).lower() for item in value} if isinstance(value, list) else {str(value).lower()}
    )
    if key == "domain":
        haystack = " ".join(
            item or ""
            for item in [
                document.title,
                document.artifact_type,
                document.product,
                document.system_class,
                document.business_unit,
            ]
        ).lower()
        return any(item in haystack for item in values)
    candidate = getattr(document, key, None)
    if candidate is None:
        return True
    return str(candidate).lower() in values


ArtifactType = Literal[
    "policy",
    "control",
    "sop",
    "contract",
    "meeting_note",
    "template",
    "inventory",
    "other",
]


def _artifact_type(value: str | None) -> ArtifactType:
    if value == "policy":
        return "policy"
    if value == "control":
        return "control"
    if value == "sop":
        return "sop"
    if value == "contract":
        return "contract"
    if value == "meeting_note":
        return "meeting_note"
    if value == "template":
        return "template"
    if value == "inventory":
        return "inventory"
    return "other"


def _chunk_markdown(document: EnterpriseDocument, body: str) -> list[EnterpriseChunk]:
    sections = re.split(r"(?m)^##\s+", body)
    chunks: list[EnterpriseChunk] = []
    for index, section in enumerate(sections):
        section = section.strip()
        if not section:
            continue
        lines = section.splitlines()
        if section.startswith("# "):
            section_ref = "Overview"
            text = "\n".join(line for line in lines if not line.startswith("# ")).strip()
        else:
            section_ref = lines[0].strip()
            text = "\n".join(lines[1:]).strip()
        if not text:
            continue
        chunk_id = f"{document.doc_id}:{index}"
        chunks.append(
            EnterpriseChunk(
                chunk_id=chunk_id,
                document=document,
                section_ref=section_ref,
                text=text,
                citation=Citation(
                    source=document.uri or document.doc_id,
                    title=document.title,
                    snippet=text[:280],
                    source_type=document.source_type,
                    url=document.uri,
                    drive_file_id=document.drive_file_id,
                ),
            )
        )
    return chunks


def _retrieval_queries(
    instruction: MonitoringInstruction,
    source_findings: list[SourceFinding],
) -> list[str]:
    queries = [instruction.query]
    for finding in source_findings:
        queries.extend(obligation.text for obligation in finding.obligations)
        queries.extend(topic for obligation in finding.obligations for topic in obligation.topics)
    return queries


def _build_mappings(
    chunks: list[EnterpriseChunk],
    obligations: list,
) -> list[ObligationMapping]:
    if not obligations:
        return [
            ObligationMapping(
                obligation_id="query",
                chunk_id=chunk.chunk_id,
                doc_id=chunk.document.doc_id,
                snippet=chunk.text[:280],
                section_ref=chunk.section_ref,
                relevance_score=chunk.relevance_score,
                reason="Chunk is relevant to the regulatory monitoring query.",
            )
            for chunk in chunks
        ]

    mappings: list[ObligationMapping] = []
    for obligation in obligations:
        obligation_terms = set(_tokenize(obligation.text)) | _expand_terms(
            set(_tokenize(obligation.text))
        )
        best_chunks = sorted(
            chunks,
            key=lambda chunk: len(obligation_terms & set(_tokenize(chunk.text))),
            reverse=True,
        )[:2]
        for chunk in best_chunks:
            overlap = obligation_terms & set(_tokenize(chunk.text))
            if not overlap:
                continue
            mappings.append(
                ObligationMapping(
                    obligation_id=obligation.id,
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.document.doc_id,
                    snippet=chunk.text[:280],
                    section_ref=chunk.section_ref,
                    relevance_score=chunk.relevance_score,
                    reason=(
                        "Matches obligation terms "
                        f"{', '.join(sorted(overlap)[:5])} and topics: "
                        f"{', '.join(obligation.topics) or obligation.text}."
                    ),
                )
            )
    return mappings


def _unique_documents(chunks: list[EnterpriseChunk]) -> list[EnterpriseDocument]:
    documents: dict[str, EnterpriseDocument] = {}
    for chunk in chunks:
        documents.setdefault(chunk.document.doc_id, chunk.document)
    return list(documents.values())


def _average_score(chunks: list[EnterpriseChunk]) -> float:
    if not chunks:
        return 0.0
    return round(sum(chunk.relevance_score for chunk in chunks) / len(chunks), 3)


def _tokenize(text: str) -> list[str]:
    stop_words = {
        "and",
        "or",
        "the",
        "a",
        "an",
        "to",
        "of",
        "for",
        "with",
        "in",
        "on",
        "must",
        "be",
        "that",
        "this",
        "our",
    }
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in stop_words and len(token) > 2
    ]


def _expand_terms(terms: set[str]) -> set[str]:
    synonyms = {
        "oversight": {"review", "reviewer", "intervene", "override", "accountable"},
        "monitor": {"monitoring", "performance", "thresholds", "drift", "validation"},
        "monitoring": {"monitor", "performance", "thresholds", "drift", "validation"},
        "incident": {"incidents", "escalation", "severity", "logs", "response"},
        "incidents": {"incident", "escalation", "severity", "logs", "response"},
        "evidence": {"records", "retained", "retention", "audit", "reports"},
        "retention": {"records", "retained", "evidence", "audit"},
        "risk": {"high", "impact", "material", "compliance"},
    }
    expanded = set()
    for term in terms:
        expanded.update(synonyms.get(term, set()))
    return expanded


def _important_phrases(query: str) -> list[str]:
    phrases = [
        "human oversight",
        "incident",
        "evidence",
        "audit",
        "monitoring",
        "high-risk",
        "high impact",
    ]
    lower_query = query.lower()
    return [phrase for phrase in phrases if phrase in lower_query]


def _rag_response_to_chunks(response: object) -> list[EnterpriseChunk]:
    contexts = getattr(getattr(response, "contexts", None), "contexts", []) or []
    chunks: list[EnterpriseChunk] = []
    for index, context in enumerate(contexts):
        source_uri = getattr(context, "source_uri", None)
        title = getattr(context, "source_display_name", None) or source_uri or "RAG source"
        text = getattr(context, "text", "") or ""
        score = float(getattr(context, "score", 0.0) or 0.0)
        document = EnterpriseDocument(
            doc_id=source_uri or f"rag-doc-{index}",
            title=title,
            source_type="rag",
            uri=source_uri,
        )
        chunks.append(
            EnterpriseChunk(
                chunk_id=f"{document.doc_id}:{index}",
                document=document,
                text=text,
                relevance_score=score,
                citation=Citation(
                    source=source_uri or title,
                    title=title,
                    snippet=text[:280],
                    source_type="rag",
                    url=source_uri,
                ),
            )
        )
    return chunks

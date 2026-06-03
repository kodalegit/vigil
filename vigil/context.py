from typing import Any

from vigil.backends.memory import LocalMemoryBackend, MemoryBackend
from vigil.backends.org_context import LocalOrgContextRegistry, OrgContextRegistry
from vigil.schemas import (
    ContextPack,
    ContextProvenance,
    MemoryRecord,
    MonitoringInstruction,
    OrgContext,
)


class ContextCompiler:
    def __init__(
        self,
        registry: OrgContextRegistry | None = None,
        memory: MemoryBackend | None = None,
    ) -> None:
        self.registry = registry or LocalOrgContextRegistry()
        self.memory = memory or LocalMemoryBackend()

    async def compile(
        self,
        instruction: MonitoringInstruction,
        session_context: dict[str, Any] | None = None,
    ) -> ContextPack:
        org_context = await self.registry.get_context(instruction.org_id)
        memories = await self.memory.search(
            org_id=instruction.org_id,
            user_id=instruction.user_id,
            query=instruction.query,
            limit=5,
        )
        effective_instruction, provenance = _apply_registry_defaults(
            instruction,
            org_context,
            memories,
        )
        if memories:
            provenance.append(
                ContextProvenance(
                    field="memories",
                    source="memory",
                    detail=f"Loaded {len(memories)} advisory memory record(s).",
                )
            )
        return ContextPack(
            org_id=instruction.org_id,
            instruction=effective_instruction,
            org_context=org_context,
            memories=memories,
            session_context=session_context or {},
            provenance=provenance,
        )


def _apply_registry_defaults(
    instruction: MonitoringInstruction,
    org_context: OrgContext,
    memories: list[MemoryRecord],
) -> tuple[MonitoringInstruction, list[ContextProvenance]]:
    provenance: list[ContextProvenance] = []
    jurisdiction = instruction.jurisdiction
    domain = instruction.domain
    matched_profile = _matching_monitoring_profile(instruction, org_context)

    if not jurisdiction and matched_profile and matched_profile.jurisdictions:
        jurisdiction = matched_profile.jurisdictions[0]
        provenance.append(
            ContextProvenance(
                field="jurisdiction",
                source="registry",
                detail=f"Defaulted jurisdiction to {jurisdiction}.",
            )
        )

    if not domain:
        if matched_profile and matched_profile.domains:
            domain = matched_profile.domains[0]
            provenance.append(
                ContextProvenance(
                    field="domain",
                    source="registry",
                    detail=f"Defaulted domain to {domain}.",
                )
            )

    sources = _effective_sources(
        requested_sources=instruction.sources,
        org_context=org_context,
        jurisdiction=jurisdiction,
        domain=domain,
    )
    if sources != instruction.sources:
        provenance.append(
            ContextProvenance(
                field="sources",
                source="registry",
                detail="Applied source allowlist policy.",
            )
        )

    source_freshness_days = instruction.source_freshness_days
    if source_freshness_days is None:
        source_freshness_days = _effective_source_freshness_days(
            sources=sources,
            org_context=org_context,
            jurisdiction=jurisdiction,
            domain=domain,
        )
        if source_freshness_days is not None:
            provenance.append(
                ContextProvenance(
                    field="source_freshness_days",
                    source="registry",
                    detail=f"Applied source freshness window of {source_freshness_days} day(s).",
                )
            )

    rag_corpus = instruction.rag_corpus
    if rag_corpus is None:
        rag_corpus = _effective_rag_corpus(org_context)
        if rag_corpus is not None:
            provenance.append(
                ContextProvenance(
                    field="rag_corpus",
                    source="registry",
                    detail="Applied approved RAG Engine retrieval resource.",
                )
            )

    return (
        instruction.model_copy(
            update={
                "jurisdiction": jurisdiction,
                "domain": domain,
                "sources": sources,
                "source_freshness_days": source_freshness_days,
                "rag_corpus": rag_corpus,
                "org_context_summary": instruction.org_context_summary
                or build_org_context_summary(org_context, memories),
            }
        ),
        provenance,
    )


def build_org_context_summary(
    org_context: OrgContext,
    memories: list[MemoryRecord] | None = None,
) -> str:
    profile = org_context.profile
    parts = [
        f"Organization: {profile.display_name or profile.org_id}",
        f"Jurisdictions: {_join(profile.jurisdictions)}",
        f"Sectors: {_join(profile.sectors)}",
        f"Products or systems: {_join(profile.products)}",
        f"Business model: {profile.business_model or 'unspecified'}",
        f"Risk tolerance: {profile.risk_tolerance.value}",
    ]
    enabled_profiles = [profile for profile in org_context.monitoring_profiles if profile.enabled]
    if enabled_profiles:
        parts.append(
            "Monitoring profiles: "
            + "; ".join(
                f"{profile.name} ({_join(profile.jurisdictions)}, {_join(profile.domains)})"
                for profile in enabled_profiles[:5]
            )
        )
    if org_context.source_policy.allowlisted_sources:
        parts.append(
            "Trusted source domains: "
            + _join(
                sorted(
                    {
                        domain
                        for source in org_context.source_policy.allowlisted_sources
                        for domain in source.domains
                    }
                )
            )
        )
    if memories:
        parts.append(
            "Relevant approved memories: "
            + "; ".join(
                f"{memory.topic}: {memory.text[:220]}" for memory in memories[:5] if memory.text
            )
        )
    return "\n".join(parts)


def _join(values: list[str]) -> str:
    return ", ".join(values) if values else "unspecified"


def _effective_sources(
    *,
    requested_sources: list[str],
    org_context: OrgContext,
    jurisdiction: str | None,
    domain: str | None,
) -> list[str]:
    source_policy = org_context.source_policy
    if requested_sources:
        if not source_policy.require_allowlist:
            return [
                source
                for source in requested_sources
                if source not in source_policy.blocked_sources
            ]
        return [source for source in requested_sources if source_policy.is_allowed(source)]

    if jurisdiction or domain:
        return source_policy.allowed_urls(jurisdiction=jurisdiction, domain=domain)
    return [
        source.url
        for source in source_policy.allowlisted_sources
        if (
            source.trust_level != "blocked"
            and source.url not in source_policy.blocked_sources
            and not source.jurisdictions
            and not source.domains
        )
    ]


def _matching_monitoring_profile(
    instruction: MonitoringInstruction,
    org_context: OrgContext,
):
    query_terms = _keyword_set(instruction.query)
    for profile in org_context.monitoring_profiles:
        if not profile.enabled:
            continue
        profile_terms = _keyword_set(
            " ".join(
                [
                    profile.name,
                    profile.query,
                    " ".join(profile.jurisdictions),
                    " ".join(profile.domains),
                ]
            )
        )
        if query_terms & profile_terms:
            return profile
    return None


def _keyword_set(value: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "for",
        "in",
        "of",
        "on",
        "our",
        "the",
        "to",
        "assessment",
        "assessments",
        "compliance",
        "control",
        "controls",
        "deployer",
        "deployers",
        "monitoring",
        "obligation",
        "obligations",
        "policy",
        "regulatory",
        "threshold",
        "thresholds",
        "update",
        "updates",
    }
    return {
        part
        for part in value.lower().replace("-", " ").replace("_", " ").split()
        if len(part) > 2 and part not in stopwords
    }


def _effective_source_freshness_days(
    *,
    sources: list[str],
    org_context: OrgContext,
    jurisdiction: str | None,
    domain: str | None,
) -> int | None:
    if not sources:
        return None
    matched_days: list[int] = []
    for source in org_context.source_policy.allowlisted_sources:
        if (
            source.trust_level == "blocked"
            or source.url in org_context.source_policy.blocked_sources
        ):
            continue
        if sources and source.url not in sources:
            continue
        if jurisdiction and source.jurisdictions and jurisdiction not in source.jurisdictions:
            continue
        if domain and source.domains and domain not in source.domains:
            continue
        if source.freshness_days is not None:
            matched_days.append(source.freshness_days)
    return min(matched_days) if matched_days else None


def _effective_rag_corpus(org_context: OrgContext) -> str | None:
    for resource in org_context.retrieval_resources:
        if resource.enabled and resource.source_type == "rag_engine" and resource.rag_corpus:
            return resource.rag_corpus
    return None

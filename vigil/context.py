from typing import Any

from vigil.backends.memory import LocalMemoryBackend, MemoryBackend
from vigil.backends.org_context import LocalOrgContextRegistry, OrgContextRegistry
from vigil.schemas import ContextPack, ContextProvenance, MonitoringInstruction, OrgContext


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
) -> tuple[MonitoringInstruction, list[ContextProvenance]]:
    provenance: list[ContextProvenance] = []
    jurisdiction = instruction.jurisdiction
    domain = instruction.domain

    if not jurisdiction and org_context.profile.jurisdictions:
        jurisdiction = org_context.profile.jurisdictions[0]
        provenance.append(
            ContextProvenance(
                field="jurisdiction",
                source="registry",
                detail=f"Defaulted jurisdiction to {jurisdiction}.",
            )
        )

    if not domain:
        enabled_profiles = [profile for profile in org_context.monitoring_profiles if profile.enabled]
        profile_domains = [
            profile.domains[0]
            for profile in enabled_profiles
            if profile.domains
        ]
        if profile_domains:
            domain = profile_domains[0]
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

    return (
        instruction.model_copy(
            update={
                "jurisdiction": jurisdiction,
                "domain": domain,
                "sources": sources,
                "source_freshness_days": source_freshness_days,
            }
        ),
        provenance,
    )


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

    allowlisted = source_policy.allowed_urls(jurisdiction=jurisdiction, domain=domain)
    if allowlisted:
        return allowlisted
    return source_policy.allowed_urls()


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
        if source.trust_level == "blocked" or source.url in org_context.source_policy.blocked_sources:
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

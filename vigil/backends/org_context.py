from copy import deepcopy
from hashlib import sha256
from typing import Any, Protocol
from uuid import uuid4

from vigil.schemas import (
    ContextUpdateProposal,
    ContextUpdateResult,
    MemoryWriteProposal,
    ObligationRegistryEntry,
    ObligationVersion,
    OrgContext,
    TrustedSource,
)


class OrgContextRegistry(Protocol):
    async def get_context(self, org_id: str) -> OrgContext: ...

    async def save_proposal(self, proposal: ContextUpdateProposal) -> ContextUpdateProposal: ...

    async def validate_proposal(self, proposal: ContextUpdateProposal) -> list[str]: ...

    async def commit_proposal(
        self,
        proposal_id: str,
        approved: bool,
    ) -> ContextUpdateResult: ...

    async def get_proposal(self, proposal_id: str) -> ContextUpdateProposal | None: ...


_LOCAL_CONTEXTS: dict[str, OrgContext] = {}
_LOCAL_PROPOSALS: dict[str, ContextUpdateProposal] = {}


class LocalOrgContextRegistry:
    async def get_context(self, org_id: str) -> OrgContext:
        context = _LOCAL_CONTEXTS.setdefault(org_id, _default_context(org_id))
        return context.model_copy(deep=True)

    async def save_proposal(self, proposal: ContextUpdateProposal) -> ContextUpdateProposal:
        errors = await self.validate_proposal(proposal)
        if errors:
            raise ValueError("; ".join(errors))
        _LOCAL_PROPOSALS[proposal.proposal_id] = proposal.model_copy(deep=True)
        return proposal.model_copy(deep=True)

    async def validate_proposal(self, proposal: ContextUpdateProposal) -> list[str]:
        errors: list[str] = []
        context = proposal.proposed_context
        if not context.profile.org_id:
            errors.append("Org profile requires an org_id.")
        if not context.profile.jurisdictions:
            errors.append("Org profile requires at least one jurisdiction.")
        if context.source_policy.require_allowlist and not context.source_policy.allowlisted_sources:
            errors.append("Source policy requires at least one allowlisted source.")
        for source in context.source_policy.allowlisted_sources:
            if not source.url.startswith(("https://", "http://")):
                errors.append(f"Allowlisted source {source.source_id} must use an HTTP URL.")
        return errors

    async def get_proposal(self, proposal_id: str) -> ContextUpdateProposal | None:
        proposal = _LOCAL_PROPOSALS.get(proposal_id)
        return proposal.model_copy(deep=True) if proposal else None

    async def commit_proposal(
        self,
        proposal_id: str,
        approved: bool,
    ) -> ContextUpdateResult:
        proposal = _LOCAL_PROPOSALS.get(proposal_id)
        if not proposal:
            return ContextUpdateResult(
                proposal_id=proposal_id,
                committed=False,
                message="Context update proposal was not found.",
            )
        if not approved or not proposal.approved:
            return ContextUpdateResult(
                proposal_id=proposal_id,
                committed=False,
                message="Context update was not committed because approval is required.",
            )
        errors = await self.validate_proposal(proposal)
        if errors:
            return ContextUpdateResult(
                proposal_id=proposal_id,
                committed=False,
                message="Context update was not committed: " + "; ".join(errors),
            )
        _LOCAL_CONTEXTS[proposal.org_id] = proposal.proposed_context.model_copy(deep=True)
        return ContextUpdateResult(
            proposal_id=proposal_id,
            committed=True,
            message="Approved organization context update committed.",
            context=proposal.proposed_context.model_copy(deep=True),
        )


async def build_context_update_proposal(
    registry: OrgContextRegistry,
    *,
    org_id: str,
    summary: str,
    updates: dict[str, Any],
    requested_by: str | None = None,
    memory_writes: list[MemoryWriteProposal] | None = None,
    approved: bool = False,
) -> ContextUpdateProposal:
    current = await registry.get_context(org_id)
    proposed = _apply_updates(current, updates)
    proposal = ContextUpdateProposal(
        proposal_id=f"ctx-{uuid4().hex[:12]}",
        org_id=org_id,
        requested_by=requested_by,
        summary=summary,
        proposed_context=proposed,
        memory_writes=memory_writes or [],
        diff=_diff_context(current, proposed),
        approved=approved,
    )
    return await registry.save_proposal(proposal)


def _apply_updates(context: OrgContext, updates: dict[str, Any]) -> OrgContext:
    data = context.model_dump(mode="python")
    for section, value in updates.items():
        if section == "obligation_inventory":
            data[section] = [_normalize_obligation(item).model_dump(mode="python") for item in value]
            continue
        if isinstance(value, dict) and isinstance(data.get(section), dict):
            data[section] = {**data[section], **value}
            continue
        data[section] = deepcopy(value)
    return OrgContext.model_validate(data)


def _normalize_obligation(item: dict[str, Any] | ObligationRegistryEntry) -> ObligationRegistryEntry:
    if isinstance(item, ObligationRegistryEntry):
        obligation = item
    else:
        obligation = ObligationRegistryEntry.model_validate(item)
    content_hash = sha256(obligation.canonical_text.encode("utf-8")).hexdigest()
    if obligation.versions:
        return obligation
    return obligation.model_copy(
        update={
            "versions": [
                ObligationVersion(
                    version=1,
                    canonical_text=obligation.canonical_text,
                    source_quote=obligation.evidence_snippets[0]
                    if obligation.evidence_snippets
                    else obligation.canonical_text,
                    source_url=obligation.source_url,
                    section_ref=obligation.section_ref,
                    effective_date=obligation.effective_date,
                    content_hash=content_hash,
                )
            ]
        }
    )


def _diff_context(current: OrgContext, proposed: OrgContext) -> list[str]:
    diff: list[str] = []
    if current.profile != proposed.profile:
        diff.append("Updated organization profile.")
    if current.source_policy != proposed.source_policy:
        diff.append("Updated source policy and allowlist.")
    if current.slack_preferences != proposed.slack_preferences:
        diff.append("Updated Slack preferences.")
    if current.monitoring_profiles != proposed.monitoring_profiles:
        diff.append("Updated monitoring profiles.")
    if current.obligation_inventory != proposed.obligation_inventory:
        diff.append("Updated obligation inventory.")
    return diff or ["No material context changes detected."]


def _default_context(org_id: str) -> OrgContext:
    return OrgContext(
        profile={
            "org_id": org_id,
            "display_name": "Default Organization",
            "sectors": ["SaaS"],
            "products": ["AI governance workflows"],
            "business_model": "Mid-size SaaS company handling regulated data.",
            "jurisdictions": ["European Union"],
            "risk_tolerance": "medium",
        },
        source_policy={
            "allowlisted_sources": [
                TrustedSource(
                    source_id="eu-ai-act-briefing",
                    name="EU AI Act briefing",
                    url="https://artificialintelligenceact.eu/",
                    jurisdictions=["European Union"],
                    domains=["AI governance"],
                    regulators=["European Union"],
                    trust_level="trusted",
                    freshness_days=30,
                )
            ],
            "require_allowlist": True,
        },
        slack_preferences={
            "default_channel": "#ai-governance-review",
            "reviewer_user_ids": [],
            "notification_windows": [],
            "escalation_rules": [],
        },
        monitoring_profiles=[
            {
                "profile_id": "eu-ai-act",
                "name": "EU AI Act high-risk AI monitoring",
                "query": "EU AI Act high-risk AI deployer obligations",
                "jurisdictions": ["European Union"],
                "domains": ["AI governance"],
                "cadence": "weekly",
                "threshold": "medium",
                "source_ids": ["eu-ai-act-briefing"],
                "enabled": True,
            }
        ],
    )

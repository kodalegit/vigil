from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


MemoryTopic = Literal[
    "source_policy",
    "notification_preferences",
    "false_positive_patterns",
    "regulatory_scope",
    "obligation_summaries",
    "other",
]


class MonitoringInstruction(BaseModel):
    query: str
    jurisdiction: str | None = None
    domain: str | None = None
    sources: list[str] = Field(default_factory=list)
    source_freshness_days: int | None = None
    org_context_summary: str | None = None
    suppress_repeated_findings: bool = False
    org_id: str = "default-org"
    user_id: str | None = None


class Citation(BaseModel):
    source: str
    title: str
    snippet: str
    source_type: Literal["web", "drive", "local", "rag", "slack", "other"] = "other"
    url: str | None = None
    drive_file_id: str | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RegulatoryObligation(BaseModel):
    id: str
    text: str
    section_id: str | None = None
    effective_date: str | None = None
    jurisdiction: str
    topics: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.medium
    source_url: str | None = None
    source_quote: str
    confidence: Literal["low", "medium", "high"] = "medium"


class SourceEvidence(BaseModel):
    title: str
    url: str | None = None
    source_type: Literal["web", "configured_source", "mock"] = "web"
    published_at: str | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    snippet: str
    confidence: Literal["low", "medium", "high"] = "medium"


class EnterpriseDocument(BaseModel):
    doc_id: str
    title: str
    owner: str | None = None
    business_unit: str | None = None
    jurisdiction: str | None = None
    product: str | None = None
    system_class: str | None = None
    review_cadence: str | None = None
    artifact_type: Literal[
        "policy", "control", "sop", "contract", "meeting_note", "template", "inventory", "other"
    ] = "other"
    source_type: Literal["local", "drive", "rag", "other"] = "local"
    uri: str | None = None
    drive_file_id: str | None = None
    last_reviewed_at: str | None = None


class EnterpriseChunk(BaseModel):
    chunk_id: str
    document: EnterpriseDocument
    section_ref: str | None = None
    text: str
    relevance_score: float = 0.0
    citation: Citation


class ObligationMapping(BaseModel):
    obligation_id: str
    chunk_id: str
    doc_id: str
    snippet: str
    section_ref: str | None = None
    relevance_score: float = 0.0
    reason: str


class OrgProfile(BaseModel):
    org_id: str = "default-org"
    display_name: str = "Default Organization"
    sectors: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    business_model: str | None = None
    jurisdictions: list[str] = Field(default_factory=list)
    risk_tolerance: RiskLevel = RiskLevel.medium


class TrustedSource(BaseModel):
    source_id: str
    name: str
    url: str
    jurisdictions: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    regulators: list[str] = Field(default_factory=list)
    trust_level: Literal["official", "trusted", "watch", "blocked"] = "trusted"
    freshness_days: int | None = None
    notes: str | None = None


class SourcePolicy(BaseModel):
    allowlisted_sources: list[TrustedSource] = Field(default_factory=list)
    blocked_sources: list[str] = Field(default_factory=list)
    require_allowlist: bool = True

    def allowed_urls(
        self,
        jurisdiction: str | None = None,
        domain: str | None = None,
    ) -> list[str]:
        urls: list[str] = []
        for source in self.allowlisted_sources:
            if source.trust_level == "blocked" or source.url in self.blocked_sources:
                continue
            if jurisdiction and source.jurisdictions and jurisdiction not in source.jurisdictions:
                continue
            if domain and source.domains and domain not in source.domains:
                continue
            urls.append(source.url)
        return urls

    def is_allowed(self, source_url: str) -> bool:
        if source_url in self.blocked_sources:
            return False
        return any(
            source.url == source_url and source.trust_level != "blocked"
            for source in self.allowlisted_sources
        )


class SlackPreferences(BaseModel):
    default_channel: str = "#compliance-review"
    reviewer_user_ids: list[str] = Field(default_factory=list)
    notification_windows: list[str] = Field(default_factory=list)
    escalation_rules: list[str] = Field(default_factory=list)


class MonitoringProfile(BaseModel):
    profile_id: str
    name: str
    query: str
    jurisdictions: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    cadence: str | None = None
    threshold: Literal["low", "medium", "high"] = "medium"
    source_ids: list[str] = Field(default_factory=list)
    enabled: bool = True


class RetrievalResource(BaseModel):
    resource_id: str
    name: str
    source_type: Literal["drive", "gcs", "rag_engine"]
    rag_corpus: str | None = None
    drive_folder_id: str | None = None
    gcs_uri: str | None = None
    refresh_cadence: str | None = None
    enabled: bool = True
    notes: str | None = None


class ObligationVersion(BaseModel):
    version: int
    canonical_text: str
    source_quote: str
    source_url: str | None = None
    section_ref: str | None = None
    effective_date: str | None = None
    content_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ObligationRegistryEntry(BaseModel):
    obligation_id: str
    jurisdiction: str
    regulator: str | None = None
    source_url: str | None = None
    section_ref: str | None = None
    canonical_text: str
    topics: list[str] = Field(default_factory=list)
    effective_date: str | None = None
    status: Literal["candidate", "approved", "deprecated", "false_positive"] = "candidate"
    confidence: Literal["low", "medium", "high"] = "medium"
    approval_status: Literal["pending", "approved", "rejected"] = "pending"
    versions: list[ObligationVersion] = Field(default_factory=list)
    related_policy_ids: list[str] = Field(default_factory=list)
    related_control_ids: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    business_units: list[str] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list)
    mapping_confidence: float = 0.0
    last_reviewed_at: str | None = None


class OrgContext(BaseModel):
    profile: OrgProfile = Field(default_factory=OrgProfile)
    source_policy: SourcePolicy = Field(default_factory=SourcePolicy)
    slack_preferences: SlackPreferences = Field(default_factory=SlackPreferences)
    monitoring_profiles: list[MonitoringProfile] = Field(default_factory=list)
    retrieval_resources: list[RetrievalResource] = Field(default_factory=list)
    obligation_inventory: list[ObligationRegistryEntry] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryRecord(BaseModel):
    memory_id: str
    org_id: str
    app_name: str = "vigil"
    user_id: str | None = None
    topic: MemoryTopic = "other"
    text: str
    provenance: Literal["approved_registry", "approved_user_preference", "derived"] = (
        "approved_registry"
    )
    registry_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryWriteProposal(BaseModel):
    topic: MemoryTopic
    text: str
    org_id: str = "default-org"
    user_id: str | None = None
    registry_refs: list[str] = Field(default_factory=list)
    approved: bool = False


class ContextProvenance(BaseModel):
    field: str
    source: Literal["registry", "memory", "session", "default"]
    detail: str


class ContextPack(BaseModel):
    org_id: str
    instruction: MonitoringInstruction
    org_context: OrgContext
    memories: list[MemoryRecord] = Field(default_factory=list)
    session_context: dict[str, Any] = Field(default_factory=dict)
    provenance: list[ContextProvenance] = Field(default_factory=list)


class ContextUpdateProposal(BaseModel):
    proposal_id: str
    org_id: str = "default-org"
    requested_by: str | None = None
    summary: str
    proposed_context: OrgContext
    memory_writes: list[MemoryWriteProposal] = Field(default_factory=list)
    diff: list[str] = Field(default_factory=list)
    approved: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ContextUpdateResult(BaseModel):
    proposal_id: str
    committed: bool
    message: str
    context: OrgContext | None = None
    memories_written: list[MemoryRecord] = Field(default_factory=list)


class SourceFinding(BaseModel):
    summary: str
    obligations: list[RegulatoryObligation] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0
    uncertainty: str | None = None
    is_duplicate: bool = False


class EnterpriseFinding(BaseModel):
    summary: str
    relevant_docs: list[EnterpriseDocument] = Field(default_factory=list)
    chunks: list[EnterpriseChunk] = Field(default_factory=list)
    mappings: list[ObligationMapping] = Field(default_factory=list)
    affected_artifacts: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0


class EvidencePacket(BaseModel):
    instruction: MonitoringInstruction
    source_findings: list[SourceFinding] = Field(default_factory=list)
    enterprise_findings: list[EnterpriseFinding] = Field(default_factory=list)


class ActionResult(BaseModel):
    action: str
    success: bool
    message: str
    external_id: str | None = None
    idempotency_key: str | None = None


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"audit-{uuid4().hex[:12]}")
    event_type: str
    message: str
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ImpactDecision(BaseModel):
    analysis_id: str = Field(default_factory=lambda: f"analysis-{uuid4().hex[:12]}")
    org_id: str = "default-org"
    is_actionable: bool
    risk_level: RiskLevel
    classification: Literal["actionable", "informational", "irrelevant", "ambiguous"]
    summary: str
    recommended_actions: list[str] = Field(default_factory=list)
    source_findings: list[SourceFinding] = Field(default_factory=list)
    enterprise_findings: list[EnterpriseFinding] = Field(default_factory=list)
    action_results: list[ActionResult] = Field(default_factory=list)
    approval_required: bool = False
    approval_status: Literal["not_required", "pending", "approved", "rejected"] = "not_required"
    ticket_status: Literal["not_required", "blocked_pending_approval", "created"] = "not_required"
    approved_by: str | None = None
    approved_at: datetime | None = None
    ticket_id: str | None = None
    audit_events: list[AuditEvent] = Field(default_factory=list)
    slack_channel: str | None = None
    reviewer_user_ids: list[str] = Field(default_factory=list)
    context_provenance: list[ContextProvenance] = Field(default_factory=list)
    applied_memories: list[MemoryRecord] = Field(default_factory=list)

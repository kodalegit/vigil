from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class MonitoringInstruction(BaseModel):
    query: str
    jurisdiction: str | None = None
    domain: str | None = None
    sources: list[str] = Field(default_factory=list)


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


class SourceFinding(BaseModel):
    summary: str
    obligations: list[RegulatoryObligation] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0
    uncertainty: str | None = None


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


class AuditEvent(BaseModel):
    event_type: str
    message: str
    metadata: dict[str, str] = Field(default_factory=dict)


class ImpactDecision(BaseModel):
    is_actionable: bool
    risk_level: RiskLevel
    summary: str
    recommended_actions: list[str] = Field(default_factory=list)
    source_findings: list[SourceFinding] = Field(default_factory=list)
    enterprise_findings: list[EnterpriseFinding] = Field(default_factory=list)
    action_results: list[ActionResult] = Field(default_factory=list)

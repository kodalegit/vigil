from enum import Enum

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
    url: str | None = None


class SourceFinding(BaseModel):
    summary: str
    obligations: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0


class EnterpriseFinding(BaseModel):
    summary: str
    affected_artifacts: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0


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

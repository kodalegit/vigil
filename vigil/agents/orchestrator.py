from vigil.agents.enterprise_context import EnterpriseContextAgent
from vigil.agents.source_monitoring import SourceMonitoringAgent
from vigil.backends import BackendBundle, create_backends
from vigil.schemas import (
    AuditEvent,
    EnterpriseFinding,
    ImpactDecision,
    MonitoringInstruction,
    RiskLevel,
    SourceFinding,
)


class VigilOrchestrator:
    def __init__(
        self,
        backends: BackendBundle | None = None,
        source_agent: SourceMonitoringAgent | None = None,
        enterprise_agent: EnterpriseContextAgent | None = None,
    ) -> None:
        self.backends = backends or create_backends()
        self.source_agent = source_agent or SourceMonitoringAgent(self.backends.source)
        self.enterprise_agent = enterprise_agent or EnterpriseContextAgent(
            self.backends.retrieval
        )

    async def analyze(self, instruction: MonitoringInstruction) -> ImpactDecision:
        audit_events: list[AuditEvent] = []
        await self._record_audit(
            audit_events,
            event_type="analysis_started",
            message="Started regulatory impact analysis.",
            metadata={"query": instruction.query},
        )
        source_findings = await self.source_agent.search(instruction)
        await self._record_audit(
            audit_events,
            event_type="source_searched",
            message="Completed source monitoring and obligation extraction.",
            metadata={
                "query": instruction.query,
                "source_findings": str(len(source_findings)),
                "obligations": str(_count_obligations(source_findings)),
            },
        )
        enterprise_findings = await self.enterprise_agent.search(
            instruction, source_findings
        )
        await self._record_audit(
            audit_events,
            event_type="enterprise_context_retrieved",
            message="Completed enterprise context retrieval and obligation mapping.",
            metadata={
                "query": instruction.query,
                "enterprise_findings": str(len(enterprise_findings)),
                "chunks": str(_count_chunks(enterprise_findings)),
                "mappings": str(_count_mappings(enterprise_findings)),
            },
        )

        classification = _classify(source_findings, enterprise_findings)
        is_actionable = classification == "actionable"
        risk_level = _risk_level(classification, source_findings, enterprise_findings)
        recommended_actions = _recommended_actions(classification)

        decision = ImpactDecision(
            is_actionable=is_actionable,
            risk_level=risk_level,
            classification=classification,
            summary=(
                _summary(
                    classification=classification,
                    instruction=instruction,
                    source_findings=source_findings,
                    enterprise_findings=enterprise_findings,
                )
            ),
            recommended_actions=recommended_actions,
            source_findings=source_findings,
            enterprise_findings=enterprise_findings,
            approval_required=is_actionable,
            approval_status="pending" if is_actionable else "not_required",
            ticket_status="blocked_pending_approval" if is_actionable else "not_required",
            audit_events=audit_events.copy(),
        )

        if decision.is_actionable:
            await self._record_audit(
                audit_events,
                event_type="alert_prepared",
                message="Prepared approval-oriented Slack alert.",
                metadata={
                    "classification": decision.classification,
                    "risk_level": decision.risk_level.value,
                },
            )
            decision.action_results.append(
                await self.backends.actions.send_alert(decision)
            )
            await self._record_audit(
                audit_events,
                event_type="approval_requested",
                message="Human approval required before remediation ticket creation.",
                metadata={"approval_status": decision.approval_status},
            )
            decision.action_results.append(
                await self.backends.actions.generate_report(decision)
            )
            ticket_result = await self.backends.actions.create_ticket(
                decision,
                approved=False,
            )
            decision.action_results.append(ticket_result)
            await self._record_audit(
                audit_events,
                event_type="ticket_blocked",
                message="Remediation ticket creation was blocked pending human approval.",
                metadata={"success": str(ticket_result.success)},
            )

        await self._record_audit(
            audit_events,
            event_type="analysis_completed",
            message="Completed regulatory impact analysis.",
            metadata={
                "query": instruction.query,
                "classification": decision.classification,
                "risk_level": decision.risk_level.value,
                "is_actionable": str(decision.is_actionable),
            },
        )
        decision.audit_events = audit_events

        return decision

    async def _record_audit(
        self,
        audit_events: list[AuditEvent],
        event_type: str,
        message: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        event = AuditEvent(
            event_type=event_type,
            message=message,
            metadata=metadata or {},
        )
        audit_events.append(event)
        await self.backends.audit.record(event)


def _classify(
    source_findings: list[SourceFinding],
    enterprise_findings: list[EnterpriseFinding],
) -> str:
    obligation_count = _count_obligations(source_findings)
    chunk_count = _count_chunks(enterprise_findings)
    mapping_count = _count_mappings(enterprise_findings)
    has_uncertainty = any(finding.uncertainty for finding in source_findings)

    if obligation_count > 0 and chunk_count > 0 and mapping_count > 0:
        return "actionable"
    if obligation_count > 0 and chunk_count == 0:
        return "informational"
    if source_findings and obligation_count == 0 and has_uncertainty:
        return "ambiguous"
    return "irrelevant"


def _risk_level(
    classification: str,
    source_findings: list[SourceFinding],
    enterprise_findings: list[EnterpriseFinding],
) -> RiskLevel:
    if classification == "actionable":
        high_obligation = any(
            obligation.risk_level in {RiskLevel.high, RiskLevel.critical}
            for finding in source_findings
            for obligation in finding.obligations
        )
        multi_artifact = len(
            {
                chunk.document.doc_id
                for finding in enterprise_findings
                for chunk in finding.chunks
            }
        ) > 1
        return RiskLevel.high if high_obligation or multi_artifact else RiskLevel.medium
    if classification in {"informational", "ambiguous"}:
        return RiskLevel.medium
    return RiskLevel.low


def _recommended_actions(classification: str) -> list[str]:
    if classification == "actionable":
        return [
            "Send a compliance impact alert to the AI governance review channel.",
            "Request human approval before creating remediation tasks.",
            "Update human oversight, monitoring, incident escalation, and evidence retention controls.",
            "Generate a cited impact report for the audit trail.",
        ]
    if classification == "informational":
        return [
            "Record the source update and monitor for enterprise impact.",
            "Do not create remediation tasks until relevant internal artifacts are identified.",
        ]
    if classification == "ambiguous":
        return [
            "Ask for clarification or retrieve stronger official source evidence.",
            "Do not alert broadly or create remediation tasks yet.",
        ]
    return ["No action recommended unless new evidence appears."]


def _summary(
    classification: str,
    instruction: MonitoringInstruction,
    source_findings: list[SourceFinding],
    enterprise_findings: list[EnterpriseFinding],
) -> str:
    artifact_count = len(
        {
            chunk.document.doc_id
            for finding in enterprise_findings
            for chunk in finding.chunks
        }
    )
    obligation_count = _count_obligations(source_findings)
    if classification == "actionable":
        return (
            f"Vigil found {obligation_count} evidence-backed obligation(s) for "
            f"{instruction.query} with matching enterprise context across "
            f"{artifact_count} artifact(s). Human approval is required before ticket creation."
        )
    if classification == "informational":
        return (
            f"Vigil found {obligation_count} source obligation(s) for {instruction.query}, "
            "but did not find matching enterprise artifacts in the current corpus."
        )
    if classification == "ambiguous":
        return (
            f"Vigil found source material for {instruction.query}, but the evidence was too "
            "uncertain to extract obligations or recommend action."
        )
    return f"Vigil did not find enough source or enterprise evidence for {instruction.query}."


def _count_obligations(source_findings: list[SourceFinding]) -> int:
    return sum(len(finding.obligations) for finding in source_findings)


def _count_chunks(enterprise_findings: list[EnterpriseFinding]) -> int:
    return sum(len(finding.chunks) for finding in enterprise_findings)


def _count_mappings(enterprise_findings: list[EnterpriseFinding]) -> int:
    return sum(len(finding.mappings) for finding in enterprise_findings)

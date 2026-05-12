from vigil.agents.enterprise_context import EnterpriseContextAgent
from vigil.agents.source_monitoring import SourceMonitoringAgent
from vigil.backends import BackendBundle, create_backends
from vigil.schemas import AuditEvent, ImpactDecision, MonitoringInstruction, RiskLevel


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
        await self.backends.audit.record(
            AuditEvent(
                event_type="analysis_started",
                message="Started regulatory impact analysis.",
                metadata={"query": instruction.query},
            )
        )
        source_findings = await self.source_agent.search(instruction)
        enterprise_findings = await self.enterprise_agent.search(
            instruction, source_findings
        )

        is_actionable = bool(source_findings and enterprise_findings)
        risk_level = RiskLevel.medium if is_actionable else RiskLevel.low
        recommended_actions = []
        if is_actionable:
            recommended_actions = [
                "Send a compliance impact alert to the configured review channel.",
                "Request human review before creating remediation tasks.",
                "Generate a cited impact report for the audit trail.",
            ]

        decision = ImpactDecision(
            is_actionable=is_actionable,
            risk_level=risk_level,
            summary=(
                "Vigil found a potentially actionable regulatory update with matching enterprise context."
                if is_actionable
                else "Vigil did not find enough evidence to recommend action."
            ),
            recommended_actions=recommended_actions,
            source_findings=source_findings,
            enterprise_findings=enterprise_findings,
        )

        if decision.is_actionable:
            decision.action_results.append(
                await self.backends.actions.send_alert(decision)
            )
            decision.action_results.append(
                await self.backends.actions.generate_report(decision)
            )

        await self.backends.audit.record(
            AuditEvent(
                event_type="analysis_completed",
                message="Completed regulatory impact analysis.",
                metadata={
                    "query": instruction.query,
                    "risk_level": decision.risk_level.value,
                    "is_actionable": str(decision.is_actionable),
                },
            )
        )

        return decision

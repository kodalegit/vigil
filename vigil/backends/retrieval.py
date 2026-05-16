from typing import Protocol

from vigil.schemas import Citation, EnterpriseFinding, MonitoringInstruction, SourceFinding


class RetrievalBackend(Protocol):
    async def search(
        self,
        instruction: MonitoringInstruction,
        source_findings: list[SourceFinding],
    ) -> list[EnterpriseFinding]: ...


class LocalRetrievalBackend:
    async def search(
        self,
        instruction: MonitoringInstruction,
        source_findings: list[SourceFinding],
    ) -> list[EnterpriseFinding]:
        return [
            EnterpriseFinding(
                summary=(
                    "Local enterprise context suggests the AI governance policy, model risk control, "
                    "and incident response SOP may need updates for EU AI Act deployer obligations."
                ),
                affected_artifacts=[
                    "AI Governance Policy",
                    "Model Risk Control Register",
                    "AI Incident Response SOP",
                ],
                citations=[
                    Citation(
                        source="local demo corpus",
                        title="AI Governance Policy",
                        snippet=(
                            "Product teams must document model purpose, approved use cases, "
                            "and assigned business owner before production launch."
                        ),
                    ),
                    Citation(
                        source="local demo corpus",
                        title="Model Risk Control Register",
                        snippet=(
                            "High-impact models require quarterly monitoring, named reviewers, "
                            "and retained evidence of validation results."
                        ),
                    ),
                    Citation(
                        source="local demo corpus",
                        title="AI Incident Response SOP",
                        snippet=(
                            "Material AI incidents must be escalated to Compliance and Security "
                            "within one business day with supporting logs."
                        ),
                    ),
                ],
                confidence=0.72,
            )
        ]

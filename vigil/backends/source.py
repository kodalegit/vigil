from typing import Protocol

from vigil.schemas import Citation, MonitoringInstruction, SourceFinding


class SourceBackend(Protocol):
    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]: ...


class MockSourceBackend:
    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]:
        topic = instruction.query
        jurisdiction = instruction.jurisdiction or "European Union"
        domain = instruction.domain or "AI governance"
        source = instruction.sources[0] if instruction.sources else "mock regulatory source"

        return [
            SourceFinding(
                summary=(
                    f"Potential {domain} update relevant to {topic} in {jurisdiction}. "
                    "The update indicates that deployers of high-risk AI systems need clearer "
                    "human oversight, monitoring, incident escalation, and evidence retention."
                ),
                obligations=[
                    "Maintain documented human oversight procedures for high-risk AI workflows.",
                    "Monitor AI system performance and log incidents that may create material risk.",
                    "Keep technical and compliance evidence available for regulator or auditor review.",
                ],
                citations=[
                    Citation(
                        source=source,
                        title="EU AI Act deployer obligations briefing",
                        snippet=(
                            "Deployers of high-risk AI systems must use them according to instructions, "
                            "assign human oversight, monitor operation, and retain relevant logs."
                        ),
                        url=source if source.startswith("http") else None,
                    )
                ],
                confidence=0.78,
            )
        ]

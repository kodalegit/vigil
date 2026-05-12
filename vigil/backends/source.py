from typing import Protocol

from vigil.schemas import Citation, MonitoringInstruction, SourceFinding


class SourceBackend(Protocol):
    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]: ...


class MockSourceBackend:
    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]:
        topic = instruction.query
        jurisdiction = instruction.jurisdiction or "the selected jurisdiction"
        domain = instruction.domain or "compliance"
        source = instruction.sources[0] if instruction.sources else "mock regulatory source"

        return [
            SourceFinding(
                summary=f"Potential {domain} update relevant to {topic} in {jurisdiction}.",
                obligations=[
                    "Review internal policies for alignment with the detected regulatory change.",
                    "Confirm whether customer-facing terms require updates.",
                ],
                citations=[
                    Citation(
                        source=source,
                        title="Mock regulatory update",
                        snippet="Organizations must review affected procedures and update compliance controls.",
                        url=source if source.startswith("http") else None,
                    )
                ],
                confidence=0.62,
            )
        ]

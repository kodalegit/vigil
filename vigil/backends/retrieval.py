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
                summary="Mock enterprise context suggests finance and contract templates may be affected.",
                affected_artifacts=["Finance SOP", "Customer contract template"],
                citations=[
                    Citation(
                        source="local demo corpus",
                        title="Finance SOP",
                        snippet="Invoices are reviewed according to the previous compliance workflow.",
                    ),
                    Citation(
                        source="local demo corpus",
                        title="Customer contract template",
                        snippet="Tax and regulatory changes are handled under the legacy adjustment clause.",
                    ),
                ],
                confidence=0.58,
            )
        ]

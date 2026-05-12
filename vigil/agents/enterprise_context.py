from vigil.backends.retrieval import RetrievalBackend
from vigil.schemas import EnterpriseFinding, MonitoringInstruction, SourceFinding


class EnterpriseContextAgent:
    def __init__(self, backend: RetrievalBackend) -> None:
        self.backend = backend

    async def search(
        self,
        instruction: MonitoringInstruction,
        source_findings: list[SourceFinding],
    ) -> list[EnterpriseFinding]:
        return await self.backend.search(instruction, source_findings)

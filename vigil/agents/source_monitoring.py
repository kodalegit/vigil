from vigil.backends.source import SourceBackend
from vigil.schemas import MonitoringInstruction, SourceFinding


class SourceMonitoringAgent:
    def __init__(self, backend: SourceBackend) -> None:
        self.backend = backend

    async def search(self, instruction: MonitoringInstruction) -> list[SourceFinding]:
        return await self.backend.search(instruction)

from typing import Protocol

from vigil.schemas import AuditEvent


class AuditBackend(Protocol):
    async def record(self, event: AuditEvent) -> None: ...


class LocalAuditBackend:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)

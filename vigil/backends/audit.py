import json
from pathlib import Path
from typing import Protocol

from vigil.schemas import AuditEvent


class AuditBackend(Protocol):
    async def record(self, event: AuditEvent) -> None: ...

    async def list_events(
        self,
        event_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> list[AuditEvent]: ...


class LocalAuditBackend:
    def __init__(self, path: str | Path | None = None) -> None:
        self.events: list[AuditEvent] = []
        self.path = Path(path) if path else None
        if self.path and self.path.exists():
            self.events = _load_events(self.path)

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(event.model_dump_json() + "\n")

    async def list_events(
        self,
        event_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> list[AuditEvent]:
        events = self.events
        if event_type:
            events = [event for event in events if event.event_type == event_type]
        if metadata:
            events = [
                event
                for event in events
                if all(event.metadata.get(key) == value for key, value in metadata.items())
            ]
        return [event.model_copy(deep=True) for event in events]


def _load_events(path: Path) -> list[AuditEvent]:
    events: list[AuditEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(AuditEvent.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValueError):
            continue
    return events

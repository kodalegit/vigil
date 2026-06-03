import json
from pathlib import Path
from typing import Any, Protocol

from google.cloud import firestore

from vigil.schemas import AuditEvent
from vigil.settings import Settings, get_settings


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


class FirestoreAuditBackend:
    def __init__(
        self,
        settings: Settings | Any | None = None,
        client: Any = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client: Any = client or firestore.Client(project=self.settings.google_cloud_project)
        self.collection_name = f"{self.settings.vigil_firestore_collection_prefix}_audit_events"

    async def record(self, event: AuditEvent) -> None:
        self.client.collection(self.collection_name).document(event.event_id).set(
            event.model_dump(mode="json")
        )

    async def list_events(
        self,
        event_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> list[AuditEvent]:
        query = self.client.collection(self.collection_name)
        if event_type:
            query = query.where("event_type", "==", event_type)
        if metadata:
            for key, value in metadata.items():
                query = query.where(f"metadata.{key}", "==", value)
        snapshots = query.stream()
        events = [
            AuditEvent.model_validate(snapshot.to_dict() or {})
            for snapshot in snapshots
            if snapshot.exists
        ]
        return [event.model_copy(deep=True) for event in events]

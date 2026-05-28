from typing import Any, Literal, Protocol
from uuid import uuid4

from vigil.schemas import MemoryRecord, MemoryTopic, MemoryWriteProposal
from vigil.settings import Settings, get_settings


class MemoryBackend(Protocol):
    async def search(
        self,
        *,
        org_id: str,
        query: str,
        user_id: str | None = None,
        topics: list[str] | None = None,
        limit: int = 5,
    ) -> list[MemoryRecord]: ...

    async def write_approved(self, proposal: MemoryWriteProposal) -> MemoryRecord: ...


_LOCAL_MEMORIES: dict[str, MemoryRecord] = {}


class LocalMemoryBackend:
    async def search(
        self,
        *,
        org_id: str,
        query: str,
        user_id: str | None = None,
        topics: list[str] | None = None,
        limit: int = 5,
    ) -> list[MemoryRecord]:
        query_terms = {term for term in query.lower().split() if len(term) > 2}
        results: list[tuple[int, MemoryRecord]] = []
        for memory in _LOCAL_MEMORIES.values():
            if memory.org_id != org_id:
                continue
            if user_id and memory.user_id and memory.user_id != user_id:
                continue
            if topics and memory.topic not in topics:
                continue
            memory_terms = set(memory.text.lower().split())
            score = len(query_terms & memory_terms)
            if score or not query_terms:
                results.append((score, memory))
        return [
            memory.model_copy(deep=True)
            for _, memory in sorted(results, key=lambda item: item[0], reverse=True)[:limit]
        ]

    async def write_approved(self, proposal: MemoryWriteProposal) -> MemoryRecord:
        if not proposal.approved:
            raise PermissionError("Memory writes require explicit approval.")
        memory = MemoryRecord(
            memory_id=f"mem-{uuid4().hex[:12]}",
            org_id=proposal.org_id,
            user_id=proposal.user_id,
            topic=proposal.topic,
            text=proposal.text,
            registry_refs=proposal.registry_refs,
            provenance="approved_registry"
            if proposal.registry_refs
            else "approved_user_preference",
        )
        _LOCAL_MEMORIES[memory.memory_id] = memory
        return memory.model_copy(deep=True)


class GoogleMemoryBankBackend:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.agent_engine_id = (
            self.settings.vigil_agent_engine_id or self.settings.vigil_memory_bank_name
        )
        if not self.agent_engine_id:
            raise ValueError(
                "VIGIL_AGENT_ENGINE_ID or VIGIL_MEMORY_BANK_NAME must be set for "
                "Google Memory Bank."
            )

    async def search(
        self,
        *,
        org_id: str,
        query: str,
        user_id: str | None = None,
        topics: list[str] | None = None,
        limit: int = 5,
    ) -> list[MemoryRecord]:
        service = self._service()
        response = await service.search_memory(
            app_name="vigil",
            user_id=_scoped_user_id(org_id, user_id),
            query=query,
        )
        records = [
            _memory_entry_to_record(entry, org_id=org_id, user_id=user_id)
            for entry in getattr(response, "memories", []) or []
        ]
        if topics:
            records = [record for record in records if record.topic in topics]
        return records[:limit]

    async def write_approved(self, proposal: MemoryWriteProposal) -> MemoryRecord:
        if not proposal.approved:
            raise PermissionError("Memory writes require explicit approval.")
        from google.adk.memory.memory_entry import MemoryEntry
        from google.genai import types

        memory_id = f"mem-{uuid4().hex[:12]}"
        metadata = {
            "memory_id": memory_id,
            "org_id": proposal.org_id,
            "user_id": proposal.user_id,
            "topic": proposal.topic,
            "registry_refs": proposal.registry_refs,
            "provenance": "approved_registry"
            if proposal.registry_refs
            else "approved_user_preference",
        }
        entry = MemoryEntry(
            id=memory_id,
            content=types.Content(
                role="user",
                parts=[types.Part(text=proposal.text)],
            ),
            author=proposal.user_id or proposal.org_id,
            custom_metadata=metadata,
        )
        await self._service().add_memory(
            app_name="vigil",
            user_id=_scoped_user_id(proposal.org_id, proposal.user_id),
            memories=[entry],
            custom_metadata=metadata,
        )
        return MemoryRecord(
            memory_id=memory_id,
            org_id=proposal.org_id,
            user_id=proposal.user_id,
            topic=proposal.topic,
            text=proposal.text,
            registry_refs=proposal.registry_refs,
            provenance=_provenance(metadata.get("provenance")),
        )

    def _service(self):
        from google.adk.memory import VertexAiMemoryBankService

        return VertexAiMemoryBankService(
            project=self.settings.google_cloud_project,
            location=self.settings.google_cloud_location,
            agent_engine_id=self.agent_engine_id,
        )


def _scoped_user_id(org_id: str, user_id: str | None) -> str:
    if user_id:
        return f"org:{org_id}:user:{user_id}"
    return f"org:{org_id}"


def _memory_entry_to_record(entry: Any, *, org_id: str, user_id: str | None) -> MemoryRecord:
    metadata = getattr(entry, "custom_metadata", None) or {}
    text = _entry_text(entry)
    topic = _topic(metadata.get("topic"))
    return MemoryRecord(
        memory_id=metadata.get("memory_id")
        or getattr(entry, "id", None)
        or f"mem-{uuid4().hex[:12]}",
        org_id=metadata.get("org_id") or org_id,
        user_id=metadata.get("user_id") or user_id,
        topic=topic,
        text=text,
        provenance=_provenance(metadata.get("provenance")),
        registry_refs=list(metadata.get("registry_refs") or []),
    )


def _entry_text(entry: Any) -> str:
    content = getattr(entry, "content", None)
    parts = getattr(content, "parts", None) or []
    return " ".join(part.text for part in parts if getattr(part, "text", None)).strip()


def _topic(value: object) -> MemoryTopic:
    if value == "source_policy":
        return "source_policy"
    if value == "notification_preferences":
        return "notification_preferences"
    if value == "false_positive_patterns":
        return "false_positive_patterns"
    if value == "regulatory_scope":
        return "regulatory_scope"
    if value == "obligation_summaries":
        return "obligation_summaries"
    return "other"


def _provenance(
    value: object,
) -> Literal["approved_registry", "approved_user_preference", "derived"]:
    if value == "approved_registry":
        return "approved_registry"
    if value == "approved_user_preference":
        return "approved_user_preference"
    return "derived"

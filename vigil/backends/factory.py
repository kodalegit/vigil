from dataclasses import dataclass

from vigil.backends.actions import ActionBackend, MockActionBackend, SlackActionBackend
from vigil.backends.audit import AuditBackend, LocalAuditBackend
from vigil.backends.decisions import DecisionStore, FirestoreDecisionStore, LocalDecisionStore
from vigil.backends.memory import GoogleMemoryBankBackend, LocalMemoryBackend, MemoryBackend
from vigil.backends.org_context import (
    FirestoreOrgContextRegistry,
    LocalOrgContextRegistry,
    OrgContextRegistry,
)
from vigil.backends.retrieval import LocalRetrievalBackend, RagEngineRetrievalBackend, RetrievalBackend
from vigil.backends.source import GeminiWebSourceBackend, MockSourceBackend, SourceBackend
from vigil.settings import Settings, get_settings


@dataclass(frozen=True)
class BackendBundle:
    source: SourceBackend
    retrieval: RetrievalBackend
    actions: ActionBackend
    audit: AuditBackend
    org_context: OrgContextRegistry | None = None
    memory: MemoryBackend | None = None
    decisions: DecisionStore | None = None


def create_backends(settings: Settings | None = None) -> BackendBundle:
    settings = settings or get_settings()

    source: SourceBackend
    retrieval: RetrievalBackend
    actions: ActionBackend
    audit: AuditBackend = LocalAuditBackend(settings.vigil_audit_log_path)
    decisions: DecisionStore
    org_context: OrgContextRegistry
    memory: MemoryBackend

    if settings.vigil_storage_backend == "local":
        decisions = LocalDecisionStore(settings.vigil_decision_store_path)
        org_context = LocalOrgContextRegistry()
    elif settings.vigil_storage_backend == "firestore":
        decisions = FirestoreDecisionStore(settings)
        org_context = FirestoreOrgContextRegistry(settings)
    else:
        raise NotImplementedError(f"Unknown storage backend: {settings.vigil_storage_backend}")

    if settings.vigil_source_backend == "mock":
        source = MockSourceBackend()
    elif settings.vigil_source_backend == "gemini_web":
        source = GeminiWebSourceBackend(settings)
    else:
        raise NotImplementedError(f"Unknown source backend: {settings.vigil_source_backend}")

    if settings.vigil_retrieval_backend == "local":
        retrieval = LocalRetrievalBackend(
            top_k=settings.vigil_retrieval_top_k,
            min_score=settings.vigil_retrieval_min_score,
        )
    elif settings.vigil_retrieval_backend == "rag_engine":
        retrieval = RagEngineRetrievalBackend(settings)
    else:
        raise NotImplementedError(f"Unknown retrieval backend: {settings.vigil_retrieval_backend}")

    if settings.vigil_action_backend == "mock":
        actions = MockActionBackend()
    elif settings.vigil_action_backend == "slack":
        actions = SlackActionBackend(settings)
    else:
        raise NotImplementedError(f"Unknown action backend: {settings.vigil_action_backend}")

    if settings.vigil_memory_backend == "local":
        memory = LocalMemoryBackend()
    elif settings.vigil_memory_backend == "google":
        memory = GoogleMemoryBankBackend(settings)
    else:
        raise NotImplementedError(f"Unknown memory backend: {settings.vigil_memory_backend}")

    return BackendBundle(
        source=source,
        retrieval=retrieval,
        actions=actions,
        audit=audit,
        org_context=org_context,
        memory=memory,
        decisions=decisions,
    )

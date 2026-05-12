from dataclasses import dataclass

from vigil.backends.actions import ActionBackend, MockActionBackend
from vigil.backends.audit import AuditBackend, LocalAuditBackend
from vigil.backends.retrieval import LocalRetrievalBackend, RetrievalBackend
from vigil.backends.source import MockSourceBackend, SourceBackend
from vigil.settings import Settings, get_settings


@dataclass(frozen=True)
class BackendBundle:
    source: SourceBackend
    retrieval: RetrievalBackend
    actions: ActionBackend
    audit: AuditBackend


def create_backends(settings: Settings | None = None) -> BackendBundle:
    settings = settings or get_settings()

    source: SourceBackend = MockSourceBackend()
    retrieval: RetrievalBackend = LocalRetrievalBackend()
    actions: ActionBackend = MockActionBackend()
    audit: AuditBackend = LocalAuditBackend()

    if settings.vigil_source_backend != "mock":
        raise NotImplementedError("Only the mock source backend is implemented locally.")
    if settings.vigil_retrieval_backend != "local":
        raise NotImplementedError("Only the local retrieval backend is implemented locally.")
    if settings.vigil_action_backend != "mock":
        raise NotImplementedError("Only the mock action backend is implemented locally.")

    return BackendBundle(source=source, retrieval=retrieval, actions=actions, audit=audit)

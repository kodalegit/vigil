from types import SimpleNamespace

from tests.unit.firestore_fakes import FakeFirestoreClient
from vigil.backends.audit import FirestoreAuditBackend, LocalAuditBackend
from vigil.schemas import AuditEvent


async def test_local_audit_backend_persists_and_reloads_jsonl_events(tmp_path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    audit = LocalAuditBackend(audit_path)
    event = AuditEvent(
        event_type="analysis_started",
        message="Started analysis.",
        metadata={"analysis_id": "analysis-123", "org_id": "acme"},
    )

    await audit.record(event)
    reloaded = LocalAuditBackend(audit_path)
    events = await reloaded.list_events(metadata={"analysis_id": "analysis-123"})

    assert audit_path.exists()
    assert len(events) == 1
    assert events[0].event_id == event.event_id
    assert events[0].metadata["org_id"] == "acme"


async def test_firestore_audit_backend_records_and_filters_events() -> None:
    audit = FirestoreAuditBackend(
        settings=SimpleNamespace(
            google_cloud_project="test-project",
            vigil_firestore_collection_prefix="test_vigil",
        ),
        client=FakeFirestoreClient(),
    )
    first = AuditEvent(
        event_type="analysis_started",
        message="Started analysis.",
        metadata={"analysis_id": "analysis-123", "org_id": "acme"},
    )
    second = AuditEvent(
        event_type="analysis_completed",
        message="Completed analysis.",
        metadata={"analysis_id": "analysis-456", "org_id": "acme"},
    )

    await audit.record(first)
    await audit.record(second)
    events = await audit.list_events(
        event_type="analysis_started",
        metadata={"analysis_id": "analysis-123"},
    )

    assert len(events) == 1
    assert events[0].event_id == first.event_id

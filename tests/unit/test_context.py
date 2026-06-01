from types import SimpleNamespace

import pytest

from tests.unit.firestore_fakes import FakeFirestoreClient
from vigil.backends.memory import LocalMemoryBackend
from vigil.backends.org_context import (
    FirestoreOrgContextRegistry,
    LocalOrgContextRegistry,
    build_context_update_proposal,
)
from vigil.context import ContextCompiler
from vigil.schemas import MemoryWriteProposal, MonitoringInstruction


async def test_context_compiler_applies_registry_defaults_and_source_allowlist() -> None:
    compiler = ContextCompiler(
        registry=LocalOrgContextRegistry(),
        memory=LocalMemoryBackend(),
    )

    pack = await compiler.compile(
        MonitoringInstruction(
            query="EU AI Act deployer obligations",
            sources=["https://untrusted.example.com/rule"],
        )
    )

    assert pack.instruction.jurisdiction is None
    assert pack.instruction.domain is None
    assert pack.instruction.sources == []
    assert any(item.field == "sources" for item in pack.provenance)
    assert pack.instruction.source_freshness_days is None
    assert "Organization: Default Organization" in (pack.instruction.org_context_summary or "")


async def test_context_compiler_uses_approved_matching_allowlisted_source_when_none_requested() -> None:
    registry = LocalOrgContextRegistry()
    proposal = await build_context_update_proposal(
        registry,
        org_id="configured-org",
        summary="Configure EU AI Act monitoring.",
        updates={
            "profile": {"jurisdictions": ["European Union"]},
            "source_policy": {
                "allowlisted_sources": [
                    {
                        "source_id": "eu-ai-act-briefing",
                        "name": "EU AI Act briefing",
                        "url": "https://artificialintelligenceact.eu/",
                        "jurisdictions": ["European Union"],
                        "domains": ["AI governance"],
                        "regulators": ["European Union"],
                        "trust_level": "trusted",
                        "freshness_days": 30,
                    }
                ],
                "require_allowlist": True,
            },
        },
        approved=True,
    )
    await registry.commit_proposal(proposal.proposal_id, approved=True)
    compiler = ContextCompiler(registry=registry, memory=LocalMemoryBackend())

    pack = await compiler.compile(
        MonitoringInstruction(
            org_id="configured-org",
            query="EU AI Act deployer obligations",
            jurisdiction="European Union",
            domain="AI governance",
        )
    )

    assert pack.instruction.sources == ["https://artificialintelligenceact.eu/"]
    assert pack.instruction.source_freshness_days == 30
    assert "Jurisdictions: European Union" in (pack.instruction.org_context_summary or "")
    assert any(item.field == "source_freshness_days" for item in pack.provenance)


async def test_local_memory_requires_explicit_approval() -> None:
    memory = LocalMemoryBackend()
    proposal = MemoryWriteProposal(
        topic="notification_preferences",
        text="Send EU AI Act alerts to #legal-review.",
        approved=False,
    )

    with pytest.raises(PermissionError):
        await memory.write_approved(proposal)

    written = await memory.write_approved(proposal.model_copy(update={"approved": True}))
    results = await memory.search(
        org_id=proposal.org_id,
        query="EU AI Act legal review",
        topics=["notification_preferences"],
    )

    assert written in results


async def test_context_update_proposal_rejects_invalid_required_context() -> None:
    registry = LocalOrgContextRegistry()

    with pytest.raises(ValueError, match="at least one jurisdiction"):
        await build_context_update_proposal(
            registry,
            org_id="invalid-org",
            summary="Remove required jurisdiction context.",
            updates={
                "profile": {"jurisdictions": [], "sectors": ["financial services"]},
            },
            approved=True,
        )


async def test_context_update_proposal_validates_retrieval_resources() -> None:
    registry = LocalOrgContextRegistry()

    with pytest.raises(ValueError, match="requires a RAG corpus"):
        await build_context_update_proposal(
            registry,
            org_id="invalid-retrieval-org",
            summary="Add incomplete retrieval resource.",
            updates={
                "retrieval_resources": [
                    {
                        "resource_id": "rag",
                        "name": "RAG corpus",
                        "source_type": "rag_engine",
                    }
                ]
            },
            approved=True,
        )


async def test_context_update_proposal_validates_and_commits_approved_changes() -> None:
    registry = LocalOrgContextRegistry()
    proposal = await build_context_update_proposal(
        registry,
        org_id="acme",
        summary="Route AI alerts to legal.",
        updates={
            "profile": {"jurisdictions": ["European Union", "United States"]},
            "slack_preferences": {"default_channel": "#legal-review"},
        },
        approved=True,
    )

    errors = await registry.validate_proposal(proposal)
    result = await registry.commit_proposal(proposal.proposal_id, approved=True)
    context = await registry.get_context("acme")

    assert errors == []
    assert result.committed is True
    assert context.profile.jurisdictions == ["European Union", "United States"]
    assert context.slack_preferences.default_channel == "#legal-review"


async def test_firestore_org_context_registry_persists_proposals_and_context() -> None:
    registry = FirestoreOrgContextRegistry(
        settings=SimpleNamespace(
            google_cloud_project="test-project",
            vigil_firestore_collection_prefix="test_vigil",
        ),
        client=FakeFirestoreClient(),
    )
    proposal = await build_context_update_proposal(
        registry,
        org_id="firestore-org",
        summary="Persist legal review routing.",
        updates={
            "profile": {"jurisdictions": ["European Union", "United States"]},
            "slack_preferences": {"default_channel": "#legal-review"},
        },
        approved=True,
    )

    saved_proposal = await registry.get_proposal(proposal.proposal_id)
    result = await registry.commit_proposal(proposal.proposal_id, approved=True)
    context = await registry.get_context("firestore-org")

    assert saved_proposal is not None
    assert result.committed is True
    assert context.profile.jurisdictions == ["European Union", "United States"]
    assert context.slack_preferences.default_channel == "#legal-review"

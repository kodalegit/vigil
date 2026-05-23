import pytest

from vigil.backends.memory import LocalMemoryBackend
from vigil.backends.org_context import LocalOrgContextRegistry, build_context_update_proposal
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

    assert pack.instruction.jurisdiction == "European Union"
    assert pack.instruction.domain == "AI governance"
    assert pack.instruction.sources == []
    assert any(item.field == "sources" for item in pack.provenance)


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

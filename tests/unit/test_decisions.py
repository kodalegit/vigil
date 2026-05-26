from vigil.backends.decisions import LocalDecisionStore
from vigil.schemas import ImpactDecision, RiskLevel


async def test_local_decision_store_saves_loads_and_updates_latest_decision(tmp_path) -> None:
    path = tmp_path / "decisions.jsonl"
    store = LocalDecisionStore(path)
    decision = ImpactDecision(
        analysis_id="analysis-store-test",
        is_actionable=True,
        risk_level=RiskLevel.high,
        classification="actionable",
        summary="Needs approval.",
        approval_required=True,
        approval_status="pending",
        ticket_status="blocked_pending_approval",
    )

    await store.save(decision)
    await store.save(decision.model_copy(update={"approval_status": "approved"}))
    loaded = await LocalDecisionStore(path).get("analysis-store-test")

    assert loaded is not None
    assert loaded.approval_status == "approved"

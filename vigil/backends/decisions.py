import json
from pathlib import Path
from typing import Any, Protocol

from google.cloud import firestore

from vigil.schemas import ImpactDecision
from vigil.settings import Settings, get_settings


class DecisionStore(Protocol):
    async def save(self, decision: ImpactDecision) -> ImpactDecision: ...

    async def get(self, analysis_id: str) -> ImpactDecision | None: ...


class LocalDecisionStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.decisions: dict[str, ImpactDecision] = {}
        self.path = Path(path) if path else None
        if self.path and self.path.exists():
            self.decisions = _load_decisions(self.path)

    async def save(self, decision: ImpactDecision) -> ImpactDecision:
        saved = decision.model_copy(deep=True)
        self.decisions[saved.analysis_id] = saved
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as decision_file:
                decision_file.write(saved.model_dump_json() + "\n")
        return saved.model_copy(deep=True)

    async def get(self, analysis_id: str) -> ImpactDecision | None:
        decision = self.decisions.get(analysis_id)
        return decision.model_copy(deep=True) if decision else None


def _load_decisions(path: Path) -> dict[str, ImpactDecision]:
    decisions: dict[str, ImpactDecision] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            decision = ImpactDecision.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
        decisions[decision.analysis_id] = decision
    return decisions


class FirestoreDecisionStore:
    def __init__(
        self,
        settings: Settings | Any | None = None,
        client: Any = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client: Any = client or firestore.Client(project=self.settings.google_cloud_project)
        self.collection_name = f"{self.settings.vigil_firestore_collection_prefix}_decisions"

    async def save(self, decision: ImpactDecision) -> ImpactDecision:
        saved = decision.model_copy(deep=True)
        self.client.collection(self.collection_name).document(saved.analysis_id).set(
            saved.model_dump(mode="json")
        )
        return saved

    async def get(self, analysis_id: str) -> ImpactDecision | None:
        snapshot = self.client.collection(self.collection_name).document(analysis_id).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        return ImpactDecision.model_validate(data)

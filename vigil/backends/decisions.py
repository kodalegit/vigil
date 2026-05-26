import json
from pathlib import Path
from typing import Protocol

from vigil.schemas import ImpactDecision


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

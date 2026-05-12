from typing import Protocol

from vigil.schemas import ActionResult, ImpactDecision


class ActionBackend(Protocol):
    async def send_alert(self, decision: ImpactDecision) -> ActionResult: ...

    async def generate_report(self, decision: ImpactDecision) -> ActionResult: ...


class MockActionBackend:
    async def send_alert(self, decision: ImpactDecision) -> ActionResult:
        return ActionResult(
            action="send_alert",
            success=True,
            message=f"Mock alert prepared for {decision.risk_level.value} risk decision.",
        )

    async def generate_report(self, decision: ImpactDecision) -> ActionResult:
        return ActionResult(
            action="generate_report",
            success=True,
            message="Mock cited report generated.",
        )

from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from vigil.agents.enterprise_context import EnterpriseContextAgent
from vigil.agents.source_monitoring import SourceMonitoringAgent
from vigil.backends import BackendBundle, create_backends
from vigil.backends.memory import LocalMemoryBackend
from vigil.backends.org_context import LocalOrgContextRegistry, build_context_update_proposal
from vigil.context import ContextCompiler
from vigil.schemas import (
    AuditEvent,
    ContextPack,
    EnterpriseFinding,
    ImpactDecision,
    MonitoringInstruction,
    ObligationRegistryEntry,
    ObligationVersion,
    OrgContext,
    RegulatoryObligation,
    RiskLevel,
    SourceFinding,
)

ImpactClassification = Literal["actionable", "informational", "irrelevant", "ambiguous"]


class VigilOrchestrator:
    def __init__(
        self,
        backends: BackendBundle | None = None,
        source_agent: SourceMonitoringAgent | None = None,
        enterprise_agent: EnterpriseContextAgent | None = None,
    ) -> None:
        self.backends = backends or create_backends()
        if self.backends.org_context is None:
            self.backends = BackendBundle(
                source=self.backends.source,
                retrieval=self.backends.retrieval,
                actions=self.backends.actions,
                audit=self.backends.audit,
                org_context=LocalOrgContextRegistry(),
                memory=self.backends.memory,
                decisions=self.backends.decisions,
            )
        if self.backends.memory is None:
            self.backends = BackendBundle(
                source=self.backends.source,
                retrieval=self.backends.retrieval,
                actions=self.backends.actions,
                audit=self.backends.audit,
                org_context=self.backends.org_context,
                memory=LocalMemoryBackend(),
                decisions=self.backends.decisions,
            )
        self.source_agent = source_agent or SourceMonitoringAgent(self.backends.source)
        self.enterprise_agent = enterprise_agent or EnterpriseContextAgent(self.backends.retrieval)
        self.context_compiler = ContextCompiler(
            registry=self.backends.org_context,
            memory=self.backends.memory,
        )

    async def analyze(self, instruction: MonitoringInstruction) -> ImpactDecision:
        audit_events: list[AuditEvent] = []
        await self._record_audit(
            audit_events,
            event_type="analysis_started",
            message="Started regulatory impact analysis.",
            metadata={"query": instruction.query},
        )
        context_pack = await self.context_compiler.compile(instruction)
        instruction = context_pack.instruction
        await self._record_audit(
            audit_events,
            event_type="context_loaded",
            message="Loaded organization registry context and advisory memories.",
            metadata={
                "org_id": context_pack.org_id,
                "memories": str(len(context_pack.memories)),
                "sources": str(len(instruction.sources)),
            },
        )

        source_findings = await self.source_agent.search(instruction)
        source_findings = await self._record_and_filter_duplicate_source_findings(
            audit_events,
            instruction,
            source_findings,
        )
        await self._record_audit(
            audit_events,
            event_type="source_searched",
            message="Completed source monitoring and obligation extraction.",
            metadata={
                "query": instruction.query,
                "source_findings": str(len(source_findings)),
                "obligations": str(_count_obligations(source_findings)),
            },
        )
        enterprise_findings = await self.enterprise_agent.search(instruction, source_findings)
        await self._record_audit(
            audit_events,
            event_type="enterprise_context_retrieved",
            message="Completed enterprise context retrieval and obligation mapping.",
            metadata={
                "query": instruction.query,
                "enterprise_findings": str(len(enterprise_findings)),
                "chunks": str(_count_chunks(enterprise_findings)),
                "mappings": str(_count_mappings(enterprise_findings)),
            },
        )

        classification = _classify(source_findings, enterprise_findings, context_pack)
        is_actionable = classification == "actionable"
        risk_level = _risk_level(
            classification,
            source_findings,
            enterprise_findings,
            context_pack.org_context,
        )
        recommended_actions = _recommended_actions(classification, context_pack.org_context)

        decision = ImpactDecision(
            org_id=context_pack.org_id,
            is_actionable=is_actionable,
            risk_level=risk_level,
            classification=classification,
            summary=(
                _summary(
                    classification=classification,
                    instruction=instruction,
                    source_findings=source_findings,
                    enterprise_findings=enterprise_findings,
                )
            ),
            recommended_actions=recommended_actions,
            source_findings=source_findings,
            enterprise_findings=enterprise_findings,
            approval_required=is_actionable,
            approval_status="pending" if is_actionable else "not_required",
            ticket_status="blocked_pending_approval" if is_actionable else "not_required",
            audit_events=audit_events.copy(),
            slack_channel=context_pack.org_context.slack_preferences.default_channel,
            reviewer_user_ids=context_pack.org_context.slack_preferences.reviewer_user_ids,
            context_provenance=context_pack.provenance,
            applied_memories=context_pack.memories,
        )

        if decision.is_actionable:
            await self._record_audit(
                audit_events,
                event_type="alert_prepared",
                message="Prepared approval-oriented Slack alert.",
                metadata={
                    "classification": decision.classification,
                    "risk_level": decision.risk_level.value,
                },
            )
            decision.action_results.append(await self.backends.actions.send_alert(decision))
            await self._record_audit(
                audit_events,
                event_type="approval_requested",
                message="Human approval required before remediation ticket creation.",
                metadata={"approval_status": decision.approval_status},
            )
            decision.action_results.append(await self.backends.actions.generate_report(decision))
            ticket_result = await self.backends.actions.create_ticket(
                decision,
                approved=False,
                idempotency_key=_ticket_idempotency_key(decision),
            )
            decision.action_results.append(ticket_result)
            await self._record_audit(
                audit_events,
                event_type="ticket_blocked",
                message="Remediation ticket creation was blocked pending human approval.",
                metadata={
                    "analysis_id": decision.analysis_id,
                    "success": str(ticket_result.success),
                    "idempotency_key": ticket_result.idempotency_key or "",
                },
            )

        await self._record_audit(
            audit_events,
            event_type="analysis_completed",
            message="Completed regulatory impact analysis.",
            metadata={
                "query": instruction.query,
                "classification": decision.classification,
                "risk_level": decision.risk_level.value,
                "is_actionable": str(decision.is_actionable),
            },
        )
        decision.audit_events = audit_events

        if self.backends.decisions is not None:
            decision = await self.backends.decisions.save(decision)

        return decision

    async def record_approval(
        self,
        decision: ImpactDecision,
        approved_by: str,
        approved: bool = True,
        idempotency_key: str | None = None,
    ) -> ImpactDecision:
        audit_events = list(decision.audit_events)
        idempotency_key = idempotency_key or _ticket_idempotency_key(decision)
        if not decision.approval_required:
            await self._record_audit(
                audit_events,
                event_type="approval_not_required",
                message="Approval callback ignored because approval is not required.",
                metadata={
                    "analysis_id": decision.analysis_id,
                    "approved_by": approved_by,
                },
            )
            updated = decision.model_copy(update={"audit_events": audit_events})
            if self.backends.decisions is not None:
                updated = await self.backends.decisions.save(updated)
            return updated
        if not approved:
            await self._record_audit(
                audit_events,
                event_type="approval_rejected",
                message="Human rejected remediation ticket creation.",
                metadata={
                    "analysis_id": decision.analysis_id,
                    "approved_by": approved_by,
                },
            )
            updated = decision.model_copy(
                update={
                    "approval_status": "rejected",
                    "ticket_status": "not_required",
                    "approved_by": approved_by,
                    "approved_at": datetime.now(UTC),
                    "audit_events": audit_events,
                }
            )
            if self.backends.decisions is not None:
                updated = await self.backends.decisions.save(updated)
            return updated
        if decision.ticket_status == "created" and decision.ticket_id:
            await self._record_audit(
                audit_events,
                event_type="approval_idempotent_replay",
                message="Approval callback replayed after ticket was already created.",
                metadata={
                    "analysis_id": decision.analysis_id,
                    "approved_by": approved_by,
                    "ticket_id": decision.ticket_id,
                    "idempotency_key": idempotency_key,
                },
            )
            updated = decision.model_copy(
                update={
                    "approval_status": "approved",
                    "approved_by": decision.approved_by or approved_by,
                    "approved_at": decision.approved_at or datetime.now(UTC),
                    "audit_events": audit_events,
                }
            )
            if self.backends.decisions is not None:
                updated = await self.backends.decisions.save(updated)
            return updated

        approved_decision = decision.model_copy(
            update={
                "approval_status": "approved",
                "approved_by": approved_by,
                "approved_at": datetime.now(UTC),
            },
            deep=True,
        )
        await self._record_audit(
            audit_events,
            event_type="approval_received",
            message="Human approved remediation ticket creation.",
            metadata={
                "analysis_id": decision.analysis_id,
                "approved_by": approved_by,
                "idempotency_key": idempotency_key,
            },
        )
        ticket_result = await self.backends.actions.create_ticket(
            approved_decision,
            approved=True,
            idempotency_key=idempotency_key,
        )
        approved_decision.action_results.append(ticket_result)
        ticket_status = "created" if ticket_result.success else approved_decision.ticket_status
        await self._record_audit(
            audit_events,
            event_type="ticket_created" if ticket_result.success else "ticket_failed",
            message=ticket_result.message,
            metadata={
                "analysis_id": decision.analysis_id,
                "approved_by": approved_by,
                "ticket_id": ticket_result.external_id or "",
                "idempotency_key": idempotency_key,
                "success": str(ticket_result.success),
            },
        )
        updated = approved_decision.model_copy(
            update={
                "ticket_status": ticket_status,
                "ticket_id": ticket_result.external_id,
                "audit_events": audit_events,
            },
            deep=True,
        )
        if self.backends.decisions is not None:
            updated = await self.backends.decisions.save(updated)
        return updated

    async def record_false_positive(
        self,
        decision: ImpactDecision,
        marked_by: str,
    ) -> ImpactDecision:
        audit_events = list(decision.audit_events)
        entries = _false_positive_inventory_entries(decision, marked_by)
        await self._record_audit(
            audit_events,
            event_type="false_positive_recorded",
            message="Human reviewer marked regulatory impact decision as a false positive.",
            metadata={
                "analysis_id": decision.analysis_id,
                "marked_by": marked_by,
                "obligations": str(len(entries)),
            },
        )
        if entries and self.backends.org_context is not None:
            context = await self.backends.org_context.get_context(decision.org_id)
            existing_keys = {
                (entry.obligation_id, entry.canonical_text.lower())
                for entry in context.obligation_inventory
            }
            obligation_inventory = list(context.obligation_inventory)
            obligation_inventory.extend(
                entry
                for entry in entries
                if (entry.obligation_id, entry.canonical_text.lower()) not in existing_keys
            )
            proposal = await build_context_update_proposal(
                self.backends.org_context,
                org_id=decision.org_id,
                summary=("Record approved false-positive obligations from Slack reviewer action."),
                updates={
                    "obligation_inventory": [
                        entry.model_dump(mode="python") for entry in obligation_inventory
                    ]
                },
                requested_by=marked_by,
                approved=True,
            )
            result = await self.backends.org_context.commit_proposal(
                proposal.proposal_id,
                approved=True,
            )
            await self._record_audit(
                audit_events,
                event_type="false_positive_inventory_updated",
                message=result.message,
                metadata={
                    "analysis_id": decision.analysis_id,
                    "proposal_id": proposal.proposal_id,
                    "committed": str(result.committed),
                },
            )

        updated = decision.model_copy(
            update={
                "approval_status": "rejected"
                if decision.approval_required
                else decision.approval_status,
                "ticket_status": "not_required",
                "approved_by": marked_by,
                "approved_at": datetime.now(UTC),
                "audit_events": audit_events,
            },
            deep=True,
        )
        if self.backends.decisions is not None:
            updated = await self.backends.decisions.save(updated)
        return updated

    async def record_follow_up_requested(
        self,
        decision: ImpactDecision,
        requested_by: str,
        note: str | None = None,
    ) -> ImpactDecision:
        audit_events = list(decision.audit_events)
        metadata = {
            "analysis_id": decision.analysis_id,
            "requested_by": requested_by,
        }
        if note:
            metadata["note"] = note[:500]
        await self._record_audit(
            audit_events,
            event_type="follow_up_requested",
            message="Human reviewer requested follow-up before final disposition.",
            metadata=metadata,
        )
        updated = decision.model_copy(update={"audit_events": audit_events}, deep=True)
        if self.backends.decisions is not None:
            updated = await self.backends.decisions.save(updated)
        return updated

    async def _record_audit(
        self,
        audit_events: list[AuditEvent],
        event_type: str,
        message: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        event = AuditEvent(
            event_type=event_type,
            message=message,
            metadata=metadata or {},
        )
        audit_events.append(event)
        await self.backends.audit.record(event)

    async def _record_and_filter_duplicate_source_findings(
        self,
        audit_events: list[AuditEvent],
        instruction: MonitoringInstruction,
        source_findings: list[SourceFinding],
    ) -> list[SourceFinding]:
        if not instruction.suppress_repeated_findings:
            return source_findings
        seen_events = await self.backends.audit.list_events(
            event_type="source_finding_recorded",
            metadata={"org_id": instruction.org_id},
        )
        seen_fingerprints = {
            event.metadata.get("fingerprint")
            for event in seen_events
            if event.metadata.get("fingerprint")
        }
        filtered_findings: list[SourceFinding] = []
        for finding in source_findings:
            duplicate_fingerprints: list[str] = []
            new_obligations = []
            for obligation in finding.obligations:
                fingerprint = _source_obligation_fingerprint(instruction, obligation)
                if fingerprint in seen_fingerprints:
                    duplicate_fingerprints.append(fingerprint)
                    continue
                new_obligations.append(obligation)
                seen_fingerprints.add(fingerprint)
                await self._record_audit(
                    audit_events,
                    event_type="source_finding_recorded",
                    message="Recorded source obligation fingerprint for repeat monitoring.",
                    metadata={
                        "org_id": instruction.org_id,
                        "query": instruction.query,
                        "obligation_id": obligation.id,
                        "fingerprint": fingerprint,
                    },
                )

            if duplicate_fingerprints:
                await self._record_audit(
                    audit_events,
                    event_type="source_finding_duplicate",
                    message="Detected duplicate source obligation from prior monitoring run.",
                    metadata={
                        "org_id": instruction.org_id,
                        "query": instruction.query,
                        "duplicate_count": str(len(duplicate_fingerprints)),
                    },
                )

            if duplicate_fingerprints and not new_obligations and finding.obligations:
                filtered_findings.append(
                    finding.model_copy(
                        update={
                            "obligations": [],
                            "confidence": min(finding.confidence, 0.35),
                            "uncertainty": _append_uncertainty(
                                finding.uncertainty,
                                "This source finding matches a previously recorded monitoring finding.",
                            ),
                            "is_duplicate": True,
                        }
                    )
                )
                continue

            if duplicate_fingerprints:
                filtered_findings.append(
                    finding.model_copy(
                        update={
                            "obligations": new_obligations,
                            "uncertainty": _append_uncertainty(
                                finding.uncertainty,
                                "Some repeated obligations were removed before enterprise retrieval.",
                            ),
                            "is_duplicate": True,
                        }
                    )
                )
                continue

            filtered_findings.append(finding)
        return filtered_findings


def _classify(
    source_findings: list[SourceFinding],
    enterprise_findings: list[EnterpriseFinding],
    context_pack: ContextPack,
) -> ImpactClassification:
    obligation_count = _count_obligations(source_findings)
    chunk_count = _count_chunks(enterprise_findings)
    mapping_count = _count_mappings(enterprise_findings)
    has_uncertainty = any(finding.uncertainty for finding in source_findings)

    if obligation_count and _all_obligations_are_approved_false_positives(
        source_findings,
        context_pack.org_context,
    ):
        return "irrelevant"
    if source_findings and _all_source_findings_are_duplicates(source_findings):
        return "informational"
    if obligation_count > 0 and chunk_count > 0 and mapping_count > 0:
        return "actionable"
    if obligation_count > 0 and chunk_count == 0:
        return "informational"
    if source_findings and obligation_count == 0 and has_uncertainty:
        return "ambiguous"
    return "irrelevant"


def _risk_level(
    classification: str,
    source_findings: list[SourceFinding],
    enterprise_findings: list[EnterpriseFinding],
    org_context: OrgContext,
) -> RiskLevel:
    if classification == "actionable":
        high_obligation = any(
            obligation.risk_level in {RiskLevel.high, RiskLevel.critical}
            for finding in source_findings
            for obligation in finding.obligations
        )
        multi_artifact = (
            len(
                {
                    chunk.document.doc_id
                    for finding in enterprise_findings
                    for chunk in finding.chunks
                }
            )
            > 1
        )
        if high_obligation or multi_artifact or org_context.profile.risk_tolerance == RiskLevel.low:
            return RiskLevel.high
        return RiskLevel.medium
    if classification in {"informational", "ambiguous"}:
        return RiskLevel.medium
    return RiskLevel.low


def _recommended_actions(classification: str, org_context: OrgContext) -> list[str]:
    channel = org_context.slack_preferences.default_channel
    if classification == "actionable":
        return [
            f"Send a compliance impact alert to {channel}.",
            "Request human approval before creating remediation tasks.",
            "Update human oversight, monitoring, incident escalation, and evidence retention controls.",
            "Generate a cited impact report for the audit trail.",
        ]
    if classification == "informational":
        return [
            "Record the source update and monitor for enterprise impact.",
            "Do not create remediation tasks until relevant internal artifacts are identified.",
        ]
    if classification == "ambiguous":
        return [
            "Ask for clarification or retrieve stronger official source evidence.",
            "Do not alert broadly or create remediation tasks yet.",
        ]
    return ["No action recommended unless new evidence appears."]


def _summary(
    classification: str,
    instruction: MonitoringInstruction,
    source_findings: list[SourceFinding],
    enterprise_findings: list[EnterpriseFinding],
) -> str:
    artifact_count = len(
        {chunk.document.doc_id for finding in enterprise_findings for chunk in finding.chunks}
    )
    obligation_count = _count_obligations(source_findings)
    if classification == "actionable":
        return (
            f"Vigil found {obligation_count} evidence-backed obligation(s) for "
            f"{instruction.query} with matching enterprise context across "
            f"{artifact_count} artifact(s). Human approval is required before ticket creation."
        )
    if classification == "informational":
        if obligation_count == 0 and _all_source_findings_are_duplicates(source_findings):
            return (
                f"Vigil found only duplicate source finding(s) for {instruction.query}; "
                "no new obligations were sent for enterprise impact mapping."
            )
        return (
            f"Vigil found {obligation_count} source obligation(s) for {instruction.query}, "
            "but did not find matching enterprise artifacts in the current corpus."
        )
    if classification == "ambiguous":
        return (
            f"Vigil found source material for {instruction.query}, but the evidence was too "
            "uncertain to extract obligations or recommend action."
        )
    return f"Vigil did not find enough source or enterprise evidence for {instruction.query}."


def _count_obligations(source_findings: list[SourceFinding]) -> int:
    return sum(len(finding.obligations) for finding in source_findings)


def _count_chunks(enterprise_findings: list[EnterpriseFinding]) -> int:
    return sum(len(finding.chunks) for finding in enterprise_findings)


def _count_mappings(enterprise_findings: list[EnterpriseFinding]) -> int:
    return sum(len(finding.mappings) for finding in enterprise_findings)


def _ticket_idempotency_key(decision: ImpactDecision) -> str:
    return f"ticket:{decision.org_id}:{decision.analysis_id}"


def _source_obligation_fingerprint(
    instruction: MonitoringInstruction,
    obligation: RegulatoryObligation,
) -> str:
    material = "|".join(
        [
            instruction.org_id,
            obligation.jurisdiction.lower(),
            obligation.id.lower(),
            obligation.section_id or "",
            obligation.source_url or "",
            " ".join(obligation.text.lower().split()),
        ]
    )
    return sha256(material.encode("utf-8")).hexdigest()


def _append_uncertainty(current: str | None, note: str) -> str:
    if not current:
        return note
    if note in current:
        return current
    return f"{current} {note}"


def _all_source_findings_are_duplicates(source_findings: list[SourceFinding]) -> bool:
    return bool(source_findings) and all(finding.is_duplicate for finding in source_findings)


def _all_obligations_are_approved_false_positives(
    source_findings: list[SourceFinding],
    org_context: OrgContext,
) -> bool:
    obligations = [obligation for finding in source_findings for obligation in finding.obligations]
    if not obligations:
        return False
    false_positive_keys = {
        (entry.obligation_id, entry.canonical_text.lower())
        for entry in org_context.obligation_inventory
        if entry.status == "false_positive" and entry.approval_status == "approved"
    }
    for obligation in obligations:
        key = (obligation.id, obligation.text.lower())
        text_match = any(obligation.text.lower() == text for _, text in false_positive_keys)
        id_match = any(obligation.id == obligation_id for obligation_id, _ in false_positive_keys)
        if not (key in false_positive_keys or id_match or text_match):
            return False
    return True


def _false_positive_inventory_entries(
    decision: ImpactDecision,
    marked_by: str,
) -> list[ObligationRegistryEntry]:
    entries: list[ObligationRegistryEntry] = []
    for finding in decision.source_findings:
        for obligation in finding.obligations:
            content_hash = sha256(obligation.text.lower().encode("utf-8")).hexdigest()
            entries.append(
                ObligationRegistryEntry(
                    obligation_id=obligation.id,
                    jurisdiction=obligation.jurisdiction,
                    source_url=obligation.source_url,
                    section_ref=obligation.section_id,
                    canonical_text=obligation.text,
                    topics=obligation.topics,
                    effective_date=obligation.effective_date,
                    status="false_positive",
                    confidence=obligation.confidence,
                    approval_status="approved",
                    evidence_snippets=[obligation.source_quote],
                    owners=[marked_by],
                    versions=[
                        ObligationVersion(
                            version=1,
                            canonical_text=obligation.text,
                            source_quote=obligation.source_quote,
                            source_url=obligation.source_url,
                            section_ref=obligation.section_id,
                            effective_date=obligation.effective_date,
                            content_hash=content_hash,
                        )
                    ],
                )
            )
    return entries

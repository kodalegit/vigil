# Vigil Phased Implementation Plan

Last updated: 2026-05-23

This plan tracks what has actually been built, what design decisions are now settled, and what remains before Vigil is ready for a credible hackathon demo and a Google Cloud production path. It supports the system design in `docs/vigil-system-design.md`.

## 1. Current Product Direction

Vigil is a regulatory impact agent for lean legal, compliance, and AI governance teams. The flagship scenario is:

1. Search or monitor trusted regulatory sources for AI governance changes.
2. Extract evidence-backed regulatory obligations.
3. Retrieve relevant internal policies, controls, SOPs, templates, and inventories.
4. Map obligations to affected enterprise artifacts and owners.
5. Classify the event as actionable, informational, irrelevant, or uncertain.
6. Prepare a Slack-style alert and cited report.
7. Require human approval before remediation ticket creation.
8. Preserve an audit trail for the decision and external actions.

The current MVP domain is EU AI Act-style high-risk AI deployer obligations mapped against a synthetic AI governance corpus.

## 2. Architecture Decisions Now Locked For MVP

### 2.1 Agent Architecture

Use ADK hierarchical task decomposition:

- `vigil_orchestrator` is the parent agent and owns final judgment.
- `source_monitoring_agent` is called as an `AgentTool` to gather trusted source evidence and candidate obligations.
- `enterprise_context_agent` is called as an `AgentTool` to map obligations to internal enterprise artifacts.
- Subagents return bounded, cited context. They do not decide final impact, alert priority, or approval state.

We prefer callable subagents over LLM-driven transfer because Vigil needs the parent to collect both source and enterprise findings before producing one decision. Fixed workflow agents can be added later for scheduled batch monitoring, but they are not the core interactive architecture yet.

### 2.2 Obligation Extraction

Obligation extraction belongs in the source monitoring layer.

The source monitoring backend should use the model to synthesize grounded source text into a predetermined schema. Deterministic extraction is only a fallback when structured model extraction is unavailable or invalid.

The orchestrator should not perform low-level obligation extraction. It should use organization/session/memory context to select, prioritize, downgrade, or ask follow-up questions about candidate obligations returned by the source layer.

Current flow:

```text
Gemini Google Search grounding
  -> grounded source analysis
  -> structured model extraction into RegulatoryObligation objects
  -> conservative deterministic fallback only if structured extraction fails
  -> orchestrator impact decision
```

### 2.3 Enterprise Retrieval

RAG Engine / indexed retrieval is the primary enterprise retrieval path. Google Drive MCP is auxiliary.

The retrieval contract must stay stable across local and Google-managed implementations:

- query
- metadata filters
- `top_k`
- chunks
- document metadata
- citations
- relevance score
- permission-safe links
- obligation-to-chunk mappings

Local indexed retrieval is the default demo path. Vertex AI RAG Engine over Drive or Cloud Storage is the production path. Drive MCP is reserved for file lookup, metadata, previews, and refresh workflows.

### 2.4 Source Monitoring

Source monitoring has two modes:

- `mock`: deterministic source findings for tests and local demo stability.
- `gemini_web`: Gemini Google Search grounding plus structured obligation extraction.

The source layer must preserve URLs, titles, snippets, retrieved timestamps, confidence, and uncertainty. It must avoid legal-advice language.

### 2.5 Memory And Sessions

Sessions are for short-lived investigation state:

- current monitoring instruction
- selected sources
- latest source evidence
- latest enterprise mappings
- pending approval state
- follow-up answers

Memory Bank is deferred until we have recurring user or organization preferences worth preserving:

- jurisdictions
- regulated products
- preferred Slack channel
- reviewers
- risk tolerance
- recurring monitoring preferences
- known false positives

Audit evidence, source findings, approval decisions, and tickets belong in audit records, not long-term memory.

### 2.6 Slack And Actions

Slack is an operational integration, not the retrieval system.

For MVP, keep Slack mocked behind `ActionBackend` and generate a safe Slack payload with:

- classification
- priority
- what changed
- why it matters
- affected artifacts
- short snippets
- suggested actions
- approval buttons

Real Slack posting, signature verification, callback handling, and idempotent ticket creation come after retrieval/source quality is reliable.

## 3. Implemented So Far

### 3.1 Project Foundation

Status: done

Implemented:

- Python package under `vigil/`.
- `uv`-managed project dependencies.
- ADK-compatible `vigil/agent.py` with `root_agent` and `app`.
- FastAPI app scaffold in `vigil/fast_api_app.py`.
- Local CLI demo entrypoint in `vigil/cli.py`.
- Settings loader in `vigil/settings.py`.
- `.env.example` with local, Google, RAG, and Slack configuration placeholders.

### 3.2 Core Schemas

Status: done

Implemented structured contracts in `vigil/schemas.py`:

- `MonitoringInstruction`
- `Citation`
- `RegulatoryObligation`
- `SourceEvidence`
- `EnterpriseDocument`
- `EnterpriseChunk`
- `ObligationMapping`
- `SourceFinding`
- `EnterpriseFinding`
- `EvidencePacket`
- `ImpactDecision`
- `ActionResult`
- `AuditEvent`

Recent decision captured: source findings now carry first-class obligations and evidence rather than mostly free-text summaries. Enterprise findings carry chunks and obligation mappings rather than broad document names.

### 3.3 ADK Agent Skeleton

Status: done

Implemented:

- `vigil_orchestrator`
- `source_monitoring_agent`
- `enterprise_context_agent`
- `AgentTool` wrapping for source and enterprise subagents.
- Tool functions:
  - `analyze_regulatory_sources`
  - `map_enterprise_context`
  - `run_regulatory_impact_analysis`

Current orchestrator instructions require:

- source monitoring first
- enterprise context mapping second
- final impact synthesis by the orchestrator
- no final legal advice
- approval before remediation ticket creation

### 3.4 Source Monitoring Backend

Status: partially done

Implemented:

- `MockSourceBackend` with deterministic EU AI Act-style obligations.
- `GeminiWebSourceBackend` using Gemini Google Search grounding.
- Structured obligation extraction using model JSON output.
- `ObligationExtractionResult` schema for extraction.
- Conservative deterministic fallback when structured extraction fails.
- Parser support for fenced JSON model output.
- Confidence and uncertainty propagation.

Still needed:

- Better official-source prompting and source allowlists.
- Configurable monitored source sets.
- Date/change detection for repeat monitoring.
- Tests using mocked Gemini responses around grounding metadata and extraction failures.
- Guardrails for source freshness and duplicate findings.

### 3.5 Enterprise Retrieval Backend

Status: partially done

Implemented:

- `RetrievalBackend` interface.
- `LocalRetrievalBackend` over local Markdown corpus.
- Metadata-aware Markdown chunking.
- Lightweight deterministic lexical retrieval with phrase/synonym expansion.
- `ObligationMapping` generation from obligations to chunks.
- Synthetic local corpus:
  - AI Governance Policy
  - Model Risk Control Register
  - AI Incident Response SOP
  - Vendor AI Policy
  - DPIA Template
  - Model Inventory
- `RagEngineRetrievalBackend` scaffold behind the same interface.
- `scripts/import_drive_to_rag.py` for Drive/GCS import into Vertex AI RAG Engine.

Still needed:

- Metadata filters by jurisdiction, artifact type, owner, product, and business unit.
- Better chunking and ranking.
- Tests for RAG response normalization.
- Real RAG Engine smoke test with a Google Cloud corpus.
- Drive sharing documentation for the Vertex RAG Data Service Agent in the main README.

### 3.6 Actions And Audit

Status: partially done

Implemented:

- `ActionBackend` interface.
- `MockActionBackend`.
- Slack payload builder with approval buttons.
- Safe snippet truncation for Slack payloads.
- Basic mock report result.
- Basic local audit backend exists.

Still needed:

- Real audit storage schema and persisted records.
- Explicit audit events for analysis started, source searched, retrieval completed, alert prepared, approval requested, approval received, ticket created, and false positive recorded.
- Real Slack app integration.
- Slack request signing verification.
- Approval callback model.
- Idempotency keys for approval and ticket creation.
- Mock ticket creation flow after approval.

### 3.7 Tests And Evals

Status: partially done

Implemented:

- Unit tests for source extraction and fallback behavior.
- Unit tests for local retrieval.
- Unit tests for Slack payload safety.
- Integration tests for agent structure and local analysis loop.
- Basic ADK evalset for the EU AI Act happy path.

Most recent verified commands:

```text
uv run --extra dev pytest -s tests/unit/test_source.py
uv run --extra dev pytest -s tests/unit tests/integration/test_agent.py
uv run --extra dev ruff check .
agents-cli eval run --evalset tests/eval/evalsets/basic.evalset.json --config tests/eval/eval_config.json
```

Latest known result: unit/integration tests, lint, and the basic ADK eval passed.

Known tooling note:

- `agents-cli` reported a CLI/skills version mismatch. The CLI is newer than the installed local Google agent skills. Run `agents-cli update` before serious deployment or scaffold work.

## 4. Current MVP Slice

This is the slice we should finish before adding more cloud complexity:

```text
User instruction
  -> ADK orchestrator
  -> source_monitoring_agent
      -> mock or Gemini web source backend
      -> structured obligations with citations
  -> enterprise_context_agent
      -> local indexed corpus retrieval
      -> obligation-to-artifact mappings
  -> orchestrator final decision
      -> classification
      -> recommended actions
      -> mock Slack alert payload
      -> audit narrative
      -> approval required before ticket
```

The demo should be reliable with mock source + local corpus, then optionally show Gemini web source mode if credentials and network behavior are stable.

## 5. Immediate Next Phase: Tighten The Local Impact Loop

Status: next

Goal:

Make the end-to-end local loop reliable, explainable, and demo-ready before adding real Slack or managed RAG.

Tasks:

- Improve `VigilOrchestrator.analyze` decision logic so it explicitly distinguishes:
  - actionable
  - informational
  - irrelevant
  - ambiguous / needs clarification
- Make actionability require both source obligations and relevant enterprise evidence.
- Add explicit approval state to the decision or action result model.
- Persist local audit events for each material step.
- Add an approval-gated mock ticket creation path.
- Add a repeatable demo command for the flagship EU AI Act scenario.
- Add a second demo/eval case for an irrelevant or low-impact update.
- Add a third demo/eval case for ambiguous source evidence.

Exit criteria:

- A local run produces a cited decision with source obligations, affected artifacts, recommended actions, mock Slack payload, approval requirement, and audit record.
- Irrelevant updates do not create high-priority alerts.
- Ambiguous sources are marked uncertain or ask for clarification.

## 6. Phase: Retrieval Quality And Corpus Hardening

Status: next after local loop tightening

Goal:

Make enterprise mapping strong enough that the demo feels like real RAG-backed compliance work.

Tasks:

- Add metadata filters to `RetrievalBackend.search`.
- Add richer metadata to local corpus docs:
  - jurisdiction
  - product
  - system class
  - owner
  - review cadence
  - business unit
- Improve chunking for sections, headings, tables, and short policy clauses.
- Add score thresholds so weak retrieval does not produce false affected artifacts.
- Add mapping rationale tests.
- Add “no matching enterprise artifact” test and eval.
- Add citation quality eval that penalizes hallucinated owners or documents.

Exit criteria:

- Enterprise retrieval returns precise snippets and mappings for known obligations.
- Weak or unrelated queries produce informational/irrelevant decisions instead of false positives.

## 7. Phase: Gemini Web Source Robustness

Status: planned

Goal:

Make `VIGIL_SOURCE_BACKEND=gemini_web` reliable enough for live demo use.

Tasks:

- Add source allowlist and trusted-source profiles.
- Support official source preferences per jurisdiction/domain.
- Normalize source dates and retrieved timestamps.
- Detect ambiguity and return no obligations when evidence is insufficient.
- Add mocked Gemini response tests for:
  - valid structured output
  - fenced JSON
  - invalid JSON fallback
  - no obligations found
  - grounded results with missing snippets
- Add eval case for live web-backed source search if credentials are available.

Exit criteria:

- Gemini web mode returns structured source findings with obligations only when the evidence supports them.
- Fallback behavior is conservative and visible in uncertainty.

## 8. Phase: RAG Engine And Google Drive Integration

Status: planned

Goal:

Validate the production retrieval path over Google-managed infrastructure.

Tasks:

- Create or select a Google Cloud project and location.
- Create a Vertex AI RAG Engine corpus.
- Import local demo docs from GCS or Drive using `scripts/import_drive_to_rag.py`.
- Import a shared Drive folder/file set.
- Grant the Vertex RAG Data Service Agent viewer access to selected Drive files/folders.
- Configure:
  - `VIGIL_RETRIEVAL_BACKEND=rag_engine`
  - `VIGIL_RAG_CORPUS`
  - `VIGIL_RAG_DISTANCE_THRESHOLD`
  - `VIGIL_RETRIEVAL_TOP_K`
- Run a smoke test comparing local retrieval and RAG Engine retrieval for the flagship scenario.
- Document the Drive MCP auxiliary role and decide whether to add it for file preview/refresh.

Exit criteria:

- The enterprise context agent can retrieve cited chunks from RAG Engine through the same contract used by local retrieval.
- The local demo can switch between local and RAG retrieval by environment variable.

## 9. Phase: Slack, Approvals, Tickets, And Audit

Status: planned

Goal:

Turn impact analysis into an operational workflow.

Tasks:

- Add Slack app configuration docs.
- Implement real Slack posting behind `ActionBackend`.
- Add Slack signing-secret verification.
- Add approval callback endpoint.
- Add idempotent approval handling.
- Add mock ticket creation after approval.
- Add false-positive handling and audit event.
- Ensure Slack payloads contain only safe snippets and permission-safe links.
- Add tests for approval state transitions and idempotency.

Exit criteria:

- Vigil posts an alert, receives approval, creates a mock ticket once, and records the full audit trail.

## 10. Phase: Agent Runtime Readiness

Status: planned

Goal:

Prepare Vigil for Gemini Enterprise Agent Platform deployment.

Tasks:

- Run `agents-cli update`.
- Review `agents-cli info` and project metadata.
- Run `agents-cli scaffold upgrade` if needed for current CLI compatibility.
- Run `agents-cli scaffold enhance . --deployment-target agent_runtime` when the local MVP passes evals.
- Configure service account roles.
- Move secrets to Secret Manager.
- Configure Cloud Logging and Cloud Trace.
- Prepare Agent Platform Sessions.
- Defer Memory Bank until recurring organization preferences are implemented.
- Keep Cloud Run as fallback only if Agent Runtime blocks hackathon delivery.

Exit criteria:

- Vigil has a clean Agent Runtime deployment path with environment configuration, secrets plan, IAM checklist, and logging/tracing expectations.

## 11. Phase: Hackathon Demo Package

Status: planned

Goal:

Package the work so judges understand the business result, not just the agent internals.

Tasks:

- Write a crisp README demo path.
- Add one-command local demo instructions.
- Add architecture diagram.
- Add demo narrative:
  - source update
  - extracted obligations
  - affected internal artifacts
  - Slack approval
  - audit trail
- Add screenshots or terminal output snippets.
- Add eval results summary.
- Prepare a short video script.

Exit criteria:

- A judge can run or watch Vigil complete the regulatory impact loop and see clear use of ADK, Gemini, structured outputs, RAG-ready retrieval, and Google Cloud production primitives.

## 12. Deferred Work

These are valuable, but not part of the immediate MVP:

- Memory Bank integration for durable organization preferences.
- Google Drive MCP for preview/refresh workflows.
- Slack search or Gemini Enterprise Slack federation as an enterprise retrieval source.
- Real Jira, Linear, ServiceNow, or GitHub issue creation.
- Scheduled monitoring jobs.
- Multimodal retrieval over slides, screenshots, audio, and PDFs.
- Model Armor or policy filters before external Slack posting.
- Marketplace packaging and full Gemini Enterprise registration.

## 13. Working Definition Of Done

For each implementation phase, do not consider it complete until:

- The code path is behind a stable interface or environment switch.
- Unit tests cover deterministic behavior and failure cases.
- At least one integration test covers the end-to-end path.
- ADK evals cover expected agent behavior.
- Citations and uncertainty are preserved.
- External actions are either mocked or approval-gated.
- The docs explain how to run, configure, and verify the feature.

## 14. Recommended Next Engineering Task

Implement local audit persistence and explicit approval/ticket state in the orchestrator path.

Why this is next:

- Source extraction is now structured.
- Local retrieval exists.
- Slack payload building exists.
- The biggest remaining product gap is the operational loop: decision, approval requirement, ticket gating, and audit record.

Suggested order:

1. Extend `ImpactDecision` or add an approval/ticket model.
2. Persist audit events for each local analysis step.
3. Add mock ticket creation that refuses to run without approval.
4. Update Slack payload tests around approval state.
5. Add eval cases for irrelevant and ambiguous updates.

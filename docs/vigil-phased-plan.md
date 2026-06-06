# Vigil Phased Implementation Plan

Last updated: 2026-05-26

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

Use ADK 2-compatible hierarchical task decomposition:

- `vigil_orchestrator` is the parent agent and owns final judgment.
- `source_monitoring_agent` is called as an `AgentTool` to gather trusted source evidence and candidate obligations.
- `enterprise_context_agent` is called as an `AgentTool` to map obligations to internal enterprise artifacts.
- Subagents return bounded, cited context. They do not decide final impact, alert priority, or approval state.

We prefer callable subagents over LLM-driven transfer because Vigil needs the parent to collect both source and enterprise findings before producing one decision. ADK 2 workflow graphs can be added later for scheduled batch monitoring, but they are not the core interactive architecture yet.

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

### 2.5 Memory, Registry, And Sessions

Sessions are for short-lived investigation state:

- current monitoring instruction
- selected sources
- latest source evidence
- latest enterprise mappings
- pending approval state
- follow-up answers

Memory Bank is wired behind a backend seam for recurring user or organization preferences:

- jurisdictions
- regulated products
- preferred Slack channel
- reviewers
- risk tolerance
- recurring monitoring preferences
- known false positives

Audit evidence, source findings, approval decisions, and tickets belong in audit records, not long-term memory.

The typed organization context registry is the source of truth for critical context:

- org profile
- source allowlists
- Slack preferences
- monitoring profiles
- obligation inventory

Memory records are advisory and should only be written after explicit approval.

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
- Deterministic mock scenarios for unrelated shipping obligations and ambiguous consultations.
- `GeminiWebSourceBackend` using Gemini Google Search grounding.
- Allowlist-aware Gemini grounded-search prompt construction from monitoring source policy.
- Source freshness windows propagated from trusted source policy into monitoring instructions.
- Grounded source date normalization for common web date formats.
- Duplicate source evidence/citation removal and stale-source suppression guardrails.
- Structured obligation extraction using model JSON output.
- `ObligationExtractionResult` schema for extraction.
- Conservative deterministic fallback when structured extraction fails.
- Parser support for fenced JSON model output.
- Confidence and uncertainty propagation.
- Unit coverage for missing grounding snippets, allowlist prompt text, no-obligation ambiguity, unrelated source findings, source date normalization, and stale-source guardrails.

Still needed:

- Configurable monitored source sets.
- Change detection for repeat monitoring.
- More mocked Gemini response tests around grounding metadata, source dates, and extraction failures.
- Guardrails for materially duplicate findings across monitoring runs.

### 3.5 Enterprise Retrieval Backend

Status: partially done

Implemented:

- `RetrievalBackend` interface.
- `LocalRetrievalBackend` over local Markdown corpus.
- Metadata-aware Markdown chunking.
- Lightweight deterministic lexical retrieval with phrase/synonym expansion.
- `ObligationMapping` generation from obligations to chunks.
- Metadata filters by jurisdiction, artifact type, owner, product, system class, review cadence, and business unit for local retrieval.
- Local corpus metadata for jurisdiction, product, system class, and review cadence.
- Configurable local retrieval score threshold.
- Retrieval drops candidate chunks when no obligation-to-chunk mapping survives.
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

- Better chunking and ranking for tables, very short clauses, and dense policy sections.
- Tests for RAG response normalization.
- Real RAG Engine smoke test with a Google Cloud corpus.
- Drive sharing documentation for the Vertex RAG Data Service Agent in the main README.

### 3.6 Context, Memory, Actions, And Audit

Status: partially done

Implemented:

- `OrgContextRegistry` interface with a local in-process implementation.
- `MemoryBackend` interface with approval-gated local memory writes.
- `ContextCompiler` for registry defaults, allowlisted sources, provenance, and advisory memory loading.
- Agent tools for profile inspection, context update proposal, validation, approved commit, memory search, and approved memory writes.
- `ActionBackend` interface.
- `MockActionBackend`.
- Slack payload builder with approval buttons.
- Safe snippet truncation for Slack payloads.
- Basic mock report result.
- Local audit backend with optional JSONL persistence.
- Approval callback path that creates a mock ticket after human approval.
- Idempotency keys for approval-driven mock ticket creation.
- Local decision store for persisting impact decisions and approval updates.
- Firestore-backed decision store for production `analysis_id` lookups.
- Firestore-backed org context registry for approved profiles, source allowlists, Slack preferences, monitoring profiles, and proposal records.
- Slack signed-request verification and verified interaction endpoint.
- Slack approval callbacks can approve stored decisions when the button value includes `analysis_id`.
- Slack false-positive callbacks record approved false-positive obligations in the org context registry for future suppression.
- `SlackActionBackend` posts Block Kit alerts through Slack Web API when `VIGIL_ACTION_BACKEND=slack`.

Still needed:

- Google Memory Bank deployment smoke test after Agent Runtime identifiers and IAM are available.
- Firestore live smoke test for org context registry and decision store.
- Production audit storage backend beyond local JSONL.
- Real Slack workspace smoke test with a configured app, bot token, and signing secret.
- Reviewer authorization checks for Slack callback actions.

### 3.7 Tests And Evals

Status: partially done

Implemented:

- Unit tests for source extraction and fallback behavior.
- Unit tests for local retrieval.
- Unit tests for local retrieval metadata filters, score thresholds, no-match behavior, and mapping rationale.
- Unit tests for Slack payload safety.
- Integration tests for agent structure and local analysis loop.
- Unit tests for local audit persistence.
- Unit and integration tests for approval-gated ticket creation and idempotency.
- Basic ADK evalset for the EU AI Act happy path.
- Retrieval-quality ADK evalset covering unrelated no-match obligations and ambiguous source evidence.
- General-enterprise ADK evalset covering privacy, AML, vendor risk, workplace safety, and low-evidence scenarios.

Most recent verified commands:

```text
bash -ic 'uv run pytest -s'
bash -ic 'uv run ruff check vigil tests'
agents-cli eval run --evalset tests/eval/evalsets/basic.evalset.json --config tests/eval/eval_config.json
agents-cli eval run --evalset tests/eval/evalsets/retrieval_quality.evalset.json --config tests/eval/retrieval_quality_config.json
agents-cli eval run --evalset tests/eval/evalsets/general_enterprise.evalset.json --config tests/eval/general_enterprise_config.json
```

Latest known result: lint passes and the unit suite has passed with capture disabled. The reviewer Cloud Run deployment has also passed Slack endpoint smoke checks.

Known tooling note:

- `agents-cli` reported a CLI/skills version mismatch. The CLI is newer than the installed local Google agent skills. Run `agents-cli update` before serious deployment or scaffold work.

## 4. Current Reviewer Slice

This is the slice prepared for public reviewer testing:

```text
Slack command or user instruction
  -> FastAPI Slack endpoint
  -> ADK orchestrator
  -> source_monitoring_agent
      -> mock or Gemini web source backend
      -> structured obligations with citations
  -> enterprise_context_agent
      -> local indexed corpus retrieval or RAG Engine backend
      -> obligation-to-artifact mappings
  -> orchestrator final decision
      -> classification
      -> recommended actions
      -> Slack alert with approval/follow-up actions
      -> audit narrative
      -> approval required before ticket
```

The public demo is reliable with mock source + local corpus. Gemini web source mode and RAG Engine retrieval remain available for supervised production-like testing.

## 5. Phase: Tighten The Local Impact Loop

Status: implemented for the reviewer build

Goal:

Make the end-to-end local loop reliable, explainable, and demo-ready before adding real Slack or managed RAG.

Implemented:

- Explicit `classification` on `ImpactDecision`:
  - actionable
  - informational
  - irrelevant
  - ambiguous
- Actionability now requires source obligations, retrieved enterprise chunks, and obligation mappings.
- `approval_required`, `approval_status`, and `ticket_status` are included in the decision.
- Actionable decisions mark approval as pending and ticket creation as blocked.
- Mock ticket creation refuses to run unless approval is supplied.
- Human approval can be recorded after analysis and creates one mock ticket using an idempotency key.
- Audit events are attached to the returned decision and recorded through the audit backend.
- Local audit events can be persisted to `.vigil/audit.jsonl`.
- Audit events now cover:
  - analysis started
  - context loaded
  - source searched
  - enterprise context retrieved
  - alert prepared
  - approval requested
  - ticket blocked
  - approval received
  - ticket created
  - approval idempotent replay
  - analysis completed
- Tests cover actionable, informational, and ambiguous local loop behavior.
- The local demo command shows classification, approval state, ticket state, action results, and audit events.
- Retrieval-quality eval covers unrelated no-match source obligations and ambiguous consultation evidence.

Tasks:

- Add a second demo/eval case for an irrelevant or low-impact update.
- Add CLI ergonomics for approving a saved decision from a demo run, if we want a pure terminal approval demo.

Exit criteria:

- A local run produces a cited decision with source obligations, affected artifacts, recommended actions, mock Slack payload, approval requirement, and audit record.
- Irrelevant updates do not create high-priority alerts.
- Ambiguous sources are marked uncertain or ask for clarification.

## 6. Phase: Retrieval Quality And Corpus Hardening

Status: in progress

Goal:

Make enterprise mapping strong enough that the demo feels like real RAG-backed compliance work.

Implemented:

- Added metadata filters to `RetrievalBackend.search`.
- Added richer metadata to local corpus docs:
  - jurisdiction
  - product
  - system class
  - owner
  - review cadence
  - business unit
- Added score thresholds so weak retrieval does not produce false affected artifacts.
- Added no-match behavior when candidate chunks do not map to obligations.
- Add mapping rationale tests.
- Added no-match local retrieval and orchestrator tests.
- Added no-match and ambiguous-source ADK eval cases.

Remaining tasks:

- Improve chunking for sections, headings, tables, and short policy clauses.
- Add citation quality eval that penalizes hallucinated owners or documents.

Exit criteria:

- Enterprise retrieval returns precise snippets and mappings for known obligations.
- Weak or unrelated queries produce informational/irrelevant decisions instead of false positives.

## 7. Phase: Gemini Web Source Robustness

Status: in progress

Goal:

Make `VIGIL_SOURCE_BACKEND=gemini_web` reliable enough for live demo use.

Tasks:

- Add configurable monitored source sets.
- Add mocked Gemini response tests for:
  - valid structured output
  - fenced JSON
  - invalid JSON fallback
  - extraction model exceptions
  - duplicate findings across monitoring runs
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

Status: implemented for the reviewer build

Goal:

Turn impact analysis into an operational workflow.

Tasks:

- Add Slack app configuration docs.
- Implement real Slack posting behind `ActionBackend`. (Implemented behind `VIGIL_ACTION_BACKEND=slack`.)
- Add Slack signing-secret verification. (Implemented for slash commands and interactive callback requests.)
- Add approval callback endpoint. (Implemented for approve-ticket callbacks backed by the decision store.)
- Wire Slack approval callbacks into the idempotent approval path. (Implemented for approve-ticket callbacks.)
- Add false-positive handling and audit event. (Implemented.)
- Ensure Slack payloads contain only safe snippets and permission-safe links.
- Add tests for Slack callback approval wiring. (Implemented for command and interaction paths.)

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
- Smoke test the Google Memory Bank backend after Agent Runtime identifiers and IAM are available.
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

- Production persistence for the typed org context registry.
- Production validation of Google Memory Bank with Agent Runtime IAM.
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

Implement Gemini web source robustness before real Slack.

Why this is next:

- The operational approval loop now exists locally.
- Source extraction and local retrieval work for the flagship path.
- Retrieval now rejects weak and unrelated enterprise matches with unit and eval coverage.
- The biggest remaining demo risk is live source variability: stale dates, duplicate findings, and malformed grounded-search/extraction responses.

Suggested order:

1. Expand mocked Gemini response tests for extraction exceptions and stale-source paths.
2. Add duplicate-finding detection across monitoring runs.
3. Add citation-quality eval coverage for hallucinated owners/documents.
4. Then move to Slack callbacks and signature verification.

## 15. One-Week Completion Gaps

To call Vigil “complete” for the current scope, close these gaps in order:

1. Retrieval quality: citation quality eval and chunking improvements for tables, short clauses, and dense policy sections.
2. Source robustness: duplicate finding guardrails across monitoring runs and mocked Gemini edge-case tests.
3. Slack workflow: signing verification, callback endpoint, approval wiring, false-positive audit flow.
4. Runtime readiness: agents-cli upgrade/scaffold review, Agent Runtime config, IAM/secrets checklist, Memory Bank smoke test.
5. Demo package: README runbook, one-command demo, eval summary, architecture diagram, short demo script.

## 16. External Resources Needed For Live Testing

Before live Firestore, Slack, Memory Bank, or Agent Runtime testing, configure:

- Google Cloud project with Firestore in Native mode enabled.
- Service account or ADC identity with Firestore document read/write permissions.
- `VIGIL_STORAGE_BACKEND=firestore`.
- `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`.
- Optional `VIGIL_FIRESTORE_COLLECTION_PREFIX` for environment isolation, for example `vigil_dev`.
- Slack app with bot token, signing secret, `chat:write` scope, and interactive callback URL `/slack/interactions`.
- Secret Manager entries for Slack and Google credentials before deployment.
- Agent Runtime identifiers and IAM for Memory Bank smoke testing.

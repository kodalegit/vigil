# Vigil Production Readiness Notes

## Architecture Decision

Use hierarchical task decomposition with explicit `AgentTool` invocation for the MVP and near-production path.

This keeps the orchestrator responsible for product judgment while letting specialist agents do bounded context work:

1. `vigil_orchestrator` interprets the user request and owns final classification, alert wording, approval gating, and audit narrative.
2. `source_monitoring_agent` extracts regulatory changes and obligations from trusted sources.
3. `enterprise_context_agent` maps obligations to internal policies, controls, SOPs, snippets, and owners.

Prefer `AgentTool` over LLM-driven transfer for these two specialists because Vigil needs the parent to gather both results and synthesize one final decision. Transfer is better when the conversation should be handed off to another agent to complete the response. Here, the subagents should behave like callable research tools with results flowing back up to the orchestrator.

## ADK 2 Status

Vigil now targets ADK 2.x. The current code keeps the ADK 1.x-compatible parent
agent plus `AgentTool` specialist pattern because it is simple and tested, while
ADK 2 `Workflow` is available for future deterministic scheduled monitoring flows.
Do not share persistent ADK session storage between pre-upgrade ADK 1.x deployments
and ADK 2 deployments.

## Why Not a Fixed Workflow Yet

An ADK 2 `Workflow` can be useful for scheduled monitoring runs later, especially once source detection and enterprise retrieval are deterministic. For interactive compliance analysis, the LLM parent should keep discretion to ask follow-up questions, skip irrelevant work, rerun one specialist, or produce a report. We can add workflow agents later for cron-style batch monitoring without changing the user-facing orchestrator.

## Google Ecosystem Preparation

### Agent Runtime

Keep the project compatible with `agents-cli` and ADK:

- Preserve `[tool.agents-cli]` metadata in `pyproject.toml`.
- Keep `vigil/agent.py` exporting `root_agent` and `app`.
- Keep `vigil/fast_api_app.py` for local and containerized serving.
- Add deployment with `agents-cli scaffold enhance . --deployment-target agent_runtime` when ready.
- Use Agent Runtime managed deployment, revisions, traffic, Cloud Logging, Cloud Trace, Monitoring, IAM, and agent identity rather than building custom deployment plumbing early.

### Sessions

Local development currently uses in-memory sessions. For Agent Runtime, use Agent Platform Sessions rather than application-managed session storage. Session state should hold per-conversation investigation state, current regulatory topic, selected sources, and temporary evidence packets. Avoid storing long-term organization facts only in session state.

### Memory Bank

Use Memory Bank for durable user and organization preferences, with the typed
organization context registry as the source of truth:

- organization jurisdictions
- regulated products and AI use cases
- preferred Slack channel and reviewer
- risk tolerance
- known false positives
- recurring monitoring preferences

Vigil now has a local `MemoryBackend` seam and a local `OrgContextRegistry` seam.
The local registry stores approved org context, source allowlists, Slack preferences,
monitoring profiles, and obligation inventory records. Memory writes are approval-gated
and advisory; they should be generated from approved registry facts or approved reviewer
preferences. Do not store evidence-only facts as durable memory unless they are reusable
preferences or organization profile facts. Source citations and impact decisions belong
in the audit trail.

### RAG And Enterprise Context

Keep `RetrievalBackend` as the seam between local corpus search and managed retrieval.

Use RAG Engine as the primary Google-managed retrieval implementation for indexed Google
Drive or Cloud Storage documents. Google Drive MCP should be treated as an auxiliary tool
for file search, metadata lookup, previews, and ingestion refresh workflows. MCP alone does
not provide the stable semantic chunk ranking and citation contract needed for Vigil's
obligation-to-policy mapping loop.

Near-term path:

1. Add a small local `data/corpus/` of synthetic AI governance docs.
2. Add metadata fields: owner, business unit, artifact type, jurisdiction, system class, last reviewed date.
3. Add a managed retrieval backend for Vertex AI RAG Engine.
4. Preserve citations and snippets in the `EnterpriseFinding` contract.

For the hackathon, the local indexed corpus should be the default demo path. RAG Engine is
the production path once the Google Cloud project, corpus, and Drive sharing are configured.

### Slack

There are two separate Slack tracks:

- Operational Slack actions: Vigil posts alerts, requests approval, receives button callbacks, and creates mock or real remediation tickets. This requires a Slack app, bot token, signing secret, webhook endpoint, and idempotent approval handling.
- Gemini Enterprise Slack federation: Gemini Enterprise can connect Slack as a federated search data source. That is useful for searching Slack history as enterprise context, but it does not replace Vigil's operational Slack alert workflow.

For production, implement operational Slack behind `ActionBackend` first. Treat federated Slack search as an enterprise retrieval source later.

Slack request verification now follows Slack's signed-secret flow for interactive
callbacks: raw body, `X-Slack-Request-Timestamp`, `X-Slack-Signature`, HMAC-SHA256,
and a five-minute replay window. The current `/slack/interactions` endpoint verifies
callbacks and wires approve-ticket actions into `record_approval` through the local
decision store. `SlackActionBackend` can post Block Kit alerts through Slack Web API
when `VIGIL_ACTION_BACKEND=slack`; this still needs a real workspace smoke test.

Vigil now has local JSONL and Firestore storage implementations for impact decisions
and approval updates. Firestore is also suitable for the typed org context registry
because profiles, source policies, Slack preferences, monitoring profiles, proposals,
and approved obligation inventory records are document-shaped, tenant-scoped, and
mostly read by ID. Use `VIGIL_STORAGE_BACKEND=firestore` for live storage tests. Keep
audit/event analytics separate if we later need append-heavy reporting in BigQuery.

### Security And Governance

- Require human approval before remediation actions.
- Keep least-privilege service accounts for source, retrieval, Slack, ticketing, and audit tools.
- Use Secret Manager for Slack and third-party credentials.
- Add audit records for every external action and approval decision.
- Add Model Armor or policy checks before posting externally visible messages.
- Add Cloud Trace spans around subagent calls and external tool calls.

## Next Implementation Milestones

1. Add Gemini web source robustness around duplicate findings across monitoring runs and mocked grounded-search/extraction failures.
2. Add citation-quality ADK eval coverage that penalizes hallucinated owners or documents.
3. Add Firestore live smoke test, real Slack workspace smoke test, and false-positive callback handling.
4. Add Agent Runtime scaffold and verify deploy in a dev project.
5. Smoke test Agent Platform Sessions and Google Memory Bank once Agent Runtime identifiers and IAM are available.

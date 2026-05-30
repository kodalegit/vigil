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

- Preserve `agents-cli-manifest.yaml` or equivalent `[tool.agents-cli]` project metadata.
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

Slack onboarding can now capture retrieval resources as approved org context:

- an existing Vertex AI RAG Engine corpus resource name
- a Google Drive folder ID to import into a managed corpus
- a Cloud Storage `gs://...` prefix to import into a managed corpus

For production, the reviewer should first approve the retrieval resource during Slack
onboarding, then an ingestion/refresh workflow should call the existing import helper
or RAG Engine API, verify citation quality, and finally enable `VIGIL_RETRIEVAL_BACKEND=rag_engine`
with the approved corpus. The org context registry stores the approved resource metadata;
runtime settings still choose the active backend for now.

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
callbacks and wires approve-ticket actions into `record_approval` through the decision
store. False-positive callbacks record an approved false-positive obligation in the
organization context registry so future runs can suppress the same obligation. `SlackActionBackend`
can post Block Kit alerts through Slack Web API when `VIGIL_ACTION_BACKEND=slack`; this
still needs a real workspace smoke test.

Slack onboarding now uses slash commands plus modal submissions. The app derives
`org_id` from Slack Enterprise ID first, then team ID, and writes approved profile,
source, review-channel, reviewer, and monitoring preferences through the typed org
context registry. Modal submissions acknowledge immediately and move Firestore/context
writes into background tasks that update the modal with `views.update`; this keeps
Slack interactive callbacks inside Slack's response window even when live storage is
slow. Approval, false-positive, and follow-up callbacks verify the stored decision org
and reviewer allowlist before mutating state. "Ask follow-up" captures a reviewer note
in a modal and records it as a `follow_up_requested` audit event.

Vigil now has local JSONL and Firestore storage implementations for impact decisions
approval updates, and audit events. Firestore is also suitable for the typed org
context registry because profiles, source policies, Slack preferences, monitoring
profiles, retrieval resources, proposals, and approved obligation inventory records
are document-shaped, tenant-scoped, and mostly read by ID. Use
`VIGIL_STORAGE_BACKEND=firestore` for live storage tests. Keep append-heavy audit
analytics in mind for BigQuery later if reporting volume outgrows Firestore reads.

### Secrets

Local development can keep direct environment variables. Deployed environments should
prefer Secret Manager references:

- `SLACK_BOT_TOKEN_SECRET`
- `SLACK_SIGNING_SECRET_SECRET`
- `GOOGLE_API_KEY_SECRET`

Each value can be either a full Secret Manager resource such as
`projects/<project>/secrets/<name>/versions/latest`, a secret resource without a
version, or a bare secret ID when `GOOGLE_CLOUD_PROJECT` is set. Direct env vars still
win, so local overrides remain easy.

### Security And Governance

- Require human approval before remediation actions.
- Keep least-privilege service accounts for source, retrieval, Slack, ticketing, and audit tools.
- Use Secret Manager for Slack and third-party credentials.
- Add audit records for every external action and approval decision. Firestore audit
  storage is now available through `VIGIL_STORAGE_BACKEND=firestore`.
- Add Model Armor or policy checks before posting externally visible messages.
- Add Cloud Trace spans around subagent calls and external tool calls.

## Next Implementation Milestones

1. Add Gemini web source robustness around duplicate findings across monitoring runs and mocked grounded-search/extraction failures.
2. Add citation-quality ADK eval coverage that penalizes hallucinated owners or documents.
3. Add Firestore live smoke test and real Slack workspace smoke test.
4. Add Agent Runtime scaffold and verify deploy in a dev project.
5. Smoke test Agent Platform Sessions and Google Memory Bank once Agent Runtime identifiers and IAM are available.

## Production Functionality Test Roadmap

Connect production-like resources in this order, keeping each step reversible and small.
Do not connect the next resource until the current one has a passing smoke test, a rollback
path, and an audit/log signal.

### 1. Google Cloud Project And Identity

Set up a dedicated dev Google Cloud project before touching production data.

Connect:

- one dev project and billing account
- Application Default Credentials for local smoke tests
- a least-privilege service account for deployed Vigil
- Secret Manager entries for Slack and future third-party credentials

Verify:

- `agents-cli info` shows the intended project, region, and deployment target once enhanced
- local model auth works with `GOOGLE_GENAI_USE_VERTEXAI=true`
- Cloud Logging receives structured app logs without prompt/response content by default

Improve before deployment:

- document IAM roles per backend
- keep `GOOGLE_CLOUD_LOCATION` aligned with model availability
- decide retention windows for audit, decision, and trace data

### 2. Firestore Decision And Context Storage

Firestore should be the first live backend because Slack callbacks depend on stable
`analysis_id` lookups after the original request is gone.

Connect:

- Firestore Native mode in the dev project
- `VIGIL_STORAGE_BACKEND=firestore`
- a non-production collection prefix such as `vigil_dev`

Verify:

- analysis decisions persist and can be retrieved by `analysis_id`
- approval callbacks update the same decision once
- false-positive callbacks add approved obligation inventory records
- tenant/org IDs cannot read or overwrite another org's records in application code

Improve before deployment:

- add a live Firestore smoke test gated by an environment flag
- add optimistic update or transaction handling if concurrent callbacks become likely
- define export/backup and retention policy

### 3. Operational Slack App

Test operational Slack before Slack federation. The alert workflow is the product surface;
federated Slack search is only later enterprise context.

Connect:

- a dev Slack workspace
- Slack bot token in Secret Manager or local env
- Slack signing secret
- public HTTPS callback endpoint for `/slack/interactions`

Verify:

- `VIGIL_ACTION_BACKEND=slack` posts a Block Kit alert to a private test channel
- `/onboard`, `/setup`, or `/vigil onboard` opens the onboarding modal and commits approved org context
- approve button creates exactly one ticket result when clicked repeatedly
- false-positive button records inventory and suppresses the same obligation in a later run
- ask-follow-up opens a modal, records the reviewer note, and leaves the decision pending
- Slack messages include only permission-safe snippets and stable IDs, not full documents

Improve before deployment:

- implement the real ticketing backend behind `ActionBackend.create_ticket`
- add channel allowlists beyond the current reviewer authorization checks
- persist Slack installation/token metadata for multi-workspace production installs

### 4. Managed Retrieval Over Drive Or Cloud Storage

Only connect real internal documents after Slack and storage are safe, because retrieval
quality determines whether alerts are useful or noisy.

Connect:

- a small curated Drive folder or GCS bucket with non-sensitive pilot docs
- Vertex AI RAG Engine corpus
- `VIGIL_RETRIEVAL_BACKEND=rag_engine`
- `VIGIL_RAG_CORPUS=<corpus resource name>`

Verify:

- RAG results preserve titles, snippets, citations, and source URIs
- obligation-to-document mappings match the local corpus baseline
- unrelated obligations produce no affected artifacts
- reviewers can inspect cited source documents through the expected permission path

Improve before deployment:

- add RAG response normalization tests with recorded fake responses
- add citation-quality evals that penalize hallucinated owners, documents, and sections
- document Drive sharing requirements for the Vertex RAG Data Service Agent

### 5. Live Source Monitoring

Use live web/source monitoring only after enterprise retrieval has a conservative no-match
behavior. Live source noise is otherwise hard to distinguish from retrieval noise.

Connect:

- allowlisted official regulatory sources
- `VIGIL_SOURCE_BACKEND=gemini_web`
- source freshness windows per trusted source

Verify:

- obligations are returned only when backed by citations
- stale or duplicate findings are downgraded
- ambiguous consultations ask for clarification instead of alerting broadly

Improve before deployment:

- add monitored source-set configuration
- add evals for stale, duplicate, and no-obligation live-source scenarios
- consider a deterministic scheduled workflow for batch monitoring

### 6. Agent Runtime, Sessions, Memory, And Observability

Deploy only after the local loop, Firestore, Slack, RAG, and source monitoring pass dev
smoke tests.

Connect:

- `agents-cli scaffold enhance . --deployment-target agent_runtime`
- Agent Platform Sessions
- Memory Bank for approved durable preferences
- Cloud Trace and Monitoring dashboards

Verify:

- deployed revisions can run the same analysis loop as local
- sessions hold temporary investigation state only
- Memory Bank writes require approval and mirror registry facts/preferences
- traces identify source, retrieval, Slack, ticketing, and audit latency

Improve before deployment:

- add Model Armor or policy checks before externally visible messages
- define SLOs for monitoring runs and Slack callback latency
- run ADK evals as a required pre-deploy gate

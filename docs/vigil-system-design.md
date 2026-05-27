# Vigil System Design

## 1. Design Direction

Vigil should use a deliberately simple agent architecture: one primary orchestrator agent coordinates a small set of specialized subagents, gathers compressed context from them, and decides what action to take next.

The goal is to avoid an over-fragmented agent graph. Subagents should not independently drive the workflow. They should behave like bounded research and context-gathering workers that return structured, cited summaries to the orchestrator.

Vigil's product focus is the regulatory impact loop, not generic legal summarization. The system should detect a trusted regulatory change, extract the obligations that matter, map those obligations to internal policies and controls, propose remediation in Slack, and preserve an evidence-backed audit trail for human review.

## 2. Regulatory Impact Loop

Vigil should make the business workflow explicit:

1. Watch trusted regulatory sources.
2. Understand what changed and which obligations follow.
3. Find matching internal policies, controls, SOPs, and owners.
4. Classify the event as actionable, informational, or irrelevant.
5. Alert the compliance lead in Slack with concise evidence and recommended actions.
6. After human approval, create a mock remediation ticket and record the audit trail.

The flagship use case is a lean in-house legal or compliance team at a mid-size fintech or SaaS company handling regulated data. The user is overwhelmed by regulatory noise and needs to know which internal artifacts are affected, who owns them, and what action should happen next.

## 3. Core Architecture

```text
User / Schedule / Slack Event
  -> Vigil Orchestrator Agent
      -> Source Monitoring Subagent
      -> Enterprise Context Subagent
      -> Optional Evidence Compression Subagent
  -> Orchestrator Decision
      -> Ask follow-up question
      -> Send alert
      -> Generate report
      -> Request approval
      -> Create remediation action
      -> Store memory / audit event
```

## 4. Agent Responsibilities

### 4.1 Vigil Orchestrator Agent

The orchestrator is the only agent responsible for end-to-end decisions.

Responsibilities:

- Interpret user instructions and monitoring preferences.
- Load relevant user, organization, session, and memory context.
- Decide which subagents to call and what instructions to give them.
- Ask subagents for concise, grounded, task-specific context.
- Merge source-monitoring and enterprise-context findings.
- Decide whether the event is actionable, informational, irrelevant, ambiguous, or requires more context.
- Classify events based on organization profile, jurisdictions, affected assets, deadlines, risk tolerance, and prior false positives.
- Drop, batch, or downgrade low-relevance events to reduce alert fatigue.
- Prioritize events that affect multiple critical policies, controls, or owners.
- Draft final analysis, alerts, reports, and remediation recommendations.
- Call external action tools such as Slack, report generation, audit logging, and mock ticket creation.
- Enforce human approval before externally visible remediation actions.
- Persist useful memory and audit events.

The orchestrator should retain the product's core judgment. Subagents should reduce context load, not own product logic.

### 4.2 Source Monitoring and Obligation Extraction Subagent

The source monitoring subagent searches or monitors legal, compliance, and policy sources according to instructions from the orchestrator.

Responsibilities:

- Search official or trusted sources using Gemini with grounding search where available.
- Use user-specified sources, jurisdictions, domains, and keywords.
- Identify new, changed, or newly relevant legal/compliance material.
- Extract only the information requested by the orchestrator.
- Return a compressed, cited synthesis.
- Preserve source URLs, normalized publication dates, retrieved timestamps, quoted snippets, and confidence.
- Apply configured source freshness windows before treating dated source evidence as current.
- Extract obligations as first-class structured objects.

Output should answer:

- What changed?
- Why might it matter?
- What are the key obligations, deadlines, or risks?
- What source evidence supports this?
- What uncertainty remains?

Minimum obligation output contract:

```json
{
  "summary_of_change": "string",
  "obligations": [
    {
      "id": "string",
      "text": "string",
      "section_id": "string",
      "effective_date": "string|null",
      "jurisdiction": "string",
      "topics": ["string"],
      "risk_level": "low|medium|high",
      "source_url": "string",
      "source_quote": "string",
      "confidence": "low|medium|high"
    }
  ]
}
```

### 4.3 Enterprise Policy and Control Mapping Subagent

The enterprise context subagent searches the organization's internal context based on targeted instructions from the orchestrator.

Responsibilities:

- Search Google Drive and local development document stores.
- Use RAG over indexed enterprise content as the primary retrieval path.
- Support future multimodal context from audio, PDFs, images, slides, and screenshots.
- Retrieve only context relevant to the current regulatory concern.
- Return compressed findings with citations back to internal artifacts.
- Map each obligation to candidate internal policies, controls, SOPs, meeting notes, and owners.
- Include relevance scores and specific snippets rather than broad document-level matches.

Output should answer:

- Which internal documents, policies, contracts, or meeting artifacts are relevant?
- What exact snippets appear affected?
- How does each snippet relate to the regulatory source context?
- What business unit or owner may be implicated?
- What internal citations support this?

Minimum mapping output contract:

```json
{
  "relevant_docs": [
    {
      "doc_id": "string",
      "doc_title": "string",
      "owner": "string|null",
      "business_unit": "string|null",
      "artifact_type": "policy|control|sop|contract|meeting_note|other"
    }
  ],
  "mappings": [
    {
      "obligation_id": "string",
      "doc_id": "string",
      "snippet": "string",
      "section_ref": "string|null",
      "relevance_score": 0.0,
      "reason": "string"
    }
  ]
}
```

## 5. Context and Memory Model

The orchestrator should combine four context layers:

1. User instruction context
   - Current user request.
   - Monitoring criteria.
   - Explicitly selected sources.
   - Desired alert behavior.

2. Session context
   - Recent conversation state.
   - Current investigation state.
   - Previous follow-up answers.

3. Organization memory
   - Jurisdictions of interest.
   - Business profile.
   - Compliance domains.
   - Preferred Slack channels.
   - Reviewer and owner preferences.
   - Prior false positives.
   - Risk tolerance.

4. Retrieved evidence
   - Regulatory source evidence from the source monitoring subagent.
   - Enterprise evidence from the enterprise context subagent.

Memory should guide retrieval and decisions, but evidence should ground final claims.

## 6. ADK Design Pattern

Use an ADK 2-compatible parent-agent/subagent hierarchy.

Recommended pattern:

- `VigilOrchestrator` is an `LlmAgent` parent.
- `SourceMonitoringAgent` and `EnterpriseContextAgent` are available as subagents or wrapped as `AgentTool`s.
- The orchestrator delegates bounded context-gathering tasks to subagents.
- Subagents return structured summaries through state or tool results.

Use direct orchestrator control rather than a large fixed workflow graph. ADK 2
`Workflow` graphs can be added later for scheduled monitoring runs, but the
interactive design should keep orchestration agent-driven.

## 7. Tool Design

The orchestrator should have access to action and memory tools.

Initial orchestrator tools:

```text
memory.get_profile
memory.update_profile
session.get_recent_context
slack.post_message
slack.request_approval
reports.generate_report
audit.record_event
ticketing.create_mock_ticket
approval.record_decision
decision_store.save_decision
decision_store.get_decision
```

Source monitoring subagent tools:

```text
source_search.grounded_search
source_search.fetch_url
source_search.fetch_configured_sources
source_search.detect_change
```

Enterprise context subagent tools:

```text
enterprise_search.search_local_corpus
enterprise_search.search_drive
enterprise_search.get_artifact
enterprise_search.get_citation
```

Development should start with local/mock implementations behind interfaces, then replace or augment them with Google Cloud implementations.

### 7.1 Slack Payload Shape

Slack is the front door for the user experience. Alerts should be structured, short, and approval-oriented.

Minimum `slack.post_message` payload:

```json
{
  "channel": "string",
  "title": "New AML rule impacts Policy P-001",
  "classification": "actionable|informational|irrelevant",
  "priority": "low|medium|high",
  "what_changed": ["string"],
  "why_it_matters": ["string"],
  "affected_artifacts": [
    {
      "doc_id": "string",
      "title": "string",
      "owner": "string|null",
      "snippet": "string"
    }
  ],
  "suggested_actions": ["string"],
  "buttons": [
    "Approve & create ticket",
    "Ask follow-up",
    "Mark as false positive"
  ],
  "actions": [
    {
      "action_id": "approve_ticket",
      "value": {
        "analysis_id": "string",
        "org_id": "string",
        "idempotency_key": "string"
      }
    }
  ]
}
```

The Slack message should avoid leaking private document contents into unauthorized channels. The orchestrator should respect enterprise permissions and include links or short excerpts only when allowed. Approval buttons should carry a stable `analysis_id` and recover full decision state from the decision store before applying approval.

### 7.2 Audit Event Schema

Every material decision or external action should produce an audit event.

Minimum `audit.record_event` schema:

```json
{
  "event_id": "string",
  "event_type": "REG_CHANGE_DETECTED|ALERT_SENT|APPROVED|TICKET_CREATED|FALSE_POSITIVE_RECORDED",
  "external_sources": [
    {
      "url": "string",
      "citation": "string",
      "retrieved_at": "string"
    }
  ],
  "obligation_ids": ["string"],
  "internal_docs": [
    {
      "doc_id": "string",
      "snippet_hash": "string"
    }
  ],
  "classification": "actionable|informational|irrelevant",
  "user": "string|null",
  "timestamp": "string",
  "notes": "string|null"
}
```

This audit trail should make it possible to reconstruct what changed, why Vigil believed it mattered, which internal artifacts were implicated, who approved action, and what ticket was created. Decision persistence should separately store the latest `ImpactDecision` by `analysis_id` so async approvals can update the correct decision without relying on Slack message state. Firestore can serve both decision persistence and the org context registry because both use tenant-scoped document records with direct key lookups; append-heavy audit analytics can move to a separate store later.

The local implementation records audit events in memory and can append them to JSONL
for repeatable demos. Production should replace this with durable audit storage.

## 8. Retrieval and RAG Strategy

Vigil's core enterprise experience requires semantic retrieval over indexed organizational
documents. Google Drive MCP can help with ad hoc file lookup, metadata inspection, previews,
and refresh workflows, but it should not be the primary retrieval engine for obligation-to-
policy mapping. The production path is:

```text
Google Drive / local corpus
  -> ingestion and chunking
  -> local indexed corpus for development
  -> Vertex AI RAG Engine for managed retrieval
  -> Enterprise Context Subagent
```

### 8.1 Local Development

Local development should not require cloud infrastructure for every run.

Use a retrieval interface with two backends:

1. Local backend
   - Local document folder under the project package.
   - Metadata-aware chunking.
   - Lightweight semantic/lexical ranking for deterministic tests.
   - Mock Google Drive files for tests.

2. Google backend
   - Google Drive ingestion.
   - Vertex AI RAG Engine as the primary managed retrieval backend.
   - Gemini embeddings and RAG Engine retrieval configuration where available.
   - Drive MCP only as an auxiliary file access and refresh tool.

### 8.2 MVP Production Slice

The next credible hackathon slice is:

1. Gemini web search grounding for regulatory source monitoring.
2. Local indexed corpus for repeatable enterprise retrieval demos.
3. RAG Engine ingestion helper for Google Drive folders/files.
4. Mock Slack alert with approval buttons.
5. Audit events for analysis start/completion and mock external actions.
6. ADK evals for the EU AI Act happy path, irrelevant updates, ambiguous sources, and citation quality.

The agent code should call the retrieval interface, not a specific backend directly.

### 8.2 Production Retrieval

Production should prefer Google-managed retrieval primitives:

- Google Drive as a source of enterprise artifacts.
- Vertex AI RAG Engine for managed retrieval over Drive and Cloud Storage sources.
- Vertex AI Vector Search for scalable vector search where needed.
- Gemini Embedding 2 for multimodal retrieval over text, audio, PDFs, images, and slides.

## 9. Local Development Configuration

Use `uv` for environment and dependency management.

Use a `.env` file for local configuration. Do not commit real secrets.

Recommended local modes:

### Mode A: Google AI Studio quickstart

Useful for fast local model calls.

```text
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=...
```

### Mode B: Google Cloud Agent Platform local development

Useful when testing Agent Platform-compatible Gemini calls locally with user credentials.

```text
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=...
GOOGLE_CLOUD_LOCATION=us-central1
```

Authenticate locally with application default credentials:

```text
gcloud auth application-default login
```

### Mode C: Production service account

In production on Google Cloud, use the runtime service account instead of key files where possible.

For non-Google-hosted automation only, use:

```text
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

Production secrets should live in Secret Manager, not in `.env`.

## 10. Environment Variables

Recommended project variables:

```text
APP_ENV=local
VIGIL_MODEL=gemini-2.5-flash
VIGIL_REASONING_MODEL=gemini-2.5-pro
VIGIL_USE_VERTEX_AI=true
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_API_KEY=
GOOGLE_APPLICATION_CREDENTIALS=
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
VIGIL_STORAGE_BACKEND=local
VIGIL_RETRIEVAL_BACKEND=local
VIGIL_RETRIEVAL_MIN_SCORE=0.08
VIGIL_MEMORY_BACKEND=local
VIGIL_SOURCE_BACKEND=mock
```

Use `.env.example` to document required variables without exposing secrets.

## 11. Deployment Path

### 11.1 Local

Run locally using `uv`, local env variables, mock tools, and local retrieval.

### 11.2 Cloud Run Transitional Deployment

If Agent Runtime setup slows development, deploy the HTTP service to Cloud Run while preserving Agent Runtime-compatible agent code.

### 11.3 Agent Runtime Production Deployment

The intended production target is Gemini Enterprise Agent Platform Agent Runtime.

Production-readiness goals:

- ADK-compatible agent entrypoint.
- Clear dependency file.
- Service account permissions.
- Cloud Logging and Cloud Trace support.
- Secrets in Secret Manager.
- Managed retrieval through Vertex AI RAG Engine or Vector Search.
- Agent Card / Marketplace-readiness metadata.

## 12. Safety and Governance

The orchestrator must enforce these rules:

- Do not present outputs as final legal advice.
- Do not create external remediation actions without approval.
- Preserve source and enterprise citations for impact claims.
- Mark uncertainty and low-confidence findings.
- Ask follow-up questions when monitoring criteria are ambiguous.
- Respect enterprise document permissions.
- Record audit events for decisions and external actions.

## 13. Simplified MVP Architecture

For the MVP, demonstrate a full regulatory impact loop for one regulatory domain and a small internal policy corpus:

1. A new sample rule or guidance document is ingested from a configured source.
2. Vigil extracts obligations and citations.
3. Vigil searches 10-20 mocked internal policies, SOPs, controls, and meeting notes.
4. Vigil maps obligations to affected internal artifacts and owners.
5. Vigil classifies the event as actionable, informational, or irrelevant.
6. Vigil posts a Slack alert with mapped policies and suggested remediation.
7. On human approval, Vigil creates a mock ticket and records an audit event.

Build only this architecture:

```text
Vigil Orchestrator
  - calls Source Monitoring Subagent
  - calls Enterprise Context Subagent
  - classifies relevance and impact
  - posts Slack alert with suggested actions
  - requests approval before mock ticket creation
  - records audit events
```

Do not add more agents unless there is a clear context-management problem.

Recommended hackathon constraints:

- Use one coherent domain and regulator for the demo.
- Configure 5-10 monitored source URLs or static sample documents.
- Start with a simple diff or new-file trigger instead of broad horizon scanning.
- Use local keyword search or lightweight embeddings before cloud retrieval.
- Use mock ticket storage instead of Jira or ServiceNow.
- Over-invest in reliable scenario tests and clear Slack output.

# Vigil System Design

## 1. Design Direction

Vigil should use a deliberately simple agent architecture: one primary orchestrator agent coordinates a small set of specialized subagents, gathers compressed context from them, and decides what action to take next.

The goal is to avoid an over-fragmented agent graph. Subagents should not independently drive the workflow. They should behave like bounded research and context-gathering workers that return structured, cited summaries to the orchestrator.

## 2. Core Architecture

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

## 3. Agent Responsibilities

### 3.1 Vigil Orchestrator Agent

The orchestrator is the only agent responsible for end-to-end decisions.

Responsibilities:

- Interpret user instructions and monitoring preferences.
- Load relevant user, organization, session, and memory context.
- Decide which subagents to call and what instructions to give them.
- Ask subagents for concise, grounded, task-specific context.
- Merge source-monitoring and enterprise-context findings.
- Decide whether the event is actionable, irrelevant, ambiguous, or requires more context.
- Draft final analysis, alerts, reports, and remediation recommendations.
- Call external action tools such as Slack, report generation, audit logging, and mock ticket creation.
- Enforce human approval before externally visible remediation actions.
- Persist useful memory and audit events.

The orchestrator should retain the product's core judgment. Subagents should reduce context load, not own product logic.

### 3.2 Source Monitoring Subagent

The source monitoring subagent searches or monitors legal, compliance, and policy sources according to instructions from the orchestrator.

Responsibilities:

- Search official or trusted sources using Gemini with grounding search where available.
- Use user-specified sources, jurisdictions, domains, and keywords.
- Identify new, changed, or newly relevant legal/compliance material.
- Extract only the information requested by the orchestrator.
- Return a compressed, cited synthesis.
- Preserve source URLs, publication dates, quoted snippets, and confidence.

Output should answer:

- What changed?
- Why might it matter?
- What are the key obligations, deadlines, or risks?
- What source evidence supports this?
- What uncertainty remains?

### 3.3 Enterprise Context Subagent

The enterprise context subagent searches the organization's internal context based on targeted instructions from the orchestrator.

Responsibilities:

- Search Google Drive and local development document stores.
- Use RAG over indexed enterprise content.
- Support future multimodal context from audio, PDFs, images, slides, and screenshots.
- Retrieve only context relevant to the current regulatory concern.
- Return compressed findings with citations back to internal artifacts.

Output should answer:

- Which internal documents, policies, contracts, or meeting artifacts are relevant?
- What exact snippets appear affected?
- How does each snippet relate to the regulatory source context?
- What business unit or owner may be implicated?
- What internal citations support this?

## 4. Context and Memory Model

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

## 5. ADK Design Pattern

Use an ADK parent-agent/subagent hierarchy.

Recommended pattern:

- `VigilOrchestrator` is an `LlmAgent` parent.
- `SourceMonitoringAgent` and `EnterpriseContextAgent` are available as subagents or wrapped as `AgentTool`s.
- The orchestrator delegates bounded context-gathering tasks to subagents.
- Subagents return structured summaries through state or tool results.

Use direct orchestrator control rather than a large fixed workflow graph. Fixed sequential or parallel workflow agents can be added later for scheduled monitoring runs, but the initial design should keep orchestration agent-driven.

## 6. Tool Design

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

## 7. Retrieval and RAG Strategy

### 7.1 Local Development

Local development should not require cloud infrastructure for every run.

Use a retrieval interface with two backends:

1. Local backend
   - Local document folder.
   - Local metadata store.
   - Lightweight vector store or simple keyword search at first.
   - Mock Google Drive files for tests.

2. Google backend
   - Google Drive ingestion.
   - Vertex AI RAG Engine or Vertex AI Vector Search.
   - Gemini embeddings, including Gemini Embedding 2 where available.

The agent code should call the retrieval interface, not a specific backend directly.

### 7.2 Production Retrieval

Production should prefer Google-managed retrieval primitives:

- Google Drive as a source of enterprise artifacts.
- Vertex AI RAG Engine for managed retrieval over Drive and Cloud Storage sources.
- Vertex AI Vector Search for scalable vector search where needed.
- Gemini Embedding 2 for multimodal retrieval over text, audio, PDFs, images, and slides.

## 8. Local Development Configuration

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

## 9. Environment Variables

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
VIGIL_MEMORY_BACKEND=local
VIGIL_SOURCE_BACKEND=mock
```

Use `.env.example` to document required variables without exposing secrets.

## 10. Deployment Path

### 10.1 Local

Run locally using `uv`, local env variables, mock tools, and local retrieval.

### 10.2 Cloud Run Transitional Deployment

If Agent Runtime setup slows development, deploy the HTTP service to Cloud Run while preserving Agent Runtime-compatible agent code.

### 10.3 Agent Runtime Production Deployment

The intended production target is Gemini Enterprise Agent Platform Agent Runtime.

Production-readiness goals:

- ADK-compatible agent entrypoint.
- Clear dependency file.
- Service account permissions.
- Cloud Logging and Cloud Trace support.
- Secrets in Secret Manager.
- Managed retrieval through Vertex AI RAG Engine or Vector Search.
- Agent Card / Marketplace-readiness metadata.

## 11. Safety and Governance

The orchestrator must enforce these rules:

- Do not present outputs as final legal advice.
- Do not create external remediation actions without approval.
- Preserve source and enterprise citations for impact claims.
- Mark uncertainty and low-confidence findings.
- Ask follow-up questions when monitoring criteria are ambiguous.
- Respect enterprise document permissions.
- Record audit events for decisions and external actions.

## 12. Simplified MVP Architecture

For the MVP, build only this:

```text
Vigil Orchestrator
  - calls Source Monitoring Subagent
  - calls Enterprise Context Subagent
  - decides relevance and impact
  - posts Slack alert or generates report
  - requests approval before mock ticket creation
```

Do not add more agents unless there is a clear context-management problem.

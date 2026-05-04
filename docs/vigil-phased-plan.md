# Vigil Phased Implementation Plan

## 1. Planning Assumptions

Vigil will be built as a new Python project using `uv` and Google Agent Development Kit. The design favors local development first, with clean interfaces for replacing mock/local services with Google Cloud managed services during production hardening.

The architecture is intentionally simplified:

- One orchestrator agent owns decision-making.
- Two primary subagents gather and compress context.
- External actions are performed through tools.
- Cloud-specific services are introduced behind interfaces rather than hardcoded into business logic.

## 2. MVP Definition

The MVP is successful when Vigil can:

1. Accept a user monitoring instruction.
2. Use a source monitoring subagent to find or simulate relevant legal/compliance updates.
3. Use an enterprise context subagent to search local or Google Drive context.
4. Return cited, compressed evidence to the orchestrator.
5. Have the orchestrator decide whether the update is relevant and actionable.
6. Generate an impact summary and recommended action.
7. Send or simulate a Slack alert.
8. Generate a cited report.
9. Require approval before mock remediation ticket creation.
10. Run locally without requiring full cloud infrastructure.

## 3. Development Modes

### 3.1 Local Mock Mode

Purpose:

- Fast iteration.
- No cloud dependencies.
- Deterministic tests.

Backends:

- Mock regulatory source search.
- Local enterprise document folder.
- Local memory store.
- Mock Slack/ticketing.
- Optional Gemini API calls through AI Studio or Vertex AI ADC.

### 3.2 Local Google-Connected Mode

Purpose:

- Validate real Gemini model behavior.
- Validate Google Drive integration.
- Validate grounded search where available.

Backends:

- Gemini through Agent Platform local auth.
- Google Drive connector.
- Local or managed retrieval backend.
- Real Slack development workspace if available.

### 3.3 Production-Ready Mode

Purpose:

- Prepare for Gemini Enterprise Agent Platform deployment.

Backends:

- Agent Runtime.
- Service account authentication.
- Vertex AI RAG Engine or Vector Search.
- Secret Manager.
- Cloud Logging and Cloud Trace.
- Real Slack and enterprise integrations.

## 4. Environment Setup Plan

### 4.1 Python and Package Management

Use `uv` for environment management.

Initial dependency categories:

- ADK and Google GenAI libraries.
- Google Cloud SDK clients as needed.
- Pydantic or equivalent for schemas.
- FastAPI or similar only if an HTTP API is needed for Slack/webhooks.
- Testing dependencies.
- Local document parsing dependencies.

### 4.2 Environment Variables

Create `.env.example` with non-secret placeholders.

Recommended variables:

```text
APP_ENV=local
VIGIL_MODEL=gemini-2.5-flash
VIGIL_REASONING_MODEL=gemini-2.5-pro
VIGIL_RETRIEVAL_BACKEND=local
VIGIL_MEMORY_BACKEND=local
VIGIL_SOURCE_BACKEND=mock
VIGIL_ACTION_BACKEND=mock
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
```

Local developer secrets should be stored in `.env`. Production secrets should be stored in Secret Manager.

### 4.3 Authentication Strategy

Local quickstart option:

```text
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=...
```

Local Agent Platform option:

```text
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=...
GOOGLE_CLOUD_LOCATION=us-central1
```

Then authenticate with:

```text
gcloud auth application-default login
```

Production option:

- Use attached Google Cloud service account where possible.
- Avoid key files in production.
- Grant least-privilege roles.
- Store third-party secrets in Secret Manager.

## 5. Phase 1: Project Foundation and Local Skeleton

Goal:

Build the smallest runnable local version of Vigil with the simplified orchestrator architecture.

Tasks:

- Set up project package structure.
- Add `.env.example`.
- Add settings/config loader.
- Define core schemas:
  - monitoring instruction
  - source finding
  - enterprise finding
  - evidence packet
  - impact decision
  - remediation action
- Implement mock source monitoring backend.
- Implement local enterprise context backend.
- Implement mock Slack/report/ticket tools.
- Create initial ADK orchestrator and subagent definitions.

Deliverables:

- Local runnable command.
- Mock source monitoring subagent.
- Mock enterprise context subagent.
- Orchestrator combines findings and returns an impact summary.

Exit criteria:

- A developer can run one local command and see the orchestrator call subagents, synthesize context, and produce a cited impact decision.

## 6. Phase 2: Orchestrator Quality and Context Compression

Goal:

Make the orchestrator reliable before adding real integrations.

Tasks:

- Improve orchestrator instructions.
- Define strict subagent output schemas.
- Ensure subagents return compressed context, not long raw dumps.
- Add citation preservation rules.
- Add relevance, urgency, confidence, and uncertainty fields.
- Add approval decision rules.
- Add audit event recording to local storage.
- Add tests for the core loop.

Deliverables:

- Stable orchestrator prompts/instructions.
- Structured output from subagents.
- Local audit log.
- Basic evaluation fixtures.

Exit criteria:

- Given mock regulatory and enterprise evidence, Vigil consistently decides whether to ignore, ask for clarification, alert, report, or request approval.

## 7. Phase 3: Real Gemini and Grounded Source Search

Goal:

Replace mock source intelligence with Gemini-powered source monitoring where feasible.

Tasks:

- Configure Gemini model access for local development.
- Implement Gemini-backed source monitoring subagent.
- Use grounding search for source discovery where available.
- Preserve source URLs, titles, dates, snippets, and confidence.
- Keep mock backend for deterministic tests.
- Add source monitor evaluation cases.

Deliverables:

- Gemini-backed source monitoring backend.
- Config switch between mock and Gemini source backends.
- Source findings with grounding evidence.

Exit criteria:

- The source monitoring subagent can search for a user-specified compliance topic and return concise, cited findings to the orchestrator.

## 8. Phase 4: Enterprise Context Retrieval

Goal:

Add meaningful enterprise context retrieval while preserving local development ergonomics.

Tasks:

- Implement local document ingestion.
- Implement local retrieval backend.
- Add document metadata and citation model.
- Add Google Drive connector.
- Add Drive document listing and fetch behavior.
- Add retrieval abstraction for local versus Google backends.
- Evaluate Vertex AI RAG Engine versus local/vector fallback.
- Add initial multimodal retrieval experiment if feasible.

Deliverables:

- Local corpus retrieval.
- Google Drive connector.
- Enterprise context subagent using retrieval abstraction.
- Internal citations linked to local files or Drive documents.

Exit criteria:

- Given a regulatory topic, the enterprise context subagent returns relevant internal snippets and citations from local documents or Google Drive.

## 9. Phase 5: Slack, Reports, Approval, and Memory

Goal:

Turn analysis into operational enterprise workflow.

Tasks:

- Implement Slack posting tool.
- Implement Slack approval request flow or mock approval flow.
- Implement report generation tool.
- Implement local memory backend.
- Add memory retrieval to orchestrator context.
- Store organization preferences and prior false positives.
- Add mock ticket creation after approval.

Deliverables:

- Slack alert or mock Slack output.
- Approval-gated mock ticket creation.
- Report generation.
- Memory-influenced decisions.

Exit criteria:

- The orchestrator can use memory, source evidence, and enterprise evidence to send an alert, request approval, create a mock ticket, and generate an audit report.

## 10. Phase 6: Google Cloud Production Readiness

Goal:

Prepare Vigil for Gemini Enterprise Agent Platform and production deployment.

Tasks:

- Ensure ADK agent entrypoint is clean and deployable.
- Add production settings profile.
- Add service account documentation.
- Add Secret Manager documentation.
- Add logging and tracing guidance.
- Prepare Agent Runtime deployment path.
- Evaluate Agents CLI scaffold/evaluate/deploy/publish flow.
- Document Cloud Run fallback path if Agent Runtime setup blocks progress.
- Add Agent Card / marketplace-readiness metadata.

Deliverables:

- Production deployment notes.
- Agent Runtime readiness checklist.
- Agent Card draft.
- Cloud Run fallback instructions.
- Security and IAM checklist.

Exit criteria:

- The project has a clear path from local `uv` development to Agent Runtime deployment with production secrets, service account auth, and managed retrieval.

## 11. Phase 7: Demo and Evaluation Package

Goal:

Package the project for the hackathon.

Tasks:

- Create a polished demo scenario.
- Add demo data.
- Add repeatable demo script.
- Add evaluation scenarios.
- Add architecture diagram.
- Add README updates.
- Record demo video.

Deliverables:

- Demo script.
- Demo dataset.
- Evaluation results.
- Architecture diagram.
- Submission README.
- Video narrative.

Exit criteria:

- A judge can understand the business problem, watch Vigil perform the workflow, and see clear usage of ADK and Gemini Enterprise Agent Platform concepts.

## 12. Suggested Repository Structure

```text
vigil/
  app/
    agents/
      orchestrator.py
      source_monitoring.py
      enterprise_context.py
    tools/
      slack.py
      reports.py
      audit.py
      ticketing.py
    backends/
      source/
      retrieval/
      memory/
      actions/
    schemas/
    settings.py
    main.py
  data/
    demo_sources/
    demo_enterprise_docs/
  docs/
    vigil-system-design.md
    vigil-phased-plan.md
    vigil-implementation-plan.md
  evals/
  tests/
  .env.example
  README.md
  pyproject.toml
```

## 13. Immediate Next Steps

1. Add `.env.example`.
2. Add core dependencies to `pyproject.toml` after confirming exact ADK package names.
3. Create package structure.
4. Define Pydantic schemas for subagent outputs.
5. Implement local mock backends.
6. Implement first orchestrator-subagent loop.
7. Add one local demo command.

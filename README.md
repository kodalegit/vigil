# Vigil

Vigil is an autonomous regulatory impact agent for compliance teams. It watches trusted regulatory sources, extracts obligations, maps them to internal policies and controls, and pushes concise, evidence-backed Slack alerts for human review and approval.

Built for the Gemini Enterprise Agent Platform, Vigil turns regulatory change into a traceable operating workflow: monitor sources, retrieve enterprise context, classify impact, route approvals, and preserve the audit trail.

## Why Vigil

Lean legal and compliance teams are overwhelmed by regulatory noise. A new rule or supervisory update is only useful when the team can quickly answer:

- What changed?
- Does it apply to our products, jurisdictions, and risk profile?
- Which internal policies, controls, SOPs, or owners are affected?
- What should a human reviewer approve next?
- Can we prove later how the decision was made?

Vigil focuses on the hard middle of regulatory change management: obligation-to-internal-artifact mapping and Slack-first remediation orchestration. It is not a generic legal summarizer, and it does not present output as legal advice.

## What It Does

Vigil automates a focused regulatory impact loop:

```text
Detect change
  -> Extract obligations
  -> Retrieve internal context
  -> Map obligations to policies and controls
  -> Classify impact
  -> Alert in Slack
  -> Approve remediation
  -> Record ticket and audit history
```

In the reviewer demo, Vigil can:

- onboard an organization from Slack, including jurisdictions, risk tolerance, review channel, trusted sources, reviewers, and retrieval resources
- analyze a regulatory update from a deterministic mock source or live Gemini web search mode
- retrieve matching internal controls from a local corpus, with Vertex AI RAG Engine support available by configuration
- classify findings as actionable, informational, irrelevant, or ambiguous
- post Slack alerts with affected artifacts, evidence snippets, suggested actions, approval buttons, follow-up handling, and false-positive capture
- persist organization context and decisions in Firestore

## Architecture

Vigil uses a deliberately small agent architecture so final business judgment stays in one place.

- `VigilOrchestrator` owns the end-to-end decision: it loads organization context, session state, memory, and approved retrieval resources; calls specialist agents; merges evidence; classifies impact; writes the Slack alert; and gates remediation behind human approval.
- `SourceMonitoringAgent` gathers regulatory evidence from trusted or mock sources and returns structured obligations with citations, dates, risk signals, and uncertainty.
- `EnterpriseContextAgent` maps obligations to internal policies, controls, SOPs, snippets, owners, and business units using local retrieval or Vertex AI RAG Engine.

The subagents do bounded evidence gathering. The orchestrator makes the final impact decision, keeps the output approval-oriented, and records the audit trail.

See [docs/architecture-diagram.md](docs/architecture-diagram.md) for a GitHub-rendered architecture diagram.  
See [docs/vigil-system-design.md](docs/vigil-system-design.md) for the detailed system design.

## Gemini Enterprise Agent Platform

Vigil is designed around Gemini Enterprise Agent Platform production primitives:

- **Agent Runtime ready:** ADK-compatible agent code can be deployed to managed Agent Runtime. The public reviewer build currently runs the Slack API on Cloud Run for simple testing.
- **RAG Engine support:** `VIGIL_RETRIEVAL_BACKEND=rag_engine` can point approved organization context at an existing Vertex AI RAG Engine corpus.
- **Agent Platform Sessions:** session state is reserved for per-investigation context such as the current regulatory topic, selected evidence, and follow-up notes.
- **Memory Bank support:** `VIGIL_MEMORY_BACKEND=google` can use Agent Platform Memory Bank for durable reviewer preferences and reusable monitoring context. Memory writes are approval-gated.
- **Observability path:** the API is compatible with Cloud Logging, Cloud Trace, and ADK/Agent Platform traces for production debugging.

## Reviewer Demo

The deployed reviewer build is intentionally low-cost and repeatable:

- Slack is the primary interface for onboarding, analysis, alerts, approvals, and follow-up.
- Cloud Run serves the Slack/API app.
- Firestore stores organization context and impact decisions.
- Secret Manager stores Slack credentials.
- The source backend defaults to `mock` so public testing does not spend live web-search budget.
- The retrieval backend defaults to the local corpus, with RAG Engine available through configuration.
- The public fallback is the FastAPI `/docs` page; the ADK dev UI is disabled in the public build.

Tester instructions live in [docs/demo-testing-access.md](docs/demo-testing-access.md).

## Example Slack Alert

```text
New AI governance update impacts Model Risk Control Register

Classification: Actionable
Priority: High

What changed:
- Covered AI systems require documented human oversight.
- Vendor-managed AI workflows require retained audit evidence.

Why it matters:
- The model risk control register already governs high-impact AI systems.
- Existing vendor review controls need explicit evidence retention.

Affected artifacts:
- Model Risk Control Register, owner: Compliance Lead
- AI Incident Response SOP, owner: Trust & Safety

Suggested actions:
- Review affected controls and confirm ownership.
- Create an evidence note linking the source update and internal control sections.
- Open a remediation ticket after reviewer approval.

Buttons:
[Approve & create ticket] [Ask follow-up] [Mark as false positive]
```

## Technology

- Google ADK and Gemini
- Gemini web grounding/search for supervised live source monitoring
- Gemini Enterprise Agent Platform design path: Agent Runtime, Sessions, Memory Bank, RAG Engine
- Cloud Run, Firestore, Secret Manager, Cloud Build, Artifact Registry
- FastAPI and Slack SDK
- Local corpus retrieval with managed RAG Engine support
- ADK evals and pytest coverage for source, retrieval, Slack, and orchestration behavior

## Safety And Governance

Vigil is designed for human-in-the-loop compliance operations:

- remediation actions require human approval
- source citations and internal snippets are preserved for review
- ambiguous or low-confidence findings can be downgraded instead of alerted
- false positives can be captured as reusable organization context
- Slack callbacks verify request signatures and recover decision state from storage
- durable memory is reserved for approved preferences and reusable context, not unverified evidence

## Local Development

Install dependencies with `uv`, configure `.env`, and run the API locally:

```bash
uv run uvicorn vigil.fast_api_app:app --reload --host 0.0.0.0 --port 8000
```

For Slack/ngrok testing, point Slack to:

```text
https://<ngrok-host>/slack/commands
https://<ngrok-host>/slack/interactions
```

Useful checks:

```bash
agents-cli lint
uv run --extra dev pytest -s tests/unit
```

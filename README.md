# Vigil

Vigil is an autonomous regulatory impact assistant that watches trusted legal sources, finds the internal policies and artifacts they affect, and pushes concise, evidence-backed alerts and draft remediation actions into Slack for human approval.

Built for the Gemini Enterprise Agent Platform, Vigil turns regulatory change into a traceable operating workflow: monitor sources, extract obligations, retrieve enterprise context, classify impact, notify reviewers, capture approvals, and preserve the evidence trail.

## Problem

Yesterday, a new AI governance guideline was published. Today, the compliance lead is manually reading it, searching through Drive to see which policies are affected, and emailing stakeholders. Next week, they may need to prove to auditors what changed, how the company assessed impact, who approved the response, and what remediation was completed.

Lean in-house legal and compliance teams do not just need more legal summaries. They need help with the full regulatory change management loop:

1. Detect a relevant regulatory change.
2. Understand what changed and which obligations follow.
3. Map those obligations to internal policies, controls, SOPs, owners, and business units.
4. Decide whether the change is actionable, informational, or irrelevant.
5. Coordinate remediation without losing the evidence trail.

Vigil is focused on the under-served middle of that workflow: obligation-to-internal-artifact mapping and Slack-first remediation orchestration.

## Target User

Vigil is designed for an in-house legal or compliance lead at a mid-size fintech or SaaS company handling regulated data.

Their environment usually includes:

- Google Workspace for policies, SOPs, controls, meeting notes, and evidence.
- Slack as the main operational workflow surface.
- Basic ticketing such as Jira, ServiceNow, or an internal equivalent.
- A small team that cannot manually review every regulatory update in depth.

## Regulatory Impact Loop

Vigil automates a focused loop:

```text
Detect change
  -> Extract obligations
  -> Map to internal policies and controls
  -> Classify impact
  -> Alert in Slack
  -> Approve remediation
  -> Create ticket and audit log
```

The system is intentionally opinionated about impact. It should not merely summarize a law; it should explain what changed, why it matters to the organization, which internal artifacts appear affected, and what the human reviewer should do next.

## Demo Workflow

For the hackathon demo, Vigil demonstrates a full regulatory impact loop for a configured regulatory domain and a small internal control corpus.

1. A trusted regulatory source or mock source emits a new update.
2. Vigil extracts structured obligations with citations.
3. Vigil searches internal policies, SOPs, controls, and meeting notes using local retrieval or Vertex AI RAG Engine.
4. Vigil maps obligations to affected internal artifacts and owners.
5. Vigil classifies the event as actionable, informational, or irrelevant.
6. Vigil posts a structured Slack alert with evidence and suggested remediation.
7. On human approval, Vigil creates a mock ticket and records an audit event.

## Example Slack Alert

```text
New AML rule impacts Policy P-001

Classification: Actionable
Priority: High

What changed:
- Reporting frequency appears to increase for covered transaction reviews.
- The effective date is within the next quarter.

Why it matters:
- Policy P-001 currently references the older reporting cadence.
- The AML Operations SOP assigns review ownership to the compliance operations team.

Affected artifacts:
- Policy P-001, Section 3.2, owner: Compliance Lead
- AML Operations SOP, Section 4, owner: Compliance Ops

Suggested actions:
- Review and update Policy P-001 Section 3.2.
- Confirm whether AML Operations SOP Section 4 needs an owner or cadence update.
- Create an evidence note linking the source rule, affected sections, and approval.

Buttons:
[Approve & create ticket] [Ask follow-up] [Mark as false positive]
```

## Architecture

Vigil uses a deliberately simple agent architecture:

- `VigilOrchestrator` owns product judgment, triage, Slack output, approval, ticketing, and audit logging.
- `SourceMonitoringAgent` watches trusted sources and extracts changed obligations.
- `EnterpriseContextAgent` searches internal artifacts and maps obligations to policies, controls, snippets, owners, and business units.

See [`docs/vigil-system-design.md`](docs/vigil-system-design.md) for the detailed system design.
See [`docs/architecture-diagram.md`](docs/architecture-diagram.md) for a GitHub-rendered architecture diagram.

## Gemini Enterprise Agent Platform

Vigil is designed around the production building blocks of Gemini Enterprise Agent Platform Agent Runtime:

- **Agent Runtime ready:** the ADK agent code can be deployed to managed Agent Runtime, while the hackathon reviewer build runs the Slack API on Cloud Run for simple public testing.
- **RAG Engine support:** `VIGIL_RETRIEVAL_BACKEND=rag_engine` lets approved organization context point at an existing Vertex AI RAG Engine corpus. Slack onboarding captures RAG corpus, Drive folder, or Cloud Storage source metadata.
- **Agent Platform Sessions:** session state is reserved for per-investigation context such as current regulatory topic, selected evidence, and follow-up notes.
- **Memory Bank support:** `VIGIL_MEMORY_BACKEND=google` can use Agent Platform Memory Bank for durable reviewer preferences and reusable monitoring context. Memory writes are approval-gated.
- **Observability path:** the API is compatible with Cloud Logging, Cloud Trace, and ADK/Agent Platform traces for production debugging.

## Slack Onboarding

Slack is the first setup surface for organization context. The local flow supports:

- `/vigil onboard`, `/vigil setup`, `/onboard`, or `/setup` through `/slack/commands`
- interactive buttons and modal submissions through `/slack/interactions`
- org identity derived from Slack Enterprise ID first, then workspace team ID
- approved setup persisted through the existing organization context registry
- optional enterprise retrieval resource capture for existing RAG corpus, Drive folder ID, or GCS URI

For local ngrok testing:

1. Set `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, and `VIGIL_STORAGE_BACKEND=firestore` or `local`.
2. Run the API with `bash -ic 'uv run uvicorn vigil.fast_api_app:app --reload --host 0.0.0.0 --port 8000'`.
3. Point the Slack slash command request URL to `https://<ngrok-host>/slack/commands`.
4. Point the Slack interactivity request URL to `https://<ngrok-host>/slack/interactions`.
5. Run `/vigil onboard`, `/onboard`, or `/setup` in Slack, fill the modal, review the diff, and approve setup.

Slack modal submissions are acknowledged immediately and registry writes happen in
the background. If Slack shows "We had some trouble connecting," check the uvicorn
logs and ngrok request details for `/slack/interactions`; it usually means the
server did not respond within Slack's interactive callback timeout or the signing
secret rejected the request.

For deployed environments, direct Slack/API key env vars can be replaced with
Secret Manager references:

```text
SLACK_BOT_TOKEN_SECRET=projects/<project>/secrets/<name>/versions/latest
SLACK_SIGNING_SECRET_SECRET=projects/<project>/secrets/<name>/versions/latest
GOOGLE_API_KEY_SECRET=projects/<project>/secrets/<name>/versions/latest
```

Bare secret IDs also work when `GOOGLE_CLOUD_PROJECT` is set.

## Design Principles

- Keep the architecture simple: one orchestrator, a small number of bounded subagents, and mockable tools.
- Treat obligations and internal mappings as first-class structured outputs.
- Reduce alert fatigue by classifying events as actionable, informational, or irrelevant.
- Make Slack the front door for review and approval.
- Require human approval before creating remediation actions.
- Preserve source citations, internal snippets, decisions, approvals, and ticket creation in an audit trail.
- Avoid presenting outputs as final legal advice.

## Current Reviewer Build

The deployed reviewer build is intentionally low-cost and repeatable:

- Slack is the primary interface for onboarding, analysis, alerts, approvals, and follow-up.
- Firestore stores organization context and impact decisions.
- The source backend defaults to `mock` so public testing does not spend live web-search budget.
- The retrieval backend defaults to the local corpus, with RAG Engine support available through configuration.
- The public fallback is the FastAPI `/docs` page; the ADK dev UI is disabled in the public build.

## Hackathon Scope

Vigil should start narrow and credible:

- One coherent regulatory domain.
- Five to ten configured source documents or URLs.
- Ten to twenty synthetic internal policies, SOPs, controls, and meeting notes.
- Local retrieval for the public demo, plus managed Vertex AI RAG Engine support for production retrieval.
- Mock ticket creation instead of a full Jira or ServiceNow integration.
- Scenario tests that prove consistent outputs for a few predefined regulatory updates.

Future production hardening can add continuous source scheduling, richer Drive ingestion, real Jira or ServiceNow ticketing, permission-aware document previews, Agent Runtime deployment, Agent Platform Sessions, Memory Bank, and production observability.

# Vigil Architecture Diagram

```mermaid
flowchart TB
    reviewer["Compliance reviewer<br/>Slack workspace"] --> slack["Slack app<br/>/vigil commands, modals, buttons"]
    slack --> api["FastAPI service<br/>Slack verification + ADK HTTP API"]

    api --> orchestrator["VigilOrchestrator<br/>final product judgment"]

    orchestrator --> context["Context compiler<br/>org profile, session state, memory, approved resources"]
    orchestrator --> sourceAgent["SourceMonitoringAgent<br/>regulatory change + obligation extraction"]
    orchestrator --> enterpriseAgent["EnterpriseContextAgent<br/>obligation-to-artifact mapping"]

    sourceAgent --> sourceBackend{"Source backend"}
    sourceBackend --> mockSource["Mock source<br/>repeatable reviewer demo"]
    sourceBackend --> geminiSearch["Gemini web grounding<br/>live trusted-source monitoring"]

    enterpriseAgent --> retrievalBackend{"Retrieval backend"}
    retrievalBackend --> localCorpus["Local org corpus<br/>demo policies, SOPs, controls"]
    retrievalBackend --> ragEngine["Vertex AI RAG Engine<br/>Drive or Cloud Storage corpora"]

    context --> storage["Org context + decisions<br/>Firestore or local JSONL"]
    context --> memory["Memory backend<br/>local memory or Agent Platform Memory Bank"]
    context --> sessions["Agent Platform Sessions<br/>per-investigation state"]

    orchestrator --> classifier["Impact decision<br/>actionable, informational, irrelevant, ambiguous"]
    classifier --> alert["Slack alert<br/>evidence, affected artifacts, suggested actions"]
    alert --> approval["Human approval gate"]
    approval --> ticket["Mock or real ticket backend"]
    approval --> audit["Audit trail<br/>sources, snippets, decisions, approvals"]

    subgraph "Reviewer build"
        cloudRun["Cloud Run<br/>public Slack demo, mock source, local retrieval"]
    end

    subgraph "Production path"
        runtime["Gemini Enterprise Agent Platform<br/>Agent Runtime, Sessions, Memory Bank, RAG Engine"]
    end

    cloudRun -.serves.-> api
    runtime -.deploys agent.-> orchestrator
```

Vigil keeps the orchestrator responsible for the final impact judgment. The subagents are deliberately bounded: they gather cited regulatory evidence and cited enterprise context, then return structured findings to the orchestrator for classification, Slack presentation, approval gating, ticket creation, memory updates, and audit logging.

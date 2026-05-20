# Vigil Design Spec

## Overview

Vigil is an autonomous regulatory impact assistant for lean legal and compliance teams at mid-size SaaS companies. The local prototype demonstrates the EU AI Act governance workflow: detect a regulatory update, extract deployer obligations, map those obligations to internal AI policies and controls, recommend remediation, simulate a Slack alert, and preserve audit evidence.

## Example Use Cases

- Analyze an EU AI Act update and identify affected internal AI governance artifacts.
- Produce a concise compliance alert with citations, recommended actions, and approval requirements.
- Generate a mock audit trail showing source evidence, affected controls, and simulated remediation coordination.

## Tools Required

- `source_monitoring_agent`: ADK `AgentTool` specialist that extracts regulatory changes and obligations.
- `enterprise_context_agent`: ADK `AgentTool` specialist that maps obligations to internal policies, controls, SOPs, and snippets.
- `run_regulatory_impact_analysis`: local deterministic compatibility tool used by CLI/tests while the ADK orchestration path matures.
- Source tools: mock source search or Gemini Google Search grounding.
- Enterprise tools: local indexed corpus retrieval first, Vertex AI RAG Engine next, Google Drive MCP only as auxiliary file access.
- Future action tools: Slack approval workflow, ticket creation, and audit storage.

## Constraints & Safety Rules

- Do not present outputs as final legal advice.
- Require human approval before creating remediation tickets or externally visible actions.
- Preserve source citations, internal snippets, and audit records.
- Prefer official or trusted regulatory sources for production source monitoring.
- Keep local mock mode deterministic for fast iteration and repeatable tests.

## Success Criteria

- `agents-cli info` recognizes the project.
- The local CLI demo returns an actionable EU AI Act impact decision.
- The ADK app exposes a Vigil orchestrator agent that explicitly invokes source monitoring and enterprise context specialists as `AgentTool`s.
- The first local tool call returns source evidence, internal mappings, recommended actions, and simulated alert/report actions.
- The enterprise context path returns document metadata, chunks, citations, relevance scores, and obligation mappings.

## Reference Samples

- `deep-search`: useful later for iterative cited research patterns.
- `adk-ae-oauth`: useful later for Google Workspace/OAuth and Agent Runtime patterns.
- `genmedia-for-commerce`: useful later for MCP/full-stack Gemini Enterprise registration patterns.
- `safety-plugins`: useful later for reusable guardrails.

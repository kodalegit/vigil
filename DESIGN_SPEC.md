# Vigil Design Spec

## Overview

Vigil is an autonomous regulatory impact assistant for lean legal and compliance teams at mid-size SaaS companies. The local prototype demonstrates the EU AI Act governance workflow: detect a regulatory update, extract deployer obligations, map those obligations to internal AI policies and controls, recommend remediation, simulate a Slack alert, and preserve audit evidence.

## Example Use Cases

- Analyze an EU AI Act update and identify affected internal AI governance artifacts.
- Produce a concise compliance alert with citations, recommended actions, and approval requirements.
- Generate a mock audit trail showing source evidence, affected controls, and simulated remediation coordination.

## Tools Required

- `run_regulatory_impact_analysis`: local deterministic tool that runs the current Vigil mock source, retrieval, action, and audit backends.
- Future source tools: Gemini grounded search and configured source monitoring.
- Future enterprise tools: Google Drive search, local corpus retrieval, and Agent Platform RAG or Vector Search.
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
- The ADK app exposes a Vigil orchestrator agent with source monitoring and enterprise context subagents.
- The first local tool call returns source evidence, internal mappings, recommended actions, and simulated alert/report actions.

## Reference Samples

- `deep-search`: useful later for iterative cited research patterns.
- `adk-ae-oauth`: useful later for Google Workspace/OAuth and Agent Runtime patterns.
- `genmedia-for-commerce`: useful later for MCP/full-stack Gemini Enterprise registration patterns.
- `safety-plugins`: useful later for reusable guardrails.

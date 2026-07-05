# Vigil Demo Access

This guide is for reviewers trying Vigil for the first time. The best way to experience the project is through Slack, where Vigil onboards an organization, analyzes a regulatory update, maps it to internal controls, and posts an approval-ready impact alert.

## Try The Slack Demo

Join the shared Slack workspace and open the public Vigil demo channel. A pinned message in the channel should include the same steps and test values below.

1. Run `/vigil onboard` in the demo channel.
2. Fill the modal with the sample organization profile.
3. Submit and approve the proposed setup.
4. Run the analyze command.
5. Review the Slack alert, mapped controls, suggested actions, and approval/follow-up buttons.

## Sample Organization Profile

Use these values in the onboarding modal:

```text
Organization name: Example Financial Group
Sectors: financial services
Products or systems: AI credit model, customer support chatbot, vendor risk platform
Business profile: Financial services company using AI systems for customer decisions, operational support, and third-party vendor workflows.
Jurisdictions: United States, European Union
Risk tolerance: Medium
Default review channel: the demo channel
Trusted source names: SEC AI and cybersecurity updates
Trusted source URLs: https://www.sec.gov/newsroom/press-releases
Source domains: AI governance, cybersecurity, financial compliance
Regulators: SEC, European Commission
First monitoring query: AI governance, cybersecurity incident escalation, vendor oversight, and audit evidence obligations for financial services.
Monitoring cadence: weekly
Retrieval source type: policy corpus
Retrieval source name: Local organization control corpus
Retrieval source URI: local://vigil/data/corpus
```

## Analyze Command

After onboarding, run:

```text
/vigil analyze SEC financial services update requiring AI model governance, cybersecurity incident escalation, vendor oversight, and retained audit evidence
```

Expected result: Vigil classifies the update as actionable, maps it to the local governance control corpus, and posts a Slack alert with affected artifacts, evidence, suggested actions, and approval/follow-up controls.

## What To Look For

- Slack-first onboarding that captures organization context and trusted monitoring preferences.
- Obligation-to-control mapping, not just a regulatory summary.
- An actionable classification with affected internal artifacts and owners.
- Human approval before ticket creation.
- Follow-up and false-positive paths that preserve the decision trail.

## Fallback API Docs

If Slack access is unavailable, use the public FastAPI docs as a fallback:

[https://vigil-demo-333479689357.us-central1.run.app/docs](https://vigil-demo-333479689357.us-central1.run.app/docs)

The Slack demo is the intended reviewer experience. The API docs are provided only as a lightweight way to inspect the deployed service surface.

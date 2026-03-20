# Content Publishing Flow - CrewAI Flow + Agent Control

A complete CrewAI Flow example demonstrating routing (`@router`), embedded crews, and human-in-the-loop via steering, with Agent Control guardrails at every pipeline stage.

## What It Demonstrates

- **CrewAI Flows** with `@start`, `@listen`, and `@router` decorators
- **Routing logic** that directs content through different pipelines based on type
- **Agent Control integration** at every stage (JSON, LIST, REGEX evaluators + STEER actions)
- **Pydantic state management** across flow stages
- **Steering with retry** for corrective actions (e.g., adding missing Executive Summary)
- **Human-in-the-loop** via STEER action for manager approval

## Flow Architecture

```
@start: intake_request
    |  JSON evaluator: require topic, audience, content_type
    |
@listen(intake_request): research
    |  Researcher:   LIST evaluator (block banned sources)
    |  Fact-Checker: REGEX evaluator (flag unverified claims)
    |
@listen(research): draft_content
    |  Writer: REGEX (block PII), LIST (block banned topics)
    |
@router(draft_content): quality_gate
    |
    +-- "low_risk" (blog_post)
    |       |
    |   @listen: auto_publish
    |       REGEX: final PII scan, then publish
    |
    +-- "high_risk" (press_release)
    |       |
    |   @listen: compliance_review
    |       Legal Reviewer: JSON (require disclaimer, legal_reviewed)
    |       Editor: REGEX (PII), client-side steer (Executive Summary)
    |       Then: publish
    |
    +-- "escalation" (internal_memo)
            |
        @listen: human_review
            STEER: pause for manager approval
```

## Scenarios

| # | Scenario | Input | Path | Expected Outcome |
|---|----------|-------|------|------------------|
| 1 | Blog post | topic + audience + "blog_post" | low_risk | Intake -> Research -> Draft -> Auto-publish |
| 2 | Press release | topic + audience + "press_release" | high_risk | Intake -> Research -> Draft -> Compliance review -> Publish |
| 3 | Internal memo | topic + audience + "internal_memo" | escalation | Intake -> Research -> Draft -> Human review (STEER) |
| 4 | Invalid request | missing fields | blocked | JSON evaluator blocks at intake |
| 5 | Banned topic | draft contains "insider trading" | blocked | LIST evaluator blocks at draft |
| 6 | PII in draft | draft contains email/phone/SSN | blocked | REGEX evaluator blocks at draft |

## Prerequisites

- **Python 3.12+**
- **uv** package manager
- **Docker** for the Agent Control server's PostgreSQL
- **OpenAI API key** (for full CrewAI agent execution, not required for simulated scenarios)

## Running

### 1. Start the Agent Control Server

From the monorepo root:

```bash
make server-run
```

Verify:

```bash
curl http://localhost:8000/health
```

### 2. Install Dependencies

```bash
cd examples/crewai/content_publishing_flow
uv pip install -e . --upgrade
```

### 3. Set Environment Variables

```bash
export OPENAI_API_KEY="your-key-here"
export AGENT_CONTROL_URL="http://localhost:8000"  # optional, this is the default
```

### 4. Setup Controls (One-Time)

```bash
uv run --active python setup_controls.py
```

This creates 9 controls covering all pipeline stages and associates them with the `content-publishing-flow` agent.

### 5. Run the Flow

```bash
uv run --active python -m content_publishing_flow.main
```

## Controls Reference

| Control Name | Evaluator | Stage | Step | Action |
|---|---|---|---|---|
| flow-intake-validation | JSON (required_fields) | pre | validate_request | deny |
| flow-research-banned-sources | LIST (unreliable sources) | post | research_topic | deny |
| flow-factcheck-unverified | REGEX (unverified markers) | post | fact_check | deny |
| flow-draft-pii-block | REGEX (SSN/email/phone) | post | write_draft | deny |
| flow-draft-banned-topics | LIST (restricted topics) | post | write_draft | deny |
| flow-compliance-legal-review | JSON (disclaimer, legal_reviewed) | post | legal_review | deny |
| flow-editor-pii-block | REGEX (SSN/email/phone) | post | edit_content | deny |
| flow-human-review-steer | LIST (internal_memo) | pre | request_human_review | steer |
| flow-publish-pii-scan | REGEX (SSN/email/phone) | pre | publish_content | deny |

## How Agent Control Integrates with CrewAI Flows

Agent Control works at the **tool boundary** within each flow stage:

1. Each flow stage calls a **controlled function** (wrapped with `@control()`)
2. The SDK sends the function's input/output to the Agent Control server
3. The server evaluates controls matching the step name and stage (pre/post)
4. On **deny**: `ControlViolationError` is raised, the stage handles it
5. On **steer**: `ControlSteerError` provides corrective guidance for retry
6. On **allow**: execution proceeds normally

This pattern means controls are defined on the **server** (not in code), so you can update rules, add new controls, or change actions without redeploying the agent.

```
Flow Stage (e.g., draft_content)
    |
    v
controlled_fn(topic=..., audience=...)
    |
    +-- PRE check: server evaluates input against matching controls
    |
    +-- Function executes (simulated or LLM-based)
    |
    +-- POST check: server evaluates output against matching controls
    |
    v
Result returned to flow (or error raised)
```

# Agent Control on Azure AI Foundry (LangGraph)

A customer support agent running on [Azure AI Foundry Hosted Agents](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents), governed by Agent Control at runtime.

Demonstrates:
- **Runtime guardrails** - toggle controls on/off from the UI without redeploying the agent
- **Step-specific controls** - different policies for different tools and the LLM itself
- **Pre and post evaluation** - block dangerous inputs before the LLM sees them, block sensitive outputs before the user sees them

## Architecture

```
User --> Azure AI Foundry Hosted Agent (port 8088)
              |
              +--> @control() decorator on every tool + LLM call
              |         |
              |         +--> Agent Control Server (separate deployment)
              |
              +--> LangGraph StateGraph
                        |
                        +--> Azure OpenAI (gpt-4.1-mini)
                        +--> Tools (4 total: 2 safe, 2 sensitive)
```

## Tools

| Tool | Returns | Controlled? |
|------|---------|-------------|
| `get_order_status` | Shipping status, items, ETA, tracking | No server control (safe data) |
| `get_order_internal` | Payment info, margins, internal notes, fraud flags | `block-internal-data` (post) |
| `lookup_customer` | Name, email, membership, recent orders | No server control (safe data) |
| `lookup_customer_pii` | Phone, DOB, address, credit card, risk score | `block-customer-pii` (post) |

The LLM call itself (`llm_call`) is also wrapped with `@control()`:
- `block-prompt-injection` (pre) - blocks adversarial inputs
- `block-competitor-discuss` (pre) - blocks competitor comparisons (business policy)

## Prerequisites

- Python 3.12+
- Docker
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) (`az`)
- [Azure Developer CLI](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd) (`azd`)
- An Azure subscription

## Setup

### 1. Start the Agent Control server

```bash
curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml \
  | docker compose -f - up -d
```

Verify: `curl http://localhost:8000/health`

### 2. Install dependencies

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your Azure AI Foundry endpoint and model deployment name
```

### 4. Seed controls

```bash
python seed_controls.py
```

This creates 4 controls (all disabled by default):
- `block-prompt-injection` - `llm_call` pre stage
- `block-internal-data` - `get_order_internal` post stage
- `block-customer-pii` - `lookup_customer_pii` post stage
- `block-competitor-discuss` - `llm_call` pre stage

### 5. Test locally

```bash
python local_test.py
```

### 6. Deploy to Azure AI Foundry

From the repo root:

```bash
azd auth login
azd init -t Azure-Samples/azd-ai-starter-basic -e my-agent-env
azd ai agent init -m examples/azure_foundry_langgraph/agent.yaml
azd up
```

## Demo Flow

1. Start with all controls **disabled** - show the unprotected agent leaking internal notes and PII
2. Enable controls one by one in the Agent Control UI - each blocks a different category of risk
3. Toggle controls on/off in real-time - same agent, same code, different behavior

See the full demo script in the repo docs.

## File Overview

| File | Purpose |
|------|---------|
| `tools.py` | 4 tools, each decorated with `@control()` |
| `graph.py` | LangGraph StateGraph with `@control()` on the LLM call |
| `agent_control_setup.py` | `agent_control.init()` bootstrap |
| `model.py` | Azure OpenAI chat model via `langchain-azure-ai` |
| `settings.py` | pydantic-settings configuration |
| `seed_controls.py` | Creates the 4 demo controls on the server |
| `hosted_app.py` | `from_langgraph()` entrypoint for Foundry |
| `Dockerfile` | Container for Foundry Hosted Agents (port 8088) |
| `agent.yaml` | Foundry agent definition |

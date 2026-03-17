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
- [Azure Developer CLI](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd) (`azd`) with the agents extension
- An Azure subscription with permissions to create resources (Owner or User Access Administrator on the resource group)

## Setup

### 1. Start the Agent Control server

For local development, run Agent Control locally:

```bash
curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml \
  | docker compose -f - up -d
```

Verify: `curl http://localhost:8000/health`

For production or demo, deploy Agent Control to an Azure VM (or any host with Docker):

```bash
# Create a VM
az group create --name my-demo-rg --location eastus
az vm create --resource-group my-demo-rg --name agent-control-vm \
  --image Ubuntu2204 --size Standard_B2s \
  --admin-username azureuser --generate-ssh-keys
az vm open-port --resource-group my-demo-rg --name agent-control-vm --port 8000

# SSH in and deploy
ssh azureuser@<public-ip>
sudo apt update && sudo apt install -y docker.io docker-compose-v2
curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml \
  | docker compose -f - up -d
```

### 2. Install dependencies

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:
- `AGENT_CONTROL_URL` - your Agent Control server URL (e.g., `http://localhost:8000` or `http://<vm-ip>:8000`)
- `MODEL_DEPLOYMENT_NAME` - your Azure OpenAI model deployment name
- `AZURE_AI_PROJECT_ENDPOINT` - your Foundry project endpoint (only needed for local testing with Azure model)

### 4. Seed controls

```bash
python seed_controls.py
```

This registers the agent and creates 4 controls (all disabled by default):
- `block-prompt-injection` - `llm_call` pre stage
- `block-internal-data` - `get_order_internal` post stage
- `block-customer-pii` - `lookup_customer_pii` post stage
- `block-competitor-discuss` - `llm_call` pre stage

### 5. Test locally

```bash
python local_test.py
```

Enable/disable controls in the Agent Control UI and re-run to see different behavior.

### 6. Deploy to Azure AI Foundry

#### Install the azd agents extension

```bash
azd extension install azure.ai.agents
```

#### Initialize azd

From this example directory:

```bash
azd auth login
azd init -t Azure-Samples/azd-ai-starter-basic -e my-agent-env
```

When prompted:
- "Continue initializing?" - Yes
- "Overwrite existing files?" - Keep existing files

#### Register the agent

```bash
azd ai agent init -m agent.yaml
```

This reads `agent.yaml`, resolves model deployments, and adds the agent as a service in `azure.yaml`.

#### Provision Azure resources

```bash
azd provision
```

This creates (if they don't already exist):
- Azure AI Services account + Foundry project
- Azure Container Registry (ACR)
- Capability host for Hosted Agents
- Application Insights + Log Analytics
- Model deployment (gpt-4.1-mini)

> **Note:** You need Owner or User Access Administrator role on the resource group for the RBAC role assignments in the Bicep template.

#### Deploy the agent

```bash
azd deploy CustomerSupportAgentLG
```

This builds the Docker image remotely in ACR and deploys it as a Hosted Agent. The output includes the playground URL and agent endpoint.

#### If deploying to an existing Foundry project

If you already provisioned resources and want to deploy from a fresh checkout, set the required azd environment variables manually:

```bash
azd env new my-agent-env
azd env set AZURE_RESOURCE_GROUP "<your-resource-group>"
azd env set AZURE_LOCATION "<region>"
azd env set AZURE_SUBSCRIPTION_ID "<subscription-id>"
azd env set AZURE_AI_ACCOUNT_NAME "<ai-services-account-name>"
azd env set AZURE_AI_PROJECT_NAME "<project-name>"
azd env set AZURE_AI_PROJECT_ID "<full-arm-resource-id-of-project>"
azd env set AZURE_AI_PROJECT_ENDPOINT "<project-services-endpoint>"
azd env set AZURE_OPENAI_ENDPOINT "<openai-endpoint>"
azd env set AZURE_CONTAINER_REGISTRY_ENDPOINT "<acr-login-server>"
azd env set ENABLE_HOSTED_AGENTS "true"

azd deploy CustomerSupportAgentLG
```

> **Tip:** The `AZURE_AI_PROJECT_ID` is the full ARM resource ID, e.g.,
> `/subscriptions/.../resourceGroups/.../providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>`

#### Important notes

- The Dockerfile must include `pip install --upgrade pip` to avoid packaging version errors during remote builds
- Add a `.dockerignore` to exclude `.venv/`, `.env`, `infra/`, `.azure/` from the Docker build context
- Hosted Agents require `linux/amd64` containers - azd handles this via `remoteBuild: true`
- After resetting the Agent Control DB, you must redeploy the agent (so `agent_control.init()` runs fresh)
- The SDK refreshes controls every 5 seconds (`POLICY_REFRESH_INTERVAL_SECONDS=5`) - after toggling a control in the UI, wait a few seconds before testing

## Demo Flow

1. Start with all controls **disabled** - show the unprotected agent leaking internal notes and PII
2. Enable controls one by one in the Agent Control UI - each blocks a different category of risk
3. Toggle controls on/off in real-time - same agent, same code, different behavior

See [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for the full step-by-step demo script with prompts, expected results, and talking points.

## File Overview

| File | Purpose |
|------|---------|
| `tools.py` | 4 tools, each decorated with `@control()` |
| `graph.py` | LangGraph StateGraph with `@control()` on the LLM call |
| `agent_control_setup.py` | `agent_control.init()` bootstrap + health check |
| `model.py` | Azure OpenAI chat model via `langchain-azure-ai` |
| `settings.py` | pydantic-settings configuration |
| `seed_controls.py` | Creates the 4 demo controls on the server |
| `local_test.py` | Local integration test (no Azure model needed) |
| `hosted_app.py` | `from_langgraph()` entrypoint for Foundry |
| `Dockerfile` | Container for Foundry Hosted Agents (port 8088) |
| `.dockerignore` | Excludes .venv, .env, infra from container build |
| `agent.yaml` | Foundry Hosted Agent definition |
| `requirements.txt` | Python dependencies |
| `.env.example` | Environment variable template |

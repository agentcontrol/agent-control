<p align="center">
  <img
    src="docs/images/AgentControl-logo-light.png#gh-light-mode-only"
    alt="Agent Control Logo (light)"
    width="120"
  />
  <img
    src="docs/images/AgentControl-logo-dark.png#gh-dark-mode-only"
    alt="Agent Control Logo (dark)"
    width="120"
  />
</p>

<h1 align="center">Agent Control</h1>

<p align="center">
  <a href="https://opensource.org/licenses/Apache-2.0"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+" /></a>
  <a href="https://pypi.org/project/agent-control-sdk/"><img src="https://img.shields.io/pypi/v/agent-control-sdk.svg" alt="PyPI version" /></a>
  <a href="https://www.npmjs.com/package/agent-control"><img src="https://img.shields.io/npm/v/agent-control.svg" alt="npm version" /></a>
</p>

<p align="center">
  <a href="https://docs.agentcontrol.dev/">Docs</a> &middot;
  <a href="https://docs.agentcontrol.dev/core/quickstart">Quickstart Guide</a> &middot;
  <a href="examples/">Examples</a> &middot;
  <a href="https://join.slack.com/t/agentcontrol/shared_invite/zt-3s2pbclup-T4EJ5sA7SOxR6jTeETZljA">Slack</a>
</p>

Runtime guardrails for AI agents - configurable, extensible, and production-ready.

- **Minimal integration** - add guardrails with a decorator, callback, or a few lines of SDK code
- **Runtime configuration** - update controls via API or UI without redeploying
- **Pluggable evaluators** - built-in (regex, list, AI-powered) or bring your own
- **Framework support** - works with LangChain, CrewAI, Google ADK, AWS Strands, and more

## Quick Start

Start the server and UI with Docker:

```bash
curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml | docker compose -f - up -d
```

Install the SDK:

```bash
pip install agent-control-sdk
```

Add guardrails to your agent:

```python
import agent_control
from agent_control import control

agent_control.init(agent_name="my_agent", agent_description="My AI Agent")

@control()
async def chat(message: str) -> str:
    return await llm.ainvoke(message)
```

This is the decorator approach - Agent Control also integrates via [framework callbacks](examples/google_adk_callbacks/), [direct SDK calls](https://docs.agentcontrol.dev/core/quickstart), and a [TypeScript SDK](examples/typescript_sdk/).

Then open the **[UI dashboard](http://localhost:8000)** to create controls (block PII, detect prompt injections, filter toxic content, and more). See the [UI Quickstart](https://docs.agentcontrol.dev/core/ui-quickstart) for a walkthrough.

## Examples

| Example | Description |
|---------|-------------|
| [Customer Support Agent](examples/customer_support_agent/) | PII protection, prompt-injection defense, multiple tools |
| [Steer Action Demo](examples/steer_action_demo/) | Allow, deny, warn, and steer actions for a banking agent |
| [LangChain](examples/langchain/) | Protect a SQL agent from dangerous queries |
| [CrewAI](examples/crewai/) | Agent Control + CrewAI guardrails for customer support |
| [Google ADK](examples/google_adk_callbacks/) | Model and tool protection using ADK callbacks |
| [AWS Strands](examples/strands_agents/) | Guardrails for Strands agent workflows |
| [TypeScript SDK](examples/typescript_sdk/) | TypeScript example using the npm package |

See [all examples](examples/README.md) for the full list.

## Local Development

```bash
git clone https://github.com/agentcontrol/agent-control.git
cd agent-control
make sync          # install dependencies
make server-run    # start server (boots Postgres + runs migrations)
make ui-install    # install UI dependencies (separate shell)
make ui-dev        # start UI at localhost:4000
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines, code conventions, and PR workflow.

## License

Apache 2.0 - see [LICENSE](LICENSE).

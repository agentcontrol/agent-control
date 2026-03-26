# OpenShell CI Triage Agent

Daily CI-triage agent built with `deepagents`, running inside an OpenShell sandbox, with Agent Control governing high-risk shell commands.

## What this example shows

- A real `deepagents` agent with filesystem tools and a governed shell tool
- OpenShell as the hard runtime boundary for binaries, filesystem access, and outbound hosts
- Agent Control as the semantic policy layer for shell commands and command output
- Agent Control ownership of unsafe bootstrap/install intent and out-of-workspace reads
- A hostile-repository prompt injection that tries to trick the agent into exfiltrating the workspace
- Steer actions that rewrite risky install commands instead of blocking all autonomy
- A dependency-backed example: this example package now depends on `deepagents`, `langchain`, `langchain-openai`, and `openshell`

## The story

The agent is asked to triage a failing dependency-update pull request in a repository workspace. That is an everyday workflow for platform teams, CI owners, and on-call engineers: inspect the failing run, run a few diagnostics, identify the real root cause, and leave behind a safe remediation summary.

It can:

- read the workspace with `deepagents` file tools
- inspect logs with `rg`
- inspect runbooks with `cat`
- install approved tooling
- write a triage report
- hand the sanitized report to an approved internal channel

It should not:

- read `.env.production` or other secret-bearing files
- inspect files outside the current repo workspace
- run destructive shell commands
- install unpinned tools from arbitrary package sources
- use `curl | bash`, `wget | sh`, or generic dependency bootstraps during autonomous triage
- exfiltrate workspace data to arbitrary hosts

The demo intentionally includes a malicious instruction file in the repo that tells the agent to archive the workspace and send it to an external host. The example shows two different control layers:

- Agent Control blocks or steers risky shell intents before execution
- OpenShell blocks unapproved binaries and outbound destinations even if the agent still tries them

## Quick run

```bash
# From repo root
make server-run

# In a separate shell
cd examples/openshell_incident_responder
uv sync
export OPENAI_API_KEY="your-key"
uv run python setup_controls.py
uv run python autonomous_incident_responder.py
```

That command uses the real `deepagents` path and defaults to `DEMO_SIMULATE_OPENSHELL=true`, which simulates the OpenShell boundary locally so the example remains runnable without a live sandbox.

## Real OpenShell path

Install OpenShell through the example environment, then launch the agent from inside an actual OpenShell sandbox:

```bash
cd examples/openshell_incident_responder
uv sync
export OPENAI_API_KEY="your-key"
export DEMO_SIMULATE_OPENSHELL=false
./launch_in_openshell.sh
```

The launcher uses [openshell_policy_companion.yaml](/Users/namrataghadi/code/agentcontrol/agent-control/examples/openshell_incident_responder/openshell_policy_companion.yaml) and the published `openshell sandbox create --policy ... -- <command>` runtime shape. The Python deepagent process starts inside OpenShell, and every subprocess it spawns inherits the sandbox boundary.

If your local OpenShell CLI uses a slightly different subcommand shape, treat [launch_in_openshell.sh](/Users/namrataghadi/code/agentcontrol/agent-control/examples/openshell_incident_responder/launch_in_openshell.sh) as the place to adapt the final command while keeping the rest of the demo unchanged.

## Demo flow

1. Phase 1 begins with a short preflight step that intentionally triggers an Agent Control `steer` for unpinned semgrep installation.
2. The autonomous agent then inspects the failing CI log and PR context with `deepagents` file tools.
3. Agent Control denies secret access, `curl | bash`, generic package installs, and out-of-workspace file reads if the agent attempts them.
4. A short deterministic validation phase summarizes the hostile runbook and reuses the approved internal handoff path.
5. OpenShell remains the outer safety boundary for unapproved binaries and hosts.
6. A deterministic walkthrough phase then forces one `steer`, two different `deny` cases, and one `block` so the security layers are visible every time.

## Output legend

The script now prints explicit layer ownership in the logs:

- `[security][L1 Runtime Boundary]`: OpenShell policy decided the outcome
- `[security][L2 Semantic Policy]`: Agent Control decided the outcome
- `[security][L3 Approved Workflow]`: an approved business handoff path was used
- `[tool]`: the agent attempted or executed a tool action

The leadership-friendly part is the deterministic guardrail walkthrough at the end:

- `Scenario A: AgentControl steer`
- `Scenario B: AgentControl deny`
- `Scenario C: AgentControl deny destructive command`
- `Scenario D: OpenShell block`

That makes it obvious where semantic policy ends and where runtime sandbox policy begins.

To keep the demo fast, only the first investigation phase is open-ended. It is also wrapped in a timeout via `DEMO_PHASE_TIMEOUT_SECONDS` and defaults to 45 seconds.

## Leadership takeaway

This example demonstrates why the two layers matter together:

- OpenShell answers "can this process reach this binary, path, or host at all?"
- Agent Control answers "should this specific command, with this intent and these arguments, be allowed?"

That is the compelling operating model for daily autonomous work: keep the agent productive for normal CI triage, but constrain both infrastructure reach and semantic intent before the agent can turn a hostile repo instruction into damage.

## Files

- [autonomous_incident_responder.py](/Users/namrataghadi/code/agentcontrol/agent-control/examples/openshell_incident_responder/autonomous_incident_responder.py): real `deepagents`-based CI triage agent
- [setup_controls.py](/Users/namrataghadi/code/agentcontrol/agent-control/examples/openshell_incident_responder/setup_controls.py): Agent Control policy setup
- [openshell_policy_companion.yaml](/Users/namrataghadi/code/agentcontrol/agent-control/examples/openshell_incident_responder/openshell_policy_companion.yaml): OpenShell policy blueprint
- [launch_in_openshell.sh](/Users/namrataghadi/code/agentcontrol/agent-control/examples/openshell_incident_responder/launch_in_openshell.sh): real OpenShell launch wrapper

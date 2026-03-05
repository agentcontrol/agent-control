/**
 * Setup script — creates demo controls, a policy, and assigns it to the agent.
 *
 * Run once after starting the server:
 *   npm run setup
 */

import { AgentControlClient, type ControlDefinitionInput } from "agent-control";

const serverUrl = process.env.AGENT_CONTROL_URL ?? "http://localhost:8000";
const apiKey = process.env.AGENT_CONTROL_API_KEY;
const agentName = "customer-support-agent-ts-2";
const policyName = `policy-${agentName}`;

const client = new AgentControlClient();
client.init({
  agentName,
  serverUrl,
  ...(apiKey ? { apiKey } : {}),
  registerAgent: false,
});

interface ControlSpec {
  name: string;
  definition: ControlDefinitionInput;
}

const DEMO_CONTROLS: ControlSpec[] = [
  {
    name: "block-ssn-in-input",
    definition: {
      description: "Blocks user messages containing SSN patterns",
      enabled: true,
      execution: "server",
      scope: { stages: ["pre"], stepTypes: ["llm"], stepNames: ["respond_to_customer"] },
      selector: { path: "input" },
      evaluator: {
        name: "regex",
        config: { pattern: String.raw`\d{3}-\d{2}-\d{4}` },
      },
      action: { decision: "deny" },
    },
  },
  {
    name: "block-ssn-in-output",
    definition: {
      description: "Blocks LLM responses containing SSN patterns",
      enabled: true,
      execution: "server",
      scope: { stages: ["post"], stepTypes: ["llm"], stepNames: ["respond_to_customer"] },
      selector: { path: "output" },
      evaluator: {
        name: "regex",
        config: { pattern: String.raw`\d{3}-\d{2}-\d{4}` },
      },
      action: { decision: "deny" },
    },
  },
  {
    name: "block-prompt-injection",
    definition: {
      description: "Blocks common prompt injection attempts",
      enabled: true,
      execution: "server",
      scope: { stages: ["pre"], stepTypes: ["llm"], stepNames: ["respond_to_customer"] },
      selector: { path: "input" },
      evaluator: {
        name: "regex",
        config: {
          pattern: String.raw`(?i)(ignore.{0,20}(previous|prior|above).{0,20}instructions|you are now|system:|forget everything|disregard)`,
        },
      },
      action: { decision: "deny" },
    },
  },
  {
    name: "block-credit-card",
    definition: {
      description: "Blocks credit card numbers in input",
      enabled: true,
      execution: "server",
      scope: { stages: ["pre"], stepTypes: ["llm"], stepNames: ["respond_to_customer"] },
      selector: { path: "input" },
      evaluator: {
        name: "regex",
        config: {
          pattern: String.raw`\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b`,
        },
      },
      action: { decision: "deny" },
    },
  },
  {
    name: "block-credit-card-in-output",
    definition: {
      description: "Blocks LLM responses containing credit card numbers",
      enabled: true,
      execution: "server",
      scope: { stages: ["post"], stepTypes: ["llm"], stepNames: ["respond_to_customer"] },
      selector: { path: "output" },
      evaluator: {
        name: "regex",
        config: {
          pattern: String.raw`\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b`,
        },
      },
      action: { decision: "deny" },
    },
  },
  {
    name: "block-sql-injection-lookup",
    definition: {
      description: "Blocks SQL injection in customer lookup tool",
      enabled: true,
      execution: "server",
      scope: {
        stages: ["pre"],
        stepTypes: ["tool"],
        stepNames: ["lookup_customer"],
      },
      selector: { path: "input" },
      evaluator: {
        name: "regex",
        config: {
          pattern: String.raw`(?i)(select|insert|update|delete|drop|union|--|;)`,
        },
      },
      action: { decision: "deny" },
    },
  },
  {
    name: "log-ticket-creation",
    definition: {
      description: "Logs all ticket creation for audit",
      enabled: true,
      execution: "server",
      scope: {
        stages: ["pre"],
        stepTypes: ["tool"],
        stepNames: ["create_ticket"],
      },
      selector: { path: "*" },
      evaluator: {
        name: "regex",
        config: { pattern: ".*" },
      },
      action: { decision: "log" },
    },
  },
];

async function main(): Promise<void> {
  console.log(`Setting up controls on ${serverUrl} ...`);

  const health = await client.system.healthCheck();
  console.log(`Server: ${health.status} (${health.version})`);

  // Register agent (steps are auto-registered when the agent app runs init() — same as Python)
  await client.agents.init({
    agent: {
      agentName,
      agentDescription: "TypeScript customer support agent demo",
    },
  });
  console.log(`Registered agent: ${agentName}`);

  // Create or reuse policy
  let policyId: number;
  try {
    const created = await client.policies.create({ name: policyName });
    policyId = created.policyId;
    console.log(`Created policy: ${policyName} (id=${policyId})`);
  } catch {
    const existing = await client.agents.getPolicy({ agentName });
    policyId = existing.policyId;
    console.log(`Reusing existing policy (id=${policyId})`);
  }

  // Assign policy to agent
  await client.agents.updatePolicy({ agentName, policyId });
  console.log(`Assigned policy to agent`);

  // Create controls and attach to policy
  let created = 0;
  for (const spec of DEMO_CONTROLS) {
    try {
      const result = await client.controls.create({ name: spec.name });
      const controlId = result.controlId;

      await client.controls.updateData({
        controlId,
        body: { data: spec.definition },
      });

      await client.policies.addControl({ policyId, controlId });
      created++;
      console.log(`  + ${spec.name} (id=${controlId})`);
    } catch {
      const list = await client.controls.list({ name: spec.name, limit: 1 });
      if (list.controls.length > 0) {
        const controlId = list.controls[0].id;
        await client.controls.updateData({
          controlId,
          body: { data: spec.definition },
        });
        try {
          await client.policies.addControl({ policyId, controlId });
        } catch {
          // already in policy
        }
        console.log(`  ~ ${spec.name} (id=${controlId}, updated)`);
      }
    }
  }

  console.log(
    `\nDone. ${created} control(s) created, ${DEMO_CONTROLS.length} total configured.`,
  );
}

main().catch((err: unknown) => {
  console.error("Setup failed:", err);
  process.exitCode = 1;
});

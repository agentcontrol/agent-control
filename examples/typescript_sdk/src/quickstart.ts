import { AgentControlClient, type ControlDefinitionInput } from "agent-control";

const serverUrl = process.env.AGENT_CONTROL_URL ?? "http://localhost:8000";
// This example creates, updates, and deletes controls, so use an admin key when auth is enabled.
const apiKey = process.env.AGENT_CONTROL_API_KEY;
const controlName = `ts-sdk-example-${Date.now()}`;

const client = new AgentControlClient();
client.init({
  agentName: "typescript-sdk-example",
  serverUrl,
  ...(apiKey ? { apiKey } : {}),
});

async function main(): Promise<void> {
  console.log(`Using server: ${serverUrl}`);

  const health = await client.system.healthCheck();
  console.log(`Health check: ${health.status} (${health.version})`);

  const existing = await client.controls.list({
    limit: 10,
    name: "ts-sdk-example-",
  });
  console.log(`Existing example controls: ${existing.controls.length}`);

  let createdControlId: number | null = null;
  try {
    const created = await client.controls.create({
      name: controlName,
    });
    createdControlId = created.controlId;
    console.log(`Created control: ${controlName} (id=${createdControlId})`);

    const controlData: ControlDefinitionInput = {
      action: { decision: "deny" },
      description: "Block SSN-like patterns in post-step output.",
      enabled: true,
      evaluator: {
        name: "regex",
        config: {
          pattern: "\\b\\d{3}-\\d{2}-\\d{4}\\b",
        },
      },
      execution: "server",
      scope: {
        stages: ["post"],
        stepTypes: ["llm"],
      },
      selector: {
        path: "output",
      },
      tags: ["example", "typescript", "npm"],
    };

    await client.controls.updateData({
      controlId: createdControlId,
      body: { data: controlData },
    });
    console.log("Configured control data.");

    const fetched = await client.controls.getData({
      controlId: createdControlId,
    });
    console.log(
      `Fetched control config: evaluator=${fetched.data.evaluator.name}, selector=${fetched.data.selector.path ?? "*"}`,
    );
  } finally {
    if (createdControlId !== null) {
      const deleted = await client.controls.delete({
        controlId: createdControlId,
      });
      console.log(`Cleanup delete success: ${deleted.success}`);
    }
  }
}

main().catch((error: unknown) => {
  console.error("TypeScript SDK example failed.", error);
  process.exitCode = 1;
});

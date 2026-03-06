import { AgentControlSDK } from "./generated/sdk/sdk";
import { mergeRegisteredSteps, type RegisteredStep } from "./_control_registry";

export type StepSchema = RegisteredStep;

export type APIKeyProvider = string | (() => Promise<string>);

export interface AgentControlInitOptions {
  /** Agent name; must be at least 10 characters and match [a-z0-9:_-] (after trim/lower). */
  agentName: string;
  agentId?: string;
  serverUrl: string;
  apiKey?: APIKeyProvider;
  steps?: StepSchema[];
  agentDescription?: string;
  agentVersion?: string;
  agentMetadata?: Record<string, unknown>;
  registerAgent?: boolean;
  timeoutMs?: number;
  userAgent?: string;
}

export type AgentsApi = AgentControlSDK["agents"];
export type ControlsApi = AgentControlSDK["controls"];
export type EvaluationApi = AgentControlSDK["evaluation"];
export type EvaluatorConfigsApi = AgentControlSDK["evaluatorConfigs"];
export type EvaluatorsApi = AgentControlSDK["evaluators"];
export type ObservabilityApi = AgentControlSDK["observability"];
export type PoliciesApi = AgentControlSDK["policies"];
export type SystemApi = AgentControlSDK["system"];

/** Match server agent name rule (models: AGENT_NAME_MIN_LENGTH, AGENT_NAME_PATTERN). */
const AGENT_NAME_MIN_LENGTH = 10;
const AGENT_NAME_PATTERN = /^[a-z0-9:_-]+$/;

function validateAgentName(name: string): string {
  const normalized = name.trim().toLowerCase();
  if (normalized.length < AGENT_NAME_MIN_LENGTH) {
    throw new Error(
      `agent_name must be at least ${AGENT_NAME_MIN_LENGTH} characters long`,
    );
  }
  if (!AGENT_NAME_PATTERN.test(normalized)) {
    throw new Error(
      "agent_name may only contain lowercase letters, digits, ':', '_' or '-'",
    );
  }
  return normalized;
}

export class AgentControlClient {
  private options: AgentControlInitOptions | null = null;
  private sdk: AgentControlSDK | null = null;

  async init(options: AgentControlInitOptions): Promise<void> {
    const agentName = validateAgentName(options.agentName);
    this.options = { ...options, agentName };
    this.sdk = new AgentControlSDK({
      serverURL: options.serverUrl,
      apiKeyHeader: options.apiKey,
      timeoutMs: options.timeoutMs,
      userAgent: options.userAgent,
    });
    if (options.registerAgent ?? true) {
      const steps = mergeRegisteredSteps(options.steps);
      await this.sdk.agents.init({
        agent: {
          agentName,
          agentDescription: options.agentDescription,
          agentVersion: options.agentVersion,
          agentMetadata: {
            ...(options.agentMetadata ?? {}),
            sdk_language: "typescript",
          },
        },
        steps: steps.length > 0 ? steps : undefined,
      });
    }
  }

  get initialized(): boolean {
    return this.sdk !== null;
  }

  get config(): AgentControlInitOptions | null {
    return this.options;
  }

  get agents(): AgentsApi {
    return this.requireSDK().agents;
  }

  get controls(): ControlsApi {
    return this.requireSDK().controls;
  }

  get evaluation(): EvaluationApi {
    return this.requireSDK().evaluation;
  }

  get evaluatorConfigs(): EvaluatorConfigsApi {
    return this.requireSDK().evaluatorConfigs;
  }

  get evaluators(): EvaluatorsApi {
    return this.requireSDK().evaluators;
  }

  get observability(): ObservabilityApi {
    return this.requireSDK().observability;
  }

  get policies(): PoliciesApi {
    return this.requireSDK().policies;
  }

  get system(): SystemApi {
    return this.requireSDK().system;
  }

  private requireSDK(): AgentControlSDK {
    if (!this.sdk) {
      throw new Error(
        "AgentControlClient is not initialized. Call init(...) before making API calls.",
      );
    }

    return this.sdk;
  }
}

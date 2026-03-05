import { AgentControlSDK } from "./generated/sdk/sdk";
import { mergeRegisteredSteps, type RegisteredStep } from "./_control_registry";

export type StepSchema = RegisteredStep;

export type APIKeyProvider = string | (() => Promise<string>);

export interface AgentControlInitOptions {
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

export class AgentControlClient {
  private options: AgentControlInitOptions | null = null;
  private sdk: AgentControlSDK | null = null;

  async init(options: AgentControlInitOptions): Promise<void> {
    this.options = { ...options };
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
          agentName: options.agentName,
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

export interface StepSchema {
  name: string;
  schema: Record<string, unknown>;
}

export interface AgentControlInitOptions {
  agentName: string;
  agentId?: string;
  serverUrl: string;
  apiKey?: string;
  steps?: StepSchema[];
}

/**
 * Minimal wrapper client scaffold for the Speakeasy-generated SDK.
 * Higher-level behavior is implemented in a later phase.
 */
export class AgentControlClient {
  private options: AgentControlInitOptions | null = null;

  init(options: AgentControlInitOptions): void {
    this.options = options;
  }

  get initialized(): boolean {
    return this.options !== null;
  }

  get config(): AgentControlInitOptions | null {
    return this.options;
  }
}

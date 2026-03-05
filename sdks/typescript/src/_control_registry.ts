export interface RegisteredStep {
  name: string;
  type: "llm" | "tool";
  description?: string;
  inputSchema?: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

const stepRegistry = new Map<string, RegisteredStep>();

function stepKey(step: Pick<RegisteredStep, "name" | "type">): string {
  return `${step.type}:${step.name}`;
}

export function registerStep(step: RegisteredStep): void {
  stepRegistry.set(stepKey(step), step);
}

export function getRegisteredSteps(): RegisteredStep[] {
  return [...stepRegistry.values()];
}

export function mergeRegisteredSteps(explicitSteps: RegisteredStep[] = []): RegisteredStep[] {
  const merged = new Map<string, RegisteredStep>();
  for (const step of getRegisteredSteps()) {
    merged.set(stepKey(step), step);
  }
  // Explicit steps should win over auto-discovered steps.
  for (const step of explicitSteps) {
    merged.set(stepKey(step), step);
  }
  return [...merged.values()];
}

/** @internal test helper */
export function _clearStepRegistry(): void {
  stepRegistry.clear();
}

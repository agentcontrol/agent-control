import type { AgentControlClient } from "./client";
import type { EvaluationResponse } from "./generated/models/evaluation-response";
import { ControlSteerError, ControlViolationError } from "./errors";
import { registerStep } from "./_control_registry";

// ---------------------------------------------------------------------------
// Internal state: holds a reference to the singleton (set by index.ts)
// ---------------------------------------------------------------------------

let _defaultClient: AgentControlClient | null = null;

/** @internal Called by index.ts to register the singleton. */
export function _registerDefaultClient(client: AgentControlClient): void {
  _defaultClient = client;
}

function requireClient(): AgentControlClient {
  if (!_defaultClient || !_defaultClient.initialized) {
    throw new Error(
      "AgentControlClient is not initialized. Call agentControl.init() before using control().",
    );
  }
  return _defaultClient;
}

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface ControlOptions {
  /** Explicit step name for control matching. Defaults to fn.name or "anonymous". */
  stepName?: string;
  /** Step type. Defaults to "llm". */
  type?: "llm" | "tool";
  /** Optional step description for registration/UI display. */
  description?: string;
  /** Optional JSON schema describing function input. */
  inputSchema?: Record<string, unknown>;
  /** Optional JSON schema describing function output. */
  outputSchema?: Record<string, unknown>;
  /** Optional custom metadata sent during step registration. */
  metadata?: Record<string, unknown>;
  /** Informational — server uses the agent's assigned policy automatically. */
  policy?: string;
}

export type AsyncFn<TArgs extends unknown[], TResult> = (...args: TArgs) => Promise<TResult>;

export interface GuardContext {
  name: string;
  type?: "llm" | "tool";
  input: unknown;
}

export interface CheckStep {
  name: string;
  type?: "llm" | "tool";
  input: unknown;
  output?: unknown;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function extractInput(args: unknown[]): unknown {
  if (args.length === 0) return null;
  if (args.length === 1) return args[0];
  return args;
}

async function callEvaluate(
  client: AgentControlClient,
  agentName: string,
  stage: "pre" | "post",
  step: { name: string; type: string; input: unknown; output?: unknown },
): Promise<EvaluationResponse> {
  return client.evaluation.evaluate({
    body: {
      agentName,
      stage,
      step: {
        name: step.name,
        type: step.type,
        input: step.input,
        output: step.output ?? null,
      },
    },
  });
}

/**
 * Inspect an EvaluationResponse and throw on deny/steer, warn/log otherwise.
 *
 * Priority order (matches Python SDK):
 *   1. Errors  → throw (evaluation infra failure)
 *   2. Deny    → throw ControlViolationError
 *   3. Steer   → throw ControlSteerError
 *   4. Warn    → console.warn (non-blocking)
 *   5. Log     → console.log  (non-blocking)
 */
function handleResult(result: EvaluationResponse): void {
  if (result.errors?.length) {
    const messages = result.errors
      .map(
        (e) => `[${e.controlName}] ${e.result.message ?? e.result.error ?? "Unknown error"}`,
      )
      .join("; ");
    throw new Error(`Control evaluation failed: ${messages}`);
  }

  if (!result.isSafe && result.matches) {
    for (const match of result.matches) {
      if (match.action === "deny") {
        throw new ControlViolationError({
          controlName: match.controlName,
          controlId: String(match.controlId),
          action: "deny",
          evaluationResult: {
            isSafe: false,
            reason: match.result.message ?? undefined,
          },
          message: match.result.message ?? `Control violation: ${match.controlName}`,
        });
      }
    }

    for (const match of result.matches) {
      if (match.action === "steer") {
        throw new ControlSteerError({
          controlName: match.controlName,
          controlId: String(match.controlId),
          steeringContext: match.steeringContext?.message,
          message: match.result.message ?? `Control steering required: ${match.controlName}`,
        });
      }
    }
  }

  if (result.matches) {
    for (const match of result.matches) {
      if (match.action === "warn") {
        console.warn(
          `[AgentControl] Control [${match.controlName}]: ${match.result.message ?? "triggered"}`,
        );
      } else if (match.action === "log") {
        console.log(
          `[AgentControl] Control [${match.controlName}]: ${match.result.message ?? "triggered"}`,
        );
      }
    }
  }
}

/**
 * Run pre-check (fail-closed) and post-check (fail-open for infra errors,
 * but deny/steer still block) around an async operation.
 */
async function withChecks<T>(
  client: AgentControlClient,
  agentName: string,
  step: { name: string; type: string; input: unknown },
  execute: () => Promise<T>,
): Promise<T> {
  // Pre-check — fail-closed: any error blocks execution
  try {
    const preResult = await callEvaluate(client, agentName, "pre", step);
    handleResult(preResult);
  } catch (err) {
    if (err instanceof ControlViolationError || err instanceof ControlSteerError) {
      throw err;
    }
    throw new Error(
      `Pre-execution control check failed. Execution blocked for safety. ` +
        `Error: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  const output = await execute();

  // Post-check — deny/steer still block, infra errors are logged
  try {
    const postResult = await callEvaluate(client, agentName, "post", {
      ...step,
      output,
    });
    handleResult(postResult);
  } catch (err) {
    if (err instanceof ControlViolationError || err instanceof ControlSteerError) {
      throw err;
    }
    console.error("[AgentControl] Post-execution check failed:", err);
  }

  return output;
}

// ---------------------------------------------------------------------------
// control()  — Higher-order function wrapper
// ---------------------------------------------------------------------------

/**
 * Wrap an async function with pre/post evaluation checks.
 *
 * ```ts
 * const chat = control(async (message: string) => {
 *   return await assistant.respond(message);
 * }, { stepName: "chat" });
 * ```
 */
export function control<TArgs extends unknown[], TResult>(
  fn: AsyncFn<TArgs, TResult>,
  options?: ControlOptions,
): AsyncFn<TArgs, TResult>;

/**
 * Wrap an async function with pre/post evaluation checks (name-first overload).
 *
 * ```ts
 * const chat = control("chat", async (message: string) => {
 *   return await assistant.respond(message);
 * });
 * ```
 */
export function control<TArgs extends unknown[], TResult>(
  name: string,
  fn: AsyncFn<TArgs, TResult>,
  options?: ControlOptions,
): AsyncFn<TArgs, TResult>;

export function control<TArgs extends unknown[], TResult>(
  fnOrName: AsyncFn<TArgs, TResult> | string,
  fnOrOptions?: AsyncFn<TArgs, TResult> | ControlOptions,
  maybeOptions?: ControlOptions,
): AsyncFn<TArgs, TResult> {
  let fn: AsyncFn<TArgs, TResult>;
  let opts: ControlOptions;

  if (typeof fnOrName === "string") {
    fn = fnOrOptions as AsyncFn<TArgs, TResult>;
    opts = { ...maybeOptions, stepName: fnOrName };
  } else {
    fn = fnOrName;
    opts = (fnOrOptions as ControlOptions | undefined) ?? {};
  }

  const stepName = opts.stepName ?? (fn.name || "anonymous");
  const stepType = opts.type ?? "llm";
  registerStep({
    name: stepName,
    type: stepType,
    description: opts.description,
    inputSchema: opts.inputSchema,
    outputSchema: opts.outputSchema,
    metadata: opts.metadata,
  });

  const wrapped = async (...args: TArgs): Promise<TResult> => {
    const client = requireClient();
    const { agentName } = client.config!;

    return withChecks(
      client,
      agentName,
      { name: stepName, type: stepType, input: extractInput(args) },
      () => fn(...args),
    );
  };

  Object.defineProperty(wrapped, "name", { value: stepName });
  return wrapped;
}

// ---------------------------------------------------------------------------
// guard()  — Inline one-off protection
// ---------------------------------------------------------------------------

/**
 * Guard a single async expression with pre/post evaluation checks.
 *
 * ```ts
 * const result = await guard(
 *   { name: "chat", input: userMessage },
 *   async () => assistant.respond(userMessage),
 * );
 * ```
 */
export async function guard<T>(context: GuardContext, fn: () => Promise<T>): Promise<T> {
  const client = requireClient();
  const { agentName } = client.config!;

  return withChecks(
    client,
    agentName,
    { name: context.name, type: context.type ?? "llm", input: context.input },
    fn,
  );
}

// ---------------------------------------------------------------------------
// check()  — Explicit pre/post check (escape hatch)
// ---------------------------------------------------------------------------

/**
 * Run an explicit evaluation check without wrapping a function.
 *
 * ```ts
 * await check("pre",  { name: "chat", input: userMessage });
 * const result = await assistant.respond(userMessage);
 * await check("post", { name: "chat", input: userMessage, output: result });
 * ```
 *
 * Throws ControlViolationError / ControlSteerError on deny/steer.
 */
export async function check(stage: "pre" | "post", step: CheckStep): Promise<EvaluationResponse> {
  const client = requireClient();
  const { agentName } = client.config!;

  const result = await callEvaluate(client, agentName, stage, {
    name: step.name,
    type: step.type ?? "llm",
    input: step.input,
    output: step.output,
  });
  handleResult(result);
  return result;
}

export type ControlAction = "allow" | "deny" | "steer" | "warn" | "log";

export interface EvaluationResult {
  isSafe: boolean;
  reason?: string;
}

export class ControlViolationError extends Error {
  readonly controlName: string;
  readonly controlId: string;
  readonly action: ControlAction;
  readonly evaluationResult: EvaluationResult;

  constructor(params: {
    controlName: string;
    controlId: string;
    action: ControlAction;
    evaluationResult: EvaluationResult;
    message?: string;
  }) {
    super(params.message ?? `Control violation: ${params.controlName}`);
    this.name = "ControlViolationError";
    this.controlName = params.controlName;
    this.controlId = params.controlId;
    this.action = params.action;
    this.evaluationResult = params.evaluationResult;
  }
}

export class ControlSteerError extends Error {
  readonly controlName: string;
  readonly controlId: string;
  readonly steeringContext: string;

  constructor(params: {
    controlName: string;
    controlId: string;
    steeringContext?: string;
    message?: string;
  }) {
    super(params.message ?? `Control steering required: ${params.controlName}`);
    this.name = "ControlSteerError";
    this.controlName = params.controlName;
    this.controlId = params.controlId;
    this.steeringContext = params.steeringContext ?? "No steering context provided";
  }
}

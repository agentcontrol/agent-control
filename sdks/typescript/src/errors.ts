export type ControlAction = "allow" | "deny";

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

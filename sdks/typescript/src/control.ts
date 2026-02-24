export interface ControlOptions {
  policy?: string;
}

export type AsyncFn<TArgs extends unknown[], TResult> = (...args: TArgs) => Promise<TResult>;

/**
 * Minimal no-op control wrapper scaffold.
 * Evaluation integration lands in a later phase.
 */
export function control<TArgs extends unknown[], TResult>(
  fn: AsyncFn<TArgs, TResult>,
  _options?: ControlOptions,
): AsyncFn<TArgs, TResult> {
  void _options;
  return async (...args: TArgs): Promise<TResult> => fn(...args);
}

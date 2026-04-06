import type { JsonSchema } from '@/core/page-components/agent-detail/modals/edit-control/types';

/**
 * Control JSON Schema used by the Playwright harness for JsonEditorCodeMirror.
 * Aligned with mock control schema in ui/tests/fixtures.ts.
 */
export const HARNESS_CONTROL_SCHEMA: JsonSchema = {
  $defs: {
    ControlSelector: {
      type: 'object',
      properties: {
        path: {
          anyOf: [{ type: 'string' }, { type: 'null' }],
          default: '*',
          examples: ['output', 'context.user_id', '*'],
        },
      },
    },
    EvaluatorSpec: {
      type: 'object',
      required: ['name', 'config'],
      properties: {
        name: {
          type: 'string',
          examples: ['regex', 'list'],
        },
        config: {
          type: 'object',
          additionalProperties: true,
        },
      },
    },
    ConditionNode: {
      type: 'object',
      properties: {
        selector: {
          anyOf: [{ $ref: '#/$defs/ControlSelector' }, { type: 'null' }],
        },
        evaluator: {
          anyOf: [{ $ref: '#/$defs/EvaluatorSpec' }, { type: 'null' }],
        },
        and: {
          anyOf: [
            { type: 'array', items: { $ref: '#/$defs/ConditionNode' } },
            { type: 'null' },
          ],
        },
        or: {
          anyOf: [
            { type: 'array', items: { $ref: '#/$defs/ConditionNode' } },
            { type: 'null' },
          ],
        },
        not: {
          anyOf: [{ $ref: '#/$defs/ConditionNode' }, { type: 'null' }],
        },
      },
    },
    ControlScope: {
      type: 'object',
      properties: {
        step_types: {
          anyOf: [
            { type: 'array', items: { type: 'string' } },
            { type: 'null' },
          ],
        },
        step_names: {
          anyOf: [
            { type: 'array', items: { type: 'string' } },
            { type: 'null' },
          ],
        },
        step_name_regex: { anyOf: [{ type: 'string' }, { type: 'null' }] },
        stages: {
          anyOf: [
            {
              type: 'array',
              items: { type: 'string', enum: ['pre', 'post'] },
            },
            { type: 'null' },
          ],
        },
      },
    },
    SteeringContext: {
      type: 'object',
      required: ['message'],
      properties: {
        message: { type: 'string' },
      },
    },
    ControlAction: {
      type: 'object',
      required: ['decision'],
      properties: {
        decision: {
          type: 'string',
          enum: ['allow', 'deny', 'steer', 'warn', 'log'],
        },
        steering_context: {
          anyOf: [{ $ref: '#/$defs/SteeringContext' }, { type: 'null' }],
        },
      },
    },
  },
  type: 'object',
  required: ['execution', 'condition', 'action'],
  properties: {
    description: {
      anyOf: [{ type: 'string' }, { type: 'null' }],
    },
    enabled: { type: 'boolean' },
    execution: { type: 'string', enum: ['server', 'sdk'] },
    scope: {
      $ref: '#/$defs/ControlScope',
    },
    condition: {
      $ref: '#/$defs/ConditionNode',
    },
    action: {
      $ref: '#/$defs/ControlAction',
    },
    tags: {
      type: 'array',
      items: { type: 'string' },
    },
  },
};

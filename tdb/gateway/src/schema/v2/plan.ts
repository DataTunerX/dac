import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { JsonValueSchema, UuidSchema } from './shared.js';

const PlanStepSchema = Type.Object({
  id: Type.String({ minLength: 1, maxLength: 120 }),
  op: Type.String({ minLength: 1, maxLength: 120 }),
  args: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  save_as: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })),
  when: Type.Optional(Type.String({ minLength: 1, maxLength: 300 })),
  on_error: Type.Optional(Type.Union([Type.Literal('fail'), Type.Literal('continue')])),
  timeout_ms: Type.Optional(Type.Integer({ minimum: 1, maximum: 120000 }))
});

export const PlanExecuteRequestSchema = Type.Object({
  version: Type.Literal('tdb.queryplan.v2'),
  execution_mode: Type.Optional(Type.Union([Type.Literal('safe'), Type.Literal('best_effort')])),
  goal: Type.Optional(Type.String({ minLength: 1, maxLength: 2000 })),
  context: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  steps: Type.Array(PlanStepSchema, { minItems: 1, maxItems: 500 })
});

const PlanDiagnosticSchema = Type.Object({
  level: Type.Union([Type.Literal('error'), Type.Literal('warning')]),
  code: Type.String(),
  message: Type.String(),
  step_id: Type.Optional(Type.String()),
  op: Type.Optional(Type.String()),
  details: Type.Optional(JsonValueSchema)
});

const PlanStepInspectionSchema = Type.Object({
  id: Type.String(),
  op: Type.String(),
  supported: Type.Boolean(),
  mutating: Type.Boolean(),
  save_as: Type.Optional(Type.String()),
  on_error: Type.Union([Type.Literal('fail'), Type.Literal('continue')]),
  timeout_ms: Type.Optional(Type.Integer({ minimum: 1 })),
  template_refs: Type.Array(Type.String()),
  context_dependencies: Type.Array(Type.String()),
  var_dependencies: Type.Array(Type.String()),
  args_preview: Type.Optional(JsonValueSchema),
  when_preview: Type.Optional(Type.String())
});

export const PlanValidateResponseSchema = Type.Object({
  valid: Type.Boolean(),
  execution_mode: Type.Union([Type.Literal('safe'), Type.Literal('best_effort')]),
  step_count: Type.Integer({ minimum: 0 }),
  mutating_step_count: Type.Integer({ minimum: 0 }),
  diagnostics: Type.Array(PlanDiagnosticSchema),
  steps: Type.Array(PlanStepInspectionSchema)
});

const PlanStepResultSchema = Type.Object({
  id: Type.String(),
  op: Type.String(),
  ok: Type.Boolean(),
  skipped: Type.Optional(Type.Boolean()),
  dry_run_skipped: Type.Optional(Type.Boolean()),
  would_mutate: Type.Optional(Type.Boolean()),
  duration_ms: Type.Integer({ minimum: 0 }),
  args_preview: Type.Optional(JsonValueSchema),
  response: Type.Optional(JsonValueSchema),
  error: Type.Optional(
    Type.Object({
      code: Type.String(),
      message: Type.String(),
      details: Type.Optional(JsonValueSchema)
    })
  )
});

const PlanStepTraceSchema = Type.Object({
  id: Type.String(),
  op: Type.String(),
  status: Type.Union([
    Type.Literal('executed'),
    Type.Literal('skipped'),
    Type.Literal('dry_run_skipped'),
    Type.Literal('failed')
  ]),
  mutating: Type.Boolean(),
  save_as: Type.Optional(Type.String()),
  when: Type.Optional(Type.String()),
  when_result: Type.Optional(Type.Boolean()),
  vars_before: Type.Record(Type.String(), JsonValueSchema),
  vars_after: Type.Record(Type.String(), JsonValueSchema),
  args_resolved: Type.Optional(JsonValueSchema),
  saved_value_preview: Type.Optional(JsonValueSchema),
  duration_ms: Type.Integer({ minimum: 0 }),
  started_at: Type.String({ format: 'date-time' }),
  finished_at: Type.String({ format: 'date-time' }),
  error: Type.Optional(
    Type.Object({
      code: Type.String(),
      message: Type.String(),
      details: Type.Optional(JsonValueSchema)
    })
  )
});

export const PlanExecuteResponseSchema = Type.Object({
  plan_id: Type.String({ format: 'uuid' }),
  success: Type.Boolean(),
  execution_mode: Type.Union([Type.Literal('safe'), Type.Literal('best_effort')]),
  started_at: Type.String({ format: 'date-time' }),
  finished_at: Type.String({ format: 'date-time' }),
  results: Type.Array(PlanStepResultSchema),
  vars: Type.Record(Type.String(), JsonValueSchema)
});

export const PlanExplainResponseSchema = Type.Composite([
  PlanValidateResponseSchema,
  Type.Object({
    plan_id: Type.String({ format: 'uuid' }),
    goal: Type.Optional(Type.String())
  })
]);

export const PlanDryRunResponseSchema = Type.Composite([
  PlanExecuteResponseSchema,
  Type.Object({
    dry_run: Type.Literal(true),
    diagnostics: Type.Array(PlanDiagnosticSchema)
  })
]);

export const PlanReplayResponseSchema = Type.Composite([
  PlanExecuteResponseSchema,
  Type.Object({
    replay: Type.Literal(true),
    replay_of_plan_id: Type.Optional(UuidSchema),
    trace: Type.Array(PlanStepTraceSchema)
  })
]);

export const PlanRunGetQuerySchema = Type.Object({
  plan_id: UuidSchema
});

export const PlanRunListQuerySchema = Type.Object({
  execution_kind: Type.Optional(
    Type.Union([Type.Literal('execute'), Type.Literal('dry_run'), Type.Literal('replay')])
  ),
  success: Type.Optional(Type.Boolean()),
  goal_q: Type.Optional(Type.String({ minLength: 1, maxLength: 2000 })),
  replay_of_plan_id: Type.Optional(UuidSchema),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 }))
});

export const PlanReplayByIdRequestSchema = Type.Object({
  plan_id: UuidSchema
});

const PlanRunRecordSchema = Type.Object({
  plan_id: UuidSchema,
  execution_kind: Type.Union([
    Type.Literal('execute'),
    Type.Literal('dry_run'),
    Type.Literal('replay')
  ]),
  replay_of_plan_id: Type.Optional(UuidSchema),
  goal: Type.String(),
  execution_mode: Type.Union([Type.Literal('safe'), Type.Literal('best_effort')]),
  success: Type.Boolean(),
  started_at: Type.String({ format: 'date-time' }),
  finished_at: Type.String({ format: 'date-time' }),
  created_at: Type.String({ format: 'date-time' })
});

export const PlanRunGetResponseSchema = Type.Object({
  run: PlanRunRecordSchema,
  request: PlanExecuteRequestSchema,
  response: JsonValueSchema,
  trace: Type.Array(PlanStepTraceSchema)
});

export const PlanRunListResponseSchema = Type.Object({
  execution_kind_filter: Type.Optional(
    Type.Union([Type.Literal('execute'), Type.Literal('dry_run'), Type.Literal('replay')])
  ),
  success_filter: Type.Optional(Type.Boolean()),
  goal_q_filter: Type.Optional(Type.String()),
  replay_of_plan_id_filter: Type.Optional(UuidSchema),
  limit: Type.Integer({ minimum: 1 }),
  count: Type.Integer({ minimum: 0 }),
  runs: Type.Array(PlanRunRecordSchema)
});

export const PlanExecuteRouteSchema = {
  tags: ['plan'],
  body: PlanExecuteRequestSchema,
  response: {
    200: PlanExecuteResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const PlanValidateRouteSchema = {
  tags: ['plan'],
  body: PlanExecuteRequestSchema,
  response: {
    200: PlanValidateResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const PlanExplainRouteSchema = {
  tags: ['plan'],
  body: PlanExecuteRequestSchema,
  response: {
    200: PlanExplainResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const PlanDryRunRouteSchema = {
  tags: ['plan'],
  body: PlanExecuteRequestSchema,
  response: {
    200: PlanDryRunResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const PlanReplayRouteSchema = {
  tags: ['plan'],
  body: PlanExecuteRequestSchema,
  response: {
    200: PlanReplayResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const PlanRunGetRouteSchema = {
  tags: ['plan'],
  querystring: PlanRunGetQuerySchema,
  response: {
    200: PlanRunGetResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const PlanRunListRouteSchema = {
  tags: ['plan'],
  querystring: PlanRunListQuerySchema,
  response: {
    200: PlanRunListResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const PlanReplayByIdRouteSchema = {
  tags: ['plan'],
  body: PlanReplayByIdRequestSchema,
  response: {
    200: PlanReplayResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

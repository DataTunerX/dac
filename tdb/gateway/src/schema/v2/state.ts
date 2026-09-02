import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { AsOfQuerySchema, JsonValueSchema, TimestampSchema, UuidSchema } from './shared.js';

export const PropertyUpsertRequestSchema = Type.Object({
  object_id: UuidSchema,
  key: Type.String({ minLength: 1, maxLength: 200 }),
  value: Type.Record(Type.String(), JsonValueSchema),
  valid_from: TimestampSchema,
  system_from: Type.Optional(TimestampSchema),
  source_event_id: Type.Optional(UuidSchema),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 }))
});

export const PropertyRecordSchema = Type.Object({
  property_state_id: UuidSchema,
  object_id: UuidSchema,
  key: Type.String(),
  value: Type.Record(Type.String(), JsonValueSchema),
  valid_from: TimestampSchema,
  valid_to: Type.Optional(TimestampSchema),
  system_from: TimestampSchema,
  system_to: Type.Optional(TimestampSchema),
  source_event_id: Type.Optional(UuidSchema),
  confidence: Type.Optional(Type.Number())
});

export const PropertyAsOfQuerySchema = Type.Intersect([
  Type.Object({
    object_id: UuidSchema,
    key: Type.String({ minLength: 1, maxLength: 200 })
  }),
  AsOfQuerySchema
]);

export const PropertyDiffQuerySchema = Type.Object({
  object_id: UuidSchema,
  key: Type.String({ minLength: 1, maxLength: 200 }),
  from_valid_time: TimestampSchema,
  to_valid_time: TimestampSchema,
  from_system_time: Type.Optional(TimestampSchema),
  to_system_time: Type.Optional(TimestampSchema)
});

export const PropertyWhyQuerySchema = Type.Intersect([
  PropertyAsOfQuerySchema,
  Type.Object({
    candidate_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 }))
  })
]);

export const PropertyUpsertRouteSchema = {
  tags: ['state'],
  body: PropertyUpsertRequestSchema,
  response: {
    201: PropertyRecordSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const PropertyAsOfRouteSchema = {
  tags: ['state'],
  querystring: PropertyAsOfQuerySchema,
  response: {
    200: Type.Object({
      property: Type.Optional(PropertyRecordSchema)
    }),
    400: ErrorSchema,
    409: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const PropertyDiffRouteSchema = {
  tags: ['state'],
  querystring: PropertyDiffQuerySchema,
  response: {
    200: Type.Object({
      object_id: UuidSchema,
      key: Type.String(),
      from: Type.Object({
        valid_time: TimestampSchema,
        system_time: TimestampSchema,
        property: Type.Optional(PropertyRecordSchema)
      }),
      to: Type.Object({
        valid_time: TimestampSchema,
        system_time: TimestampSchema,
        property: Type.Optional(PropertyRecordSchema)
      }),
      changed: Type.Boolean(),
      change_type: Type.Union([
        Type.Literal('none'),
        Type.Literal('added'),
        Type.Literal('removed'),
        Type.Literal('updated')
      ])
    }),
    400: ErrorSchema,
    409: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const PropertyWhyRouteSchema = {
  tags: ['state'],
  querystring: PropertyWhyQuerySchema,
  response: {
    200: Type.Object({
      object_id: UuidSchema,
      key: Type.String(),
      as_of_valid_time: TimestampSchema,
      as_of_system_time: TimestampSchema,
      selected: Type.Optional(PropertyRecordSchema),
      explanation: Type.Object({
        outcome: Type.Union([Type.Literal('selected'), Type.Literal('not_found')]),
        summary: Type.String(),
        selected_reason_codes: Type.Array(Type.String()),
        diagnostics: Type.Array(Type.String()),
        eligible_candidate_count: Type.Integer({ minimum: 0 }),
        candidate_limit: Type.Integer({ minimum: 1 })
      }),
      candidates: Type.Array(
        Type.Object({
          property: PropertyRecordSchema,
          matched_valid_time: Type.Boolean(),
          matched_system_time: Type.Boolean(),
          eligible: Type.Boolean(),
          selected: Type.Boolean(),
          reason_codes: Type.Array(Type.String())
        })
      )
    }),
    400: ErrorSchema,
    409: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const EdgeUpsertRequestSchema = Type.Object({
  src_id: UuidSchema,
  predicate: Type.String({ minLength: 1, maxLength: 200 }),
  dst_id: UuidSchema,
  valid_from: TimestampSchema,
  system_from: Type.Optional(TimestampSchema),
  source_event_id: Type.Optional(UuidSchema),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 }))
});

export const EdgeRecordSchema = Type.Object({
  edge_state_id: UuidSchema,
  src_id: UuidSchema,
  predicate: Type.String(),
  dst_id: UuidSchema,
  valid_from: TimestampSchema,
  valid_to: Type.Optional(TimestampSchema),
  system_from: TimestampSchema,
  system_to: Type.Optional(TimestampSchema),
  source_event_id: Type.Optional(UuidSchema),
  confidence: Type.Optional(Type.Number())
});

export const EdgeAsOfQuerySchema = Type.Intersect([
  Type.Object({
    src_id: UuidSchema,
    predicate: Type.Optional(Type.String({ minLength: 1, maxLength: 200 }))
  }),
  AsOfQuerySchema
]);

export const EdgeDiffQuerySchema = Type.Object({
  src_id: UuidSchema,
  predicate: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
  from_valid_time: TimestampSchema,
  to_valid_time: TimestampSchema,
  from_system_time: Type.Optional(TimestampSchema),
  to_system_time: Type.Optional(TimestampSchema)
});

export const EdgeUpsertRouteSchema = {
  tags: ['state'],
  body: EdgeUpsertRequestSchema,
  response: {
    201: EdgeRecordSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const EdgeAsOfRouteSchema = {
  tags: ['state'],
  querystring: EdgeAsOfQuerySchema,
  response: {
    200: Type.Object({
      edges: Type.Array(EdgeRecordSchema)
    }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const EdgeDiffRouteSchema = {
  tags: ['state'],
  querystring: EdgeDiffQuerySchema,
  response: {
    200: Type.Object({
      src_id: UuidSchema,
      predicate: Type.Optional(Type.String()),
      from: Type.Object({
        valid_time: TimestampSchema,
        system_time: TimestampSchema,
        edges: Type.Array(EdgeRecordSchema)
      }),
      to: Type.Object({
        valid_time: TimestampSchema,
        system_time: TimestampSchema,
        edges: Type.Array(EdgeRecordSchema)
      }),
      changed: Type.Boolean(),
      added: Type.Array(EdgeRecordSchema),
      removed: Type.Array(EdgeRecordSchema)
    }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

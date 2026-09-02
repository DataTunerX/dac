import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { JsonValueSchema, TimestampSchema, UuidSchema } from './shared.js';

const EntityStatusSchema = Type.Union([
  Type.Literal('active'),
  Type.Literal('inactive'),
  Type.Literal('deleted')
]);

export const EntityUpsertRequestSchema = Type.Object({
  entity_id: Type.Optional(UuidSchema),
  entity_type: Type.String({ minLength: 1, maxLength: 120 }),
  display_name: Type.String({ minLength: 1, maxLength: 400 }),
  external_refs: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  status: Type.Optional(EntityStatusSchema)
});

export const EntitySchema = Type.Object({
  entity_id: UuidSchema,
  entity_type: Type.String(),
  display_name: Type.String(),
  external_refs: Type.Record(Type.String(), JsonValueSchema),
  status: EntityStatusSchema,
  created_at: TimestampSchema,
  updated_at: TimestampSchema
});

export const EntityGetQuerySchema = Type.Object({
  entity_id: UuidSchema
});

export const EntityListQuerySchema = Type.Object({
  entity_type: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })),
  status: Type.Optional(EntityStatusSchema),
  q: Type.Optional(Type.String({ minLength: 1, maxLength: 400 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const EntityUpsertRouteSchema = {
  tags: ['entity'],
  body: EntityUpsertRequestSchema,
  response: {
    201: EntitySchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const EntityGetRouteSchema = {
  tags: ['entity'],
  querystring: EntityGetQuerySchema,
  response: {
    200: Type.Object({
      entity: Type.Optional(EntitySchema)
    }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const EntityListRouteSchema = {
  tags: ['entity'],
  querystring: EntityListQuerySchema,
  response: {
    200: Type.Object({
      entities: Type.Array(EntitySchema)
    }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { JsonValueSchema, UuidSchema } from './shared.js';

export const SearchQueryRequestSchema = Type.Object({
  query: Type.String({ minLength: 1 }),
  domain: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
  case_id: Type.Optional(UuidSchema),
  stream_id: Type.Optional(Type.String({ minLength: 1, maxLength: 300 })),
  stream_ids: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 300 }), { minItems: 1 })),
  mode: Type.Optional(Type.Union([Type.Literal('lexical'), Type.Literal('vector'), Type.Literal('hybrid')])),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 30 })),
  query_embedding: Type.Optional(Type.Array(Type.Number())),
  alpha: Type.Optional(Type.Number({ minimum: 0, maximum: 1, default: 0.7 })),
  stream_prefix: Type.Optional(Type.Boolean({ default: false }))
});

export const SearchHitSchema = Type.Object({
  doc_id: UuidSchema,
  case_id: UuidSchema,
  stream_id: Type.Optional(Type.String()),
  event_id: UuidSchema,
  event_seq: Type.Integer({ minimum: 1 }),
  content: Type.String(),
  metadata: Type.Record(Type.String(), JsonValueSchema),
  lexical_score: Type.Number(),
  vector_score: Type.Number(),
  hybrid_score: Type.Number()
});

export const SearchDomainStreamBindingSchema = Type.Object({
  binding_id: Type.String({ minLength: 1 }),
  domain: Type.String({ minLength: 1 }),
  stream_id: Type.String({ minLength: 1 }),
  status: Type.String({ minLength: 1 }),
  binding_kind: Type.String({ minLength: 1 }),
  source: Type.String({ minLength: 1 }),
  priority: Type.Integer(),
  created_at: Type.String({ minLength: 1 }),
  updated_at: Type.String({ minLength: 1 })
});

export const SearchDomainStreamBindingUpsertRequestSchema = Type.Object({
  domain: Type.String({ minLength: 1, maxLength: 200 }),
  stream_id: Type.String({ minLength: 1, maxLength: 300 }),
  status: Type.Optional(Type.Union([Type.Literal('active'), Type.Literal('inactive')])),
  binding_kind: Type.Optional(
    Type.Union([
      Type.Literal('primary'),
      Type.Literal('auxiliary'),
      Type.Literal('eval'),
      Type.Literal('debug')
    ])
  ),
  source: Type.Optional(Type.String({ minLength: 1, maxLength: 100 })),
  priority: Type.Optional(Type.Integer({ minimum: 1, maximum: 100000, default: 100 }))
});

export const SearchDomainStreamBindingListQuerySchema = Type.Object({
  domain: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
  stream_id: Type.Optional(Type.String({ minLength: 1, maxLength: 300 })),
  status: Type.Optional(Type.Union([Type.Literal('active'), Type.Literal('inactive')])),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500, default: 100 }))
});

export const SearchQueryResponseSchema = Type.Object({
  query: Type.String(),
  resolved_stream_ids: Type.Array(Type.String()),
  hits: Type.Array(SearchHitSchema)
});

export const SearchQueryRouteSchema = {
  tags: ['search'],
  body: SearchQueryRequestSchema,
  response: {
    200: SearchQueryResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const SearchDomainStreamBindingUpsertRouteSchema = {
  tags: ['search'],
  body: SearchDomainStreamBindingUpsertRequestSchema,
  response: {
    201: SearchDomainStreamBindingSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const SearchDomainStreamBindingListRouteSchema = {
  tags: ['search'],
  querystring: SearchDomainStreamBindingListQuerySchema,
  response: {
    200: Type.Object({ bindings: Type.Array(SearchDomainStreamBindingSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

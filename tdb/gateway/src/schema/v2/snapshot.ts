import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { JsonValueSchema, TimestampSchema, UuidSchema } from './shared.js';

export const SnapshotWriteRequestSchema = Type.Object({
  case_id: UuidSchema,
  event_seq: Type.Integer({ minimum: 1 }),
  projection_version: Type.String({ minLength: 1, maxLength: 100 }),
  state_blob: Type.Record(Type.String(), JsonValueSchema),
  state_hash: Type.Optional(Type.String({ maxLength: 256 }))
});

export const SnapshotSchema = Type.Object({
  snapshot_id: UuidSchema,
  case_id: UuidSchema,
  event_seq: Type.Integer({ minimum: 1 }),
  projection_version: Type.String(),
  state_blob: Type.Record(Type.String(), JsonValueSchema),
  state_hash: Type.Optional(Type.String()),
  created_at: TimestampSchema
});

export const SnapshotLatestQuerySchema = Type.Object({
  case_id: UuidSchema,
  projection_version: Type.String({ minLength: 1, maxLength: 100 }),
  target_seq: Type.Integer({ minimum: 1 })
});

export const SnapshotWriteRouteSchema = {
  tags: ['snapshot'],
  body: SnapshotWriteRequestSchema,
  response: { 201: SnapshotSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const SnapshotLatestRouteSchema = {
  tags: ['snapshot'],
  querystring: SnapshotLatestQuerySchema,
  response: {
    200: Type.Object({ snapshot: Type.Optional(SnapshotSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

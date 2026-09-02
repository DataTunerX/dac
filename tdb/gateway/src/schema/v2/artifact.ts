import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { TimestampSchema, UuidSchema } from './shared.js';

export const ArtifactCreateRequestSchema = Type.Object({
  artifact_type: Type.String({ minLength: 1, maxLength: 120 }),
  name: Type.String({ minLength: 1, maxLength: 300 }),
  description: Type.Optional(Type.String({ maxLength: 4000 }))
});

export const ArtifactSchema = Type.Object({
  artifact_id: UuidSchema,
  artifact_type: Type.String(),
  name: Type.String(),
  description: Type.Optional(Type.String()),
  created_at: TimestampSchema
});

export const ArtifactCreateRouteSchema = {
  tags: ['artifact'],
  body: ArtifactCreateRequestSchema,
  response: {
    201: ArtifactSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const ArtifactVersionCreateRequestSchema = Type.Object({
  artifact_id: UuidSchema,
  version_number: Type.Integer({ minimum: 1 }),
  status: Type.String({ minLength: 1, maxLength: 50 }),
  valid_from: TimestampSchema,
  valid_to: Type.Optional(TimestampSchema),
  content_ref: Type.String({ minLength: 1, maxLength: 2000 }),
  content_hash: Type.Optional(Type.String({ maxLength: 256 })),
  author_id: Type.Optional(UuidSchema),
  approver_id: Type.Optional(UuidSchema),
  system_from: Type.Optional(TimestampSchema)
});

export const ArtifactVersionSchema = Type.Object({
  artifact_version_id: UuidSchema,
  artifact_id: UuidSchema,
  version_number: Type.Integer({ minimum: 1 }),
  status: Type.String(),
  valid_from: TimestampSchema,
  valid_to: Type.Optional(TimestampSchema),
  system_from: TimestampSchema,
  system_to: Type.Optional(TimestampSchema),
  content_ref: Type.String(),
  content_hash: Type.Optional(Type.String()),
  author_id: Type.Optional(UuidSchema),
  approver_id: Type.Optional(UuidSchema),
  created_at: TimestampSchema
});

export const ArtifactVersionCreateRouteSchema = {
  tags: ['artifact'],
  body: ArtifactVersionCreateRequestSchema,
  response: {
    201: ArtifactVersionSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const ArtifactVersionAsOfQuerySchema = Type.Object({
  artifact_id: UuidSchema,
  as_of_valid_time: TimestampSchema
});

export const ArtifactVersionAsOfRouteSchema = {
  tags: ['artifact'],
  querystring: ArtifactVersionAsOfQuerySchema,
  response: {
    200: Type.Object({
      artifact_version: Type.Optional(ArtifactVersionSchema)
    }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

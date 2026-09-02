import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { JsonValueSchema, TimestampSchema, UuidSchema } from './shared.js';

const RefSchema = Type.String({ minLength: 1, maxLength: 300 });

const IngestErrorItemSchema = Type.Object({
  index: Type.Integer({ minimum: 0 }),
  code: Type.String(),
  message: Type.String()
});

const IngestRefStateSchema = Type.Object({
  entity_ref_to_id: Type.Optional(Type.Record(Type.String(), UuidSchema)),
  artifact_ref_to_id: Type.Optional(Type.Record(Type.String(), UuidSchema)),
  artifact_ref_to_version_id: Type.Optional(Type.Record(Type.String(), UuidSchema)),
  event_ref_to_id: Type.Optional(Type.Record(Type.String(), UuidSchema))
});

const IngestResponseBaseSchema = Type.Object({
  ingest_run_id: UuidSchema,
  stream_id: Type.String({ minLength: 1 }),
  accepted: Type.Integer({ minimum: 0 }),
  rejected: Type.Integer({ minimum: 0 }),
  errors: Type.Array(IngestErrorItemSchema),
  ref_state_delta: IngestRefStateSchema
});

export const IngestEntitiesRequestSchema = Type.Object({
  ingest_run_id: Type.Optional(UuidSchema),
  stream_id: Type.String({ minLength: 1 }),
  dry_run: Type.Optional(Type.Boolean({ default: false })),
  items: Type.Array(
    Type.Object({
      entity_ref: Type.Optional(RefSchema),
      entity_id: Type.Optional(UuidSchema),
      entity_type: Type.String({ minLength: 1, maxLength: 120 }),
      display_name: Type.String({ minLength: 1, maxLength: 400 }),
      external_refs: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
      status: Type.Optional(
        Type.Union([Type.Literal('active'), Type.Literal('inactive'), Type.Literal('deleted')])
      )
    }),
    { minItems: 1, maxItems: 5000 }
  )
});

export const IngestEntitiesResponseSchema = Type.Intersect([
  IngestResponseBaseSchema,
  Type.Object({
    results: Type.Array(
      Type.Object({
        index: Type.Integer({ minimum: 0 }),
        entity_ref: Type.Optional(Type.String()),
        entity_id: UuidSchema
      })
    )
  })
]);

export const IngestArtifactsRequestSchema = Type.Object({
  ingest_run_id: Type.Optional(UuidSchema),
  stream_id: Type.String({ minLength: 1 }),
  dry_run: Type.Optional(Type.Boolean({ default: false })),
  ref_state: Type.Optional(IngestRefStateSchema),
  items: Type.Array(
    Type.Object({
      artifact_ref: Type.Optional(RefSchema),
      artifact: Type.Object({
        artifact_type: Type.String({ minLength: 1, maxLength: 120 }),
        name: Type.String({ minLength: 1, maxLength: 300 }),
        description: Type.Optional(Type.String({ maxLength: 4000 }))
      }),
      versions: Type.Array(
        Type.Object({
          version_number: Type.Integer({ minimum: 1 }),
          status: Type.String({ minLength: 1, maxLength: 50 }),
          valid_from: TimestampSchema,
          valid_to: Type.Optional(TimestampSchema),
          content_ref: Type.String({ minLength: 1, maxLength: 2000 }),
          content_hash: Type.Optional(Type.String({ maxLength: 256 })),
          author_id: Type.Optional(UuidSchema),
          author_ref: Type.Optional(RefSchema),
          approver_id: Type.Optional(UuidSchema),
          approver_ref: Type.Optional(RefSchema),
          system_from: Type.Optional(TimestampSchema)
        }),
        { minItems: 1, maxItems: 1000 }
      )
    }),
    { minItems: 1, maxItems: 2000 }
  )
});

export const IngestArtifactsResponseSchema = Type.Intersect([
  IngestResponseBaseSchema,
  Type.Object({
    results: Type.Array(
      Type.Object({
        index: Type.Integer({ minimum: 0 }),
        artifact_ref: Type.Optional(Type.String()),
        artifact_id: UuidSchema,
        artifact_version_ids: Type.Array(UuidSchema)
      })
    )
  })
]);

export const IngestEventsRequestSchema = Type.Object({
  ingest_run_id: Type.Optional(UuidSchema),
  stream_id: Type.String({ minLength: 1 }),
  dry_run: Type.Optional(Type.Boolean({ default: false })),
  ref_state: Type.Optional(IngestRefStateSchema),
  items: Type.Array(
    Type.Object({
      event_ref: Type.Optional(RefSchema),
      case_id: Type.Optional(UuidSchema),
      case_ref: Type.Optional(RefSchema),
      event_type: Type.Optional(Type.String({ minLength: 1, maxLength: 100 })),
      actor_id: Type.Optional(UuidSchema),
      actor_ref: Type.Optional(RefSchema),
      subject_id: Type.Optional(UuidSchema),
      subject_ref: Type.Optional(RefSchema),
      object_id: Type.Optional(UuidSchema),
      object_ref: Type.Optional(RefSchema),
      payload: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
      event_text: Type.Optional(Type.String({ minLength: 1 })),
      embedding: Type.Optional(Type.Array(Type.Number())),
      embedding_model: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
      valid_time: Type.Optional(TimestampSchema),
      system_time: Type.Optional(TimestampSchema)
    }),
    { minItems: 1, maxItems: 10000 }
  )
});

export const IngestEventsResponseSchema = Type.Intersect([
  IngestResponseBaseSchema,
  Type.Object({
    event_ids: Type.Array(UuidSchema),
    results: Type.Array(
      Type.Object({
        index: Type.Integer({ minimum: 0 }),
        event_ref: Type.Optional(Type.String()),
        event_id: UuidSchema
      })
    )
  })
]);

export const IngestTextRequestSchema = Type.Object({
  ingest_run_id: Type.Optional(UuidSchema),
  stream_id: Type.String({ minLength: 1 }),
  dry_run: Type.Optional(Type.Boolean({ default: false })),
  generate_embedding: Type.Optional(Type.Boolean()),
  embedding_model: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
  event_type: Type.Optional(Type.String({ minLength: 1, maxLength: 100 })),
  valid_time: Type.Optional(TimestampSchema),
  system_time: Type.Optional(TimestampSchema),
  items: Type.Array(
    Type.Object({
      event_ref: Type.Optional(RefSchema),
      text: Type.String({ minLength: 1 }),
      payload: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
      embedding: Type.Optional(Type.Array(Type.Number()))
    }),
    { minItems: 1, maxItems: 10000 }
  )
});

export const IngestTextResponseSchema = IngestEventsResponseSchema;

export const IngestPropertyRequestSchema = Type.Object({
  ingest_run_id: Type.Optional(UuidSchema),
  stream_id: Type.String({ minLength: 1 }),
  dry_run: Type.Optional(Type.Boolean({ default: false })),
  ref_state: Type.Optional(IngestRefStateSchema),
  items: Type.Array(
    Type.Object({
      object_id: Type.Optional(UuidSchema),
      object_ref: Type.Optional(RefSchema),
      key: Type.String({ minLength: 1, maxLength: 200 }),
      value: Type.Record(Type.String(), JsonValueSchema),
      valid_from: TimestampSchema,
      system_from: Type.Optional(TimestampSchema),
      source_event_id: Type.Optional(UuidSchema),
      source_event_ref: Type.Optional(RefSchema),
      confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 }))
    }),
    { minItems: 1, maxItems: 10000 }
  )
});

export const IngestPropertyResponseSchema = Type.Intersect([
  IngestResponseBaseSchema,
  Type.Object({
    results: Type.Array(
      Type.Object({
        index: Type.Integer({ minimum: 0 }),
        property_state_id: UuidSchema
      })
    )
  })
]);

export const IngestEdgeRequestSchema = Type.Object({
  ingest_run_id: Type.Optional(UuidSchema),
  stream_id: Type.String({ minLength: 1 }),
  dry_run: Type.Optional(Type.Boolean({ default: false })),
  ref_state: Type.Optional(IngestRefStateSchema),
  items: Type.Array(
    Type.Object({
      src_id: Type.Optional(UuidSchema),
      src_ref: Type.Optional(RefSchema),
      predicate: Type.String({ minLength: 1, maxLength: 200 }),
      dst_id: Type.Optional(UuidSchema),
      dst_ref: Type.Optional(RefSchema),
      valid_from: TimestampSchema,
      system_from: Type.Optional(TimestampSchema),
      source_event_id: Type.Optional(UuidSchema),
      source_event_ref: Type.Optional(RefSchema),
      confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 }))
    }),
    { minItems: 1, maxItems: 10000 }
  )
});

export const IngestEdgeResponseSchema = Type.Intersect([
  IngestResponseBaseSchema,
  Type.Object({
    results: Type.Array(
      Type.Object({
        index: Type.Integer({ minimum: 0 }),
        edge_state_id: UuidSchema
      })
    )
  })
]);

export const IngestBundleDefaultsSchema = Type.Object({
  event_type: Type.Optional(Type.String({ minLength: 1, maxLength: 100 })),
  valid_time: Type.Optional(TimestampSchema),
  system_time: Type.Optional(TimestampSchema)
});

const IngestBundlePropertyItemSchema = Type.Object({
  object_id: Type.Optional(UuidSchema),
  object_ref: Type.Optional(RefSchema),
  key: Type.String({ minLength: 1, maxLength: 200 }),
  value: Type.Record(Type.String(), JsonValueSchema),
  valid_from: Type.Optional(TimestampSchema),
  system_from: Type.Optional(TimestampSchema),
  source_event_id: Type.Optional(UuidSchema),
  source_event_ref: Type.Optional(RefSchema),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 }))
});

const IngestBundleEdgeItemSchema = Type.Object({
  src_id: Type.Optional(UuidSchema),
  src_ref: Type.Optional(RefSchema),
  predicate: Type.String({ minLength: 1, maxLength: 200 }),
  dst_id: Type.Optional(UuidSchema),
  dst_ref: Type.Optional(RefSchema),
  valid_from: Type.Optional(TimestampSchema),
  system_from: Type.Optional(TimestampSchema),
  source_event_id: Type.Optional(UuidSchema),
  source_event_ref: Type.Optional(RefSchema),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 }))
});

export const IngestBundleRequestSchema = Type.Object({
  ingest_run_id: Type.Optional(UuidSchema),
  stream_id: Type.String({ minLength: 1 }),
  dry_run: Type.Optional(Type.Boolean({ default: false })),
  defaults: Type.Optional(IngestBundleDefaultsSchema),
  entities: Type.Optional(IngestEntitiesRequestSchema.properties.items),
  artifacts: Type.Optional(IngestArtifactsRequestSchema.properties.items),
  events: Type.Optional(IngestEventsRequestSchema.properties.items),
  properties: Type.Optional(Type.Array(IngestBundlePropertyItemSchema, { minItems: 1, maxItems: 10000 })),
  edges: Type.Optional(Type.Array(IngestBundleEdgeItemSchema, { minItems: 1, maxItems: 10000 }))
});

export const IngestBundleResponseSchema = Type.Object({
  ingest_run_id: UuidSchema,
  stream_id: Type.String({ minLength: 1 }),
  ref_state: IngestRefStateSchema,
  totals: Type.Object({
    accepted: Type.Integer({ minimum: 0 }),
    rejected: Type.Integer({ minimum: 0 }),
    errors: Type.Integer({ minimum: 0 })
  }),
  phases: Type.Object({
    entities: IngestEntitiesResponseSchema,
    artifacts: IngestArtifactsResponseSchema,
    events: IngestEventsResponseSchema,
    properties: IngestPropertyResponseSchema,
    edges: IngestEdgeResponseSchema
  })
});

export const IngestEntitiesRouteSchema = {
  tags: ['ingest'],
  body: IngestEntitiesRequestSchema,
  response: {
    200: IngestEntitiesResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const IngestArtifactsRouteSchema = {
  tags: ['ingest'],
  body: IngestArtifactsRequestSchema,
  response: {
    200: IngestArtifactsResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const IngestEventsRouteSchema = {
  tags: ['ingest'],
  body: IngestEventsRequestSchema,
  response: {
    200: IngestEventsResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const IngestTextRouteSchema = {
  tags: ['ingest'],
  body: IngestTextRequestSchema,
  response: {
    200: IngestTextResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const IngestBundleRouteSchema = {
  tags: ['ingest'],
  body: IngestBundleRequestSchema,
  response: {
    200: IngestBundleResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const IngestPropertyRouteSchema = {
  tags: ['ingest'],
  body: IngestPropertyRequestSchema,
  response: {
    200: IngestPropertyResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const IngestEdgeRouteSchema = {
  tags: ['ingest'],
  body: IngestEdgeRequestSchema,
  response: {
    200: IngestEdgeResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

import { Type } from '@sinclair/typebox';

import { EVENT_TYPES } from '../../domain/event.js';
import { ErrorSchema } from './common.js';
import { JsonValueSchema, TimestampSchema, UuidSchema } from './shared.js';

export const EventAppendRequestSchema = Type.Object({
  case_id: Type.Optional(UuidSchema),
  stream_id: Type.Optional(Type.String({ minLength: 1, maxLength: 300 })),
  event_type: Type.Union(EVENT_TYPES.map((value) => Type.Literal(value))),
  actor_id: Type.Optional(UuidSchema),
  subject_id: Type.Optional(UuidSchema),
  object_id: Type.Optional(UuidSchema),
  payload: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  event_text: Type.Optional(Type.String({ minLength: 1 })),
  embedding: Type.Optional(Type.Array(Type.Number())),
  embedding_model: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
  valid_time: TimestampSchema,
  system_time: Type.Optional(TimestampSchema)
});

export const EventAppendResponseSchema = Type.Object({
  event_id: UuidSchema,
  event_seq: Type.Integer({ minimum: 1 }),
  system_time: TimestampSchema
});

export const EventAppendRouteSchema = {
  tags: ['event'],
  body: EventAppendRequestSchema,
  response: {
    201: EventAppendResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const EventReadQuerySchema = Type.Object({
  case_id: UuidSchema,
  from_seq: Type.Optional(Type.Integer({ minimum: 1 })),
  to_seq: Type.Optional(Type.Integer({ minimum: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000, default: 200 }))
});

export const EventReadItemSchema = Type.Object({
  event_id: UuidSchema,
  case_id: UuidSchema,
  event_seq: Type.Integer({ minimum: 1 }),
  event_type: Type.String(),
  actor_id: Type.Optional(UuidSchema),
  subject_id: Type.Optional(UuidSchema),
  object_id: Type.Optional(UuidSchema),
  payload: Type.Record(Type.String(), JsonValueSchema),
  valid_time: TimestampSchema,
  system_time: TimestampSchema
});

export const EventReadResponseSchema = Type.Object({
  events: Type.Array(EventReadItemSchema)
});

export const EventReadRouteSchema = {
  tags: ['event'],
  querystring: EventReadQuerySchema,
  response: {
    200: EventReadResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const EventSentencesQuerySchema = Type.Object({
  stream_id: Type.String({ minLength: 1 }),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 2000, default: 500 }))
});

export const EventSentenceItemSchema = Type.Object({
  stream_id: Type.String(),
  event_id: Type.String(),
  sent_index: Type.Integer(),
  start_char: Type.Union([Type.Integer(), Type.Null()]),
  end_char: Type.Union([Type.Integer(), Type.Null()]),
  sentence_text: Type.String()
});

export const EventSentencesRouteSchema = {
  tags: ['event'],
  querystring: EventSentencesQuerySchema,
  response: {
    200: Type.Object({ sentences: Type.Array(EventSentenceItemSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

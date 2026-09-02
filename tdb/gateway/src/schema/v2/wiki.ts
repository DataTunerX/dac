import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { OntologyFactHistoryResponseSchema } from './governance.js';
import { TimestampSchema, UuidSchema } from './shared.js';

// ── Enum literals ─────────────────────────────────────────────────────────────

export const WikiPageTypeSchema = Type.Union([
  Type.Literal('entity'),
  Type.Literal('concept'),
  Type.Literal('source_summary'),
  Type.Literal('comparison'),
  Type.Literal('index'),
  Type.Literal('log'),
]);

export const WikiActionTypeSchema = Type.Union([
  Type.Literal('ingest'),
  Type.Literal('query'),
  Type.Literal('lint'),
  Type.Literal('crystallize'),
  Type.Literal('export'),
]);

export const WikiKnowledgeLevelSchema = Type.Union([
  Type.Literal('fact_like'),
  Type.Literal('topic_like'),
  Type.Literal('concept_like'),
  Type.Literal('generalization_like'),
  Type.Literal('principle_like'),
  Type.Literal('theory_like'),
]);

export const WikiAuthorityKindSchema = Type.Union([
  Type.Literal('accepted_ontology'),
  Type.Literal('compiled_summary'),
  Type.Literal('methodology'),
  Type.Literal('candidate_derived'),
]);

// ── Core response shapes ──────────────────────────────────────────────────────

export const WikiPageSchema = Type.Object({
  page_id: UuidSchema,
  domain: Type.String(),
  slug: Type.String(),
  title: Type.String(),
  content: Type.String(),
  page_type: WikiPageTypeSchema,
  knowledge_level: Type.Optional(WikiKnowledgeLevelSchema),
  authority_kind: Type.Optional(WikiAuthorityKindSchema),
  tags: Type.Array(Type.String()),
  source_count: Type.Integer(),
  confidence: Type.Number(),
  effective_confidence: Type.Number(),
  last_reinforced_at: TimestampSchema,
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
  superseded_by: Type.Optional(UuidSchema),
});

export const WikiPageSummarySchema = Type.Object({
  page_id: UuidSchema,
  domain: Type.String(),
  slug: Type.String(),
  title: Type.String(),
  page_type: WikiPageTypeSchema,
  knowledge_level: Type.Optional(WikiKnowledgeLevelSchema),
  authority_kind: Type.Optional(WikiAuthorityKindSchema),
  confidence: Type.Number(),
  effective_confidence: Type.Number(),
  updated_at: TimestampSchema,
});

export const WikiOperationLogSchema = Type.Object({
  log_id: UuidSchema,
  domain: Type.String(),
  action_type: WikiActionTypeSchema,
  source_ref: Type.Optional(Type.String()),
  pages_touched: Type.Integer(),
  summary: Type.Optional(Type.String()),
  created_at: TimestampSchema,
});

export const WikiLintIssueSchema = Type.Object({
  type: Type.String(),
  page_id: Type.Optional(UuidSchema),
  slug: Type.Optional(Type.String()),
  description: Type.String(),
  severity: Type.Union([Type.Literal('error'), Type.Literal('warning'), Type.Literal('info')]),
});

// ── Request bodies ────────────────────────────────────────────────────────────

export const WikiUpsertPageBodySchema = Type.Object({
  domain: Type.String({ minLength: 1 }),
  slug: Type.String({ minLength: 1 }),
  title: Type.String({ minLength: 1 }),
  content: Type.String(),
  page_type: WikiPageTypeSchema,
  knowledge_level: Type.Optional(WikiKnowledgeLevelSchema),
  authority_kind: Type.Optional(WikiAuthorityKindSchema),
  tags: Type.Optional(Type.Array(Type.String())),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  source_ref: Type.Optional(Type.String()),
  supersede: Type.Optional(Type.Boolean()),
});

export const WikiGetPageQuerySchema = Type.Object({
  domain: Type.String({ minLength: 1 }),
  slug: Type.String({ minLength: 1 }),
});

export const WikiGetPageEvidenceQuerySchema = Type.Object({
  domain: Type.String({ minLength: 1 }),
  slug: Type.String({ minLength: 1 }),
  fact_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100, default: 20 })),
  evidence_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50, default: 5 })),
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
});

export const WikiSearchQuerySchema = Type.Object({
  domain: Type.String({ minLength: 1 }),
  q: Type.String({ minLength: 1 }),
  page_type: Type.Optional(WikiPageTypeSchema),
  knowledge_level: Type.Optional(WikiKnowledgeLevelSchema),
  authority_kind: Type.Optional(WikiAuthorityKindSchema),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
});

export const WikiIndexQuerySchema = Type.Object({
  domain: Type.String({ minLength: 1 }),
});

export const WikiListPagesQuerySchema = Type.Object({
  domain: Type.String({ minLength: 1 }),
  page_type: Type.Optional(WikiPageTypeSchema),
  knowledge_level: Type.Optional(WikiKnowledgeLevelSchema),
  authority_kind: Type.Optional(WikiAuthorityKindSchema),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000, default: 200 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, default: 0 })),
});

export const WikiAppendLogBodySchema = Type.Object({
  domain: Type.String({ minLength: 1 }),
  action_type: WikiActionTypeSchema,
  source_ref: Type.Optional(Type.String()),
  pages_touched: Type.Optional(Type.Integer({ minimum: 0 })),
  summary: Type.Optional(Type.String()),
});

export const WikiUpsertLinkBodySchema = Type.Object({
  domain: Type.String({ minLength: 1 }),
  from_slug: Type.String({ minLength: 1 }),
  to_slug: Type.String({ minLength: 1 }),
  link_text: Type.Optional(Type.String()),
});

export const WikiLogQuerySchema = Type.Object({
  domain: Type.String({ minLength: 1 }),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
});

export const WikiLintQuerySchema = Type.Object({
  domain: Type.String({ minLength: 1 }),
});

export const WikiExportBodySchema = Type.Object({
  domain: Type.String({ minLength: 1 }),
  output_dir: Type.String({ minLength: 1 }),
});

export const WikiReinforceBodySchema = Type.Object({
  page_id: UuidSchema,
  delta_confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
});

// ── Route schemas ─────────────────────────────────────────────────────────────

export const WikiUpsertPageRouteSchema = {
  tags: ['wiki'],
  body: WikiUpsertPageBodySchema,
  response: {
    200: Type.Object({
      page_id: UuidSchema,
      slug: Type.String(),
      status: Type.Union([Type.Literal('created'), Type.Literal('updated'), Type.Literal('versioned')]),
      superseded_page_id: Type.Optional(UuidSchema),
    }),
    400: ErrorSchema,
    500: ErrorSchema,
  },
};

export const WikiGetPageRouteSchema = {
  tags: ['wiki'],
  querystring: WikiGetPageQuerySchema,
  response: {
    200: Type.Object({ page: Type.Optional(WikiPageSchema) }),
    400: ErrorSchema,
    500: ErrorSchema,
  },
};

export const WikiSearchRouteSchema = {
  tags: ['wiki'],
  querystring: WikiSearchQuerySchema,
  response: {
    200: Type.Object({ results: Type.Array(WikiPageSummarySchema) }),
    400: ErrorSchema,
    500: ErrorSchema,
  },
};

export const WikiGetPageEvidenceRouteSchema = {
  tags: ['wiki'],
  querystring: WikiGetPageEvidenceQuerySchema,
  response: {
    200: Type.Object({
      page: WikiPageSchema,
      facts: Type.Array(OntologyFactHistoryResponseSchema),
    }),
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema,
  },
};

export const WikiIndexRouteSchema = {
  tags: ['wiki'],
  querystring: WikiIndexQuerySchema,
  response: {
    200: Type.Object({ index_content: Type.String() }),
    400: ErrorSchema,
    500: ErrorSchema,
  },
};

export const WikiAppendLogRouteSchema = {
  tags: ['wiki'],
  body: WikiAppendLogBodySchema,
  response: {
    201: WikiOperationLogSchema,
    400: ErrorSchema,
    500: ErrorSchema,
  },
};

export const WikiUpsertLinkRouteSchema = {
  tags: ['wiki'],
  body: WikiUpsertLinkBodySchema,
  response: {
    201: Type.Object({
      from_page_id: Type.Optional(UuidSchema),
      to_page_id: Type.Optional(UuidSchema),
      status: Type.Union([Type.Literal('created'), Type.Literal('updated'), Type.Literal('missing_page')]),
    }),
    400: ErrorSchema,
    500: ErrorSchema,
  },
};

export const WikiLogRouteSchema = {
  tags: ['wiki'],
  querystring: WikiLogQuerySchema,
  response: {
    200: Type.Object({ logs: Type.Array(WikiOperationLogSchema) }),
    400: ErrorSchema,
    500: ErrorSchema,
  },
};

export const WikiLintRouteSchema = {
  tags: ['wiki'],
  querystring: WikiLintQuerySchema,
  response: {
    200: Type.Object({ issues: Type.Array(WikiLintIssueSchema) }),
    400: ErrorSchema,
    500: ErrorSchema,
  },
};

export const WikiExportRouteSchema = {
  tags: ['wiki'],
  body: WikiExportBodySchema,
  response: {
    200: Type.Object({ files_written: Type.Integer(), output_dir: Type.String() }),
    400: ErrorSchema,
    500: ErrorSchema,
  },
};

export const WikiReinforceRouteSchema = {
  tags: ['wiki'],
  body: WikiReinforceBodySchema,
  response: {
    200: WikiPageSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema,
  },
};

export const WikiListPagesRouteSchema = {
  tags: ['wiki'],
  querystring: WikiListPagesQuerySchema,
  response: {
    200: Type.Object({
      pages: Type.Array(WikiPageSchema),
      total: Type.Integer({ minimum: 0 }),
      limit: Type.Integer({ minimum: 1 }),
      offset: Type.Integer({ minimum: 0 }),
    }),
    400: ErrorSchema,
    500: ErrorSchema,
  },
};

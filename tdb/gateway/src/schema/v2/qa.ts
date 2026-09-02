import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { OntologyFactHistoryResponseSchema } from './governance.js';
import { OntologyConceptSchema } from './ontology.js';
import { TimestampSchema, UuidSchema } from './shared.js';
import {
  WikiAuthorityKindSchema,
  WikiKnowledgeLevelSchema,
  WikiPageTypeSchema,
} from './wiki.js';

export const QaEvidencePackRequestSchema = Type.Object({
  question: Type.String({ minLength: 1 }),
  domain: Type.String({ minLength: 1 }),
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
  wiki_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20, default: 5 })),
  concept_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20, default: 5 })),
  fact_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50, default: 10 })),
  evidence_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20, default: 3 })),
});

export const QaEvidencePackWikiHitSchema = Type.Object({
  matched_by: Type.String({ minLength: 1 }),
  page: Type.Object({
    page_id: UuidSchema,
    domain: Type.String(),
    slug: Type.String(),
    title: Type.String(),
    page_type: WikiPageTypeSchema,
    knowledge_level: Type.Optional(WikiKnowledgeLevelSchema),
    authority_kind: Type.Optional(WikiAuthorityKindSchema),
    confidence: Type.Number(),
    updated_at: TimestampSchema,
  }),
  facts: Type.Array(OntologyFactHistoryResponseSchema),
});

export const QaEvidencePackConceptHitSchema = Type.Object({
  matched_by: Type.String({ minLength: 1 }),
  match_source: Type.Union([Type.Literal('canonical'), Type.Literal('alias')]),
  concept: OntologyConceptSchema,
  facts: Type.Array(OntologyFactHistoryResponseSchema),
});

export const QaEvidencePackResponseSchema = Type.Object({
  question: Type.String(),
  domain: Type.String(),
  query_variants: Type.Array(Type.String()),
  wiki_hits: Type.Array(QaEvidencePackWikiHitSchema),
  concept_hits: Type.Array(QaEvidencePackConceptHitSchema),
  fact_hits: Type.Array(OntologyFactHistoryResponseSchema),
});

export const QaEvidencePackRouteSchema = {
  tags: ['qa'],
  body: QaEvidencePackRequestSchema,
  response: {
    200: QaEvidencePackResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema,
  },
} as const;

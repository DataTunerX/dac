import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';
import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

// ── Ebbinghaus confidence decay ───────────────────────────────────────────────
//
// effective_confidence = base_confidence × exp(-λ × days_since_reinforced)
//
// λ per page_type — slower for stable knowledge, faster for fresh summaries.
const DECAY_LAMBDA: Record<string, number> = {
  entity:         0.005,
  concept:        0.005,
  source_summary: 0.02,
  comparison:     0.01,
  index:          0,
  log:            0,
};

export function computeEffectiveConfidence(
  pageType: string,
  baseConfidence: number,
  lastReinforcedAt: string,
): number {
  const λ = DECAY_LAMBDA[pageType] ?? 0.005;
  if (λ === 0) return baseConfidence;
  const daysSince = (Date.now() - new Date(lastReinforcedAt).getTime()) / 86_400_000;
  const effective = baseConfidence * Math.exp(-λ * daysSince);
  // Round to 4 decimal places and keep within [0, 1]
  return Math.min(1, Math.max(0, Math.round(effective * 10_000) / 10_000));
}

// ── Row types ─────────────────────────────────────────────────────────────────

export type WikiPageRow = {
  page_id: string;
  domain: string;
  slug: string;
  title: string;
  content: string;
  page_type: string;
  tags: unknown[];
  source_count: number;
  confidence: number;
  last_reinforced_at: string;
  created_at: string;
  updated_at: string;
  superseded_by: string | null;
};

export type WikiOperationLogRow = {
  log_id: string;
  domain: string;
  action_type: string;
  source_ref: string | null;
  pages_touched: number;
  summary: string | null;
  created_at: string;
};

// ── Wiki page helpers ─────────────────────────────────────────────────────────

export async function upsertWikiPage(
  db: Queryable,
  input: {
    domain: string;
    slug: string;
    title: string;
    content: string;
    pageType: string;
    tags: string[];
    confidence?: number;
    sourceRef?: string;
  },
): Promise<{ pageId: string; status: 'created' | 'updated' }> {
  const now = new Date().toISOString();

  // Detect whether a row already exists so we can return the right status.
  const existing = await db.maybeOne(sql.typeAlias('record')`
    SELECT page_id::text FROM wiki_page
    WHERE domain = ${input.domain} AND slug = ${input.slug}
      AND superseded_by IS NULL
  `);

  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO wiki_page (domain, slug, title, content, page_type, tags, confidence, source_count, last_reinforced_at)
    VALUES (
      ${input.domain},
      ${input.slug},
      ${input.title},
      ${input.content},
      ${input.pageType},
      ${JSON.stringify(input.tags)}::jsonb,
      ${input.confidence ?? 0.5},
      1,
      ${now}
    )
    ON CONFLICT (domain, slug) DO UPDATE SET
      title               = EXCLUDED.title,
      content             = EXCLUDED.content,
      page_type           = EXCLUDED.page_type,
      tags                = EXCLUDED.tags,
      confidence          = COALESCE(EXCLUDED.confidence, wiki_page.confidence),
      source_count        = wiki_page.source_count + 1,
      last_reinforced_at  = ${now},
      updated_at          = ${now}
    RETURNING page_id::text, domain, slug
  `);

  return {
    pageId: row.page_id as string,
    status: existing ? 'updated' : 'created',
  };
}

export async function getWikiPage(
  db: Queryable,
  domain: string,
  slug: string,
): Promise<WikiPageRow | null> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      page_id::text,
      domain,
      slug,
      title,
      content,
      page_type,
      tags,
      source_count,
      confidence,
      last_reinforced_at,
      created_at,
      updated_at,
      superseded_by::text
    FROM wiki_page
    WHERE domain = ${domain} AND slug = ${slug}
      AND superseded_by IS NULL
  `);

  return row as WikiPageRow | null;
}

// Build an OR-based tsquery from a natural-language string.
// Steps: lowercase → strip punctuation → split on whitespace →
// remove English stopwords → join survivors with ' | '.
// Falls back to the raw query if no tokens survive.
function buildOrTsQuery(query: string): string {
  const STOPWORDS = new Set([
    'a','an','the','and','but','or','if','in','on','at','to','for','of','with',
    'by','from','as','is','are','was','were','be','been','being','have','has',
    'had','do','does','did','will','would','could','should','may','might','shall',
    'can','what','which','who','whom','this','that','these','those','i','me','my',
    'we','us','our','you','your','he','him','his','she','her','they','them','their',
    'it','its','not','no','so','up','out','about','than','how','when','where','why',
    'all','both','each','more','most','other','some','such','then','there','here',
  ]);
  const tokens = query
    .toLowerCase()
    .replace(/[^\w\s]/g, ' ')
    .split(/\s+/)
    .filter(w => w.length > 1 && !STOPWORDS.has(w));
  if (tokens.length === 0) return query;
  return tokens.join(' | ');
}

export async function searchWikiPages(
  db: Queryable,
  domain: string,
  query: string,
  pageType?: string,
  limit = 20,
): Promise<WikiPageRow[]> {
  const typeFilter = pageType
    ? sql.fragment`AND page_type = ${pageType}`
    : sql.fragment``;

  // OR-based full-text query with English stemming/stopword filtering.
  // e.g. "What are the products of Netapp" → "product | netapp"
  // so pages matching ANY significant term are returned (ranked by relevance).
  const orQuery = buildOrTsQuery(query);
  const likePct = `%${query.replace(/[%_\\]/g, c => `\\${c}`)}%`;

  const rows = await db.query(sql.typeAlias('record')`
    SELECT
      page_id::text,
      domain,
      slug,
      title,
      content,
      page_type,
      tags,
      source_count,
      confidence,
      last_reinforced_at,
      created_at,
      updated_at,
      superseded_by::text,
      ts_rank(
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(content, '')),
        to_tsquery('english', ${orQuery})
      ) AS rank
    FROM wiki_page
    WHERE domain = ${domain}
      AND superseded_by IS NULL
      AND (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(content, ''))
            @@ to_tsquery('english', ${orQuery})
        OR title ILIKE ${likePct}
      )
      ${typeFilter}
    ORDER BY rank DESC, updated_at DESC
    LIMIT ${limit}
  `);

  return rows.rows as WikiPageRow[];
}

export async function listWikiPagesByDomain(
  db: Queryable,
  domain: string,
): Promise<WikiPageRow[]> {
  const rows = await db.query(sql.typeAlias('record')`
    SELECT
      page_id::text,
      domain,
      slug,
      title,
      content,
      page_type,
      tags,
      source_count,
      confidence,
      last_reinforced_at,
      created_at,
      updated_at,
      superseded_by::text
    FROM wiki_page
    WHERE domain = ${domain} AND superseded_by IS NULL
    ORDER BY page_type, title
  `);

  return rows.rows as WikiPageRow[];
}

export async function reinforceWikiPage(
  db: Queryable,
  pageId: string,
  deltaConfidence: number,
): Promise<WikiPageRow | null> {
  const now = new Date().toISOString();
  const row = await db.maybeOne(sql.typeAlias('record')`
    UPDATE wiki_page
    SET
      confidence         = LEAST(1.0, confidence + ${deltaConfidence}),
      last_reinforced_at = ${now},
      updated_at         = ${now}
    WHERE page_id = ${pageId}::uuid
    RETURNING
      page_id::text,
      domain,
      slug,
      title,
      content,
      page_type,
      tags,
      source_count,
      confidence,
      last_reinforced_at,
      created_at,
      updated_at,
      superseded_by::text
  `);

  return row as WikiPageRow | null;
}

// ── Operation log helpers ─────────────────────────────────────────────────────

export async function appendWikiLog(
  db: Queryable,
  input: {
    domain: string;
    actionType: string;
    sourceRef?: string;
    pagesTouched: number;
    summary?: string;
  },
): Promise<WikiOperationLogRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO wiki_operation_log (domain, action_type, source_ref, pages_touched, summary)
    VALUES (
      ${input.domain},
      ${input.actionType},
      ${input.sourceRef ?? null},
      ${input.pagesTouched},
      ${input.summary ?? null}
    )
    RETURNING
      log_id::text,
      domain,
      action_type,
      source_ref,
      pages_touched,
      summary,
      created_at
  `);

  return row as WikiOperationLogRow;
}

export async function listWikiLogs(
  db: Queryable,
  domain: string,
  limit = 50,
): Promise<WikiOperationLogRow[]> {
  const rows = await db.query(sql.typeAlias('record')`
    SELECT
      log_id::text,
      domain,
      action_type,
      source_ref,
      pages_touched,
      summary,
      created_at
    FROM wiki_operation_log
    WHERE domain = ${domain}
    ORDER BY created_at DESC
    LIMIT ${limit}
  `);

  return rows.rows as WikiOperationLogRow[];
}

// ── Lint helpers ──────────────────────────────────────────────────────────────

export type WikiLintIssue = {
  type: string;
  page_id?: string;
  slug?: string;
  description: string;
  severity: 'error' | 'warning' | 'info';
};

export async function lintWikiDomain(
  db: Queryable,
  domain: string,
): Promise<WikiLintIssue[]> {
  const issues: WikiLintIssue[] = [];

  // 1. Orphan pages — no inbound links AND not an index/log type
  const orphans = await db.query(sql.typeAlias('record')`
    SELECT page_id::text, slug, page_type
    FROM wiki_page wp
    WHERE wp.domain = ${domain}
      AND wp.superseded_by IS NULL
      AND wp.page_type NOT IN ('index', 'log')
      AND NOT EXISTS (
        SELECT 1 FROM wiki_page_link wpl
        WHERE wpl.to_page_id = wp.page_id
      )
  `);

  for (const row of orphans.rows) {
    issues.push({
      type: 'orphan_page',
      page_id: row.page_id as string ?? undefined,
      slug: row.slug as string ?? undefined,
      description: `Page "${row.slug}" has no inbound links`,
      severity: 'warning',
    });
  }

  // 2. Stale pages — confidence < 0.3 and not reinforced in > 30 days
  const stale = await db.query(sql.typeAlias('record')`
    SELECT page_id::text, slug, confidence, last_reinforced_at
    FROM wiki_page
    WHERE domain = ${domain}
      AND superseded_by IS NULL
      AND confidence < 0.3
      AND last_reinforced_at < NOW() - INTERVAL '30 days'
  `);

  for (const row of stale.rows) {
    issues.push({
      type: 'stale_page',
      page_id: row.page_id as string ?? undefined,
      slug: row.slug as string ?? undefined,
      description: `Page "${row.slug}" has low confidence (${Number(row.confidence).toFixed(2)}) and was last reinforced on ${row.last_reinforced_at}`,
      severity: 'warning',
    });
  }

  // 3. Empty pages — content shorter than 20 chars
  const empty = await db.query(sql.typeAlias('record')`
    SELECT page_id::text, slug, char_length(content) AS len
    FROM wiki_page
    WHERE domain = ${domain}
      AND superseded_by IS NULL
      AND char_length(content) < 20
      AND page_type NOT IN ('log')
  `);

  for (const row of empty.rows) {
    issues.push({
      type: 'empty_page',
      page_id: row.page_id as string ?? undefined,
      slug: row.slug as string ?? undefined,
      description: `Page "${row.slug}" has very short content (${row.len} chars)`,
      severity: 'error',
    });
  }

  return issues;
}

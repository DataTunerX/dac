import fs from 'node:fs/promises';
import path from 'node:path';
import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import { TdbError } from '../../errors/tdb_error.js';
import { WikiEvidenceService } from '../../services/wiki_evidence.service.js';
import {
  WikiAppendLogRouteSchema,
  WikiExportRouteSchema,
  WikiGetPageEvidenceRouteSchema,
  WikiGetPageRouteSchema,
  WikiIndexRouteSchema,
  WikiLintRouteSchema,
  WikiListPagesRouteSchema,
  WikiLogRouteSchema,
  WikiReinforceRouteSchema,
  WikiSearchRouteSchema,
  WikiUpsertLinkRouteSchema,
  WikiUpsertPageRouteSchema,
} from '../../schema/v2/wiki.js';

// Ebbinghaus decay: effective_confidence = base × exp(-λ × days_since_reinforced)
const DECAY_LAMBDA: Record<string, number> = {
  entity: 0.005,
  concept: 0.005,
  comparison: 0.01,
  source_summary: 0.02,
  index: 0,
  log: 0,
};

function computeEffectiveConfidence(pageType: string, baseConfidence: number, lastReinforcedAt: string): number {
  const lambda = DECAY_LAMBDA[pageType] ?? 0.005;
  if (lambda === 0) return baseConfidence;
  const days = (Date.now() - new Date(lastReinforcedAt).getTime()) / (1000 * 60 * 60 * 24);
  return baseConfidence * Math.exp(-lambda * days);
}

type PageType = 'entity' | 'concept' | 'source_summary' | 'comparison' | 'index' | 'log';
type ActionType = 'ingest' | 'query' | 'lint' | 'crystallize' | 'export';
type KnowledgeLevel =
  | 'fact_like'
  | 'topic_like'
  | 'concept_like'
  | 'generalization_like'
  | 'principle_like'
  | 'theory_like';
type AuthorityKind =
  | 'accepted_ontology'
  | 'compiled_summary'
  | 'methodology'
  | 'candidate_derived';

type WikiSearchSummary = {
  page_id: string;
  domain: string;
  slug: string;
  title: string;
  page_type: PageType;
  knowledge_level?: KnowledgeLevel;
  authority_kind?: AuthorityKind;
  confidence: number;
  effective_confidence: number;
  updated_at: string;
};

function serializePage(row: {
  page_id: string; domain: string; slug: string; title: string; content: string;
  page_type: string; knowledge_level: string; authority_kind: string;
  tags_json: string; source_count: number; confidence: number;
  last_reinforced_at: string; created_at: string; updated_at: string; superseded_by: string;
}) {
  let tags: string[] = [];
  try { tags = JSON.parse(row.tags_json) as string[]; } catch { /* empty */ }
  return {
    page_id: row.page_id,
    domain: row.domain,
    slug: row.slug,
    title: row.title,
    content: row.content,
    page_type: row.page_type as PageType,
    knowledge_level: row.knowledge_level ? row.knowledge_level as KnowledgeLevel : undefined,
    authority_kind: row.authority_kind ? row.authority_kind as AuthorityKind : undefined,
    tags,
    source_count: row.source_count,
    confidence: row.confidence,
    effective_confidence: computeEffectiveConfidence(row.page_type, row.confidence, row.last_reinforced_at),
    last_reinforced_at: row.last_reinforced_at,
    created_at: row.created_at,
    updated_at: row.updated_at,
    superseded_by: row.superseded_by || undefined,
  };
}

function serializeLog(r: { log_id: string; domain: string; action_type: string; source_ref: string; pages_touched: number; summary: string; created_at: string }) {
  return {
    log_id: r.log_id,
    domain: r.domain,
    action_type: r.action_type as ActionType,
    source_ref: r.source_ref || undefined,
    pages_touched: r.pages_touched,
    summary: r.summary || undefined,
    created_at: r.created_at,
  };
}

function hasCjk(text: string): boolean {
  return /[\u4e00-\u9fff]/.test(text);
}

function cjkSpans(text: string): string[] {
  return text.match(/[\u4e00-\u9fff]+/g) ?? [];
}

function wikiQueryVariants(query: string): string[] {
  const compact = query.trim().replace(/\s+/g, '');
  const variants = new Set<string>();
  if (query.trim()) variants.add(query.trim());
  if (compact) variants.add(compact);
  for (const span of cjkSpans(compact)) {
    for (let size = Math.min(4, span.length); size >= 2; size--) {
      for (let start = 0; start <= span.length - size; start++) {
        variants.add(span.slice(start, start + size));
      }
    }
  }
  return [...variants];
}

function shouldUseCjkSubstringFallback(query: string): boolean {
  const compact = query.trim().replace(/\s+/g, '');
  return cjkSpans(compact).some((span) => span.length >= 2 && span.length <= 8);
}

function pageMatchesQueryVariants(
  row: { slug: string; title: string; content: string },
  variants: string[]
): boolean {
  const haystack = `${row.slug}\n${row.title}\n${row.content}`.toLowerCase();
  return variants.some((variant) => haystack.includes(variant.toLowerCase()));
}

function serializeSearchSummary(row: {
  page_id: string; domain: string; slug: string; title: string; content: string;
  page_type: string; knowledge_level: string; authority_kind: string;
  confidence: number; last_reinforced_at: string; updated_at: string;
}): WikiSearchSummary {
  return {
    page_id: row.page_id,
    domain: row.domain,
    slug: row.slug,
    title: row.title,
    page_type: row.page_type as PageType,
    knowledge_level: row.knowledge_level ? row.knowledge_level as KnowledgeLevel : undefined,
    authority_kind: row.authority_kind ? row.authority_kind as AuthorityKind : undefined,
    confidence: row.confidence,
    effective_confidence: computeEffectiveConfidence(row.page_type, row.confidence, row.last_reinforced_at),
    updated_at: row.updated_at,
  };
}

const wikiRoutes: FastifyPluginAsyncTypebox = async (app) => {
  // POST /wiki/page — create or update a wiki page
  app.post('/wiki/page', { schema: WikiUpsertPageRouteSchema }, async (req, reply) => {
    const { domain, slug, title, content, page_type, knowledge_level, authority_kind, tags, confidence, source_ref, supersede } = req.body;
    const result = await app.gatewayBackend.upsertWikiPage({
      domain,
      slug,
      title,
      content,
      page_type,
      knowledge_level: knowledge_level ?? '',
      authority_kind: authority_kind ?? '',
      tags_json: JSON.stringify(tags ?? []),
      confidence: confidence ?? 0.5,
      supersede: supersede ?? false,
    });
    if (result.status === 'created') {
      reply.status(200);
    }
    return {
      page_id: result.page_id,
      slug: result.slug,
      status: result.status as 'created' | 'updated' | 'versioned',
      superseded_page_id: result.superseded_page_id || undefined,
    };
  });

  // GET /wiki/page — fetch a single page by domain + slug
  app.get('/wiki/page', { schema: WikiGetPageRouteSchema }, async (req) => {
    const { domain, slug } = req.query;
    const page = await app.gatewayBackend.getWikiPage({ domain, slug });
    return { page: page ? serializePage(page) : undefined };
  });

  app.get('/wiki/page/evidence', { schema: WikiGetPageEvidenceRouteSchema }, async (req) => {
    const service = new WikiEvidenceService(app.gatewayBackend);
    const result = await service.getPageEvidence(req.query);
    return {
      page: serializePage(result.page),
      facts: result.facts,
    } as never;
  });

  app.post('/wiki/link', { schema: WikiUpsertLinkRouteSchema }, async (req, reply) => {
    const { domain, from_slug, to_slug, link_text } = req.body;
    const result = await app.gatewayBackend.upsertWikiPageLink({
      domain,
      from_slug,
      to_slug,
      link_text: link_text ?? '',
    });
    reply.status(201);
    return {
      from_page_id: result.from_page_id || undefined,
      to_page_id: result.to_page_id || undefined,
      status: result.status as 'created' | 'updated' | 'missing_page',
    };
  });

  // GET /wiki/search — full-text search within a domain
  app.get('/wiki/search', { schema: WikiSearchRouteSchema }, async (req) => {
    const { domain, q, page_type, knowledge_level, authority_kind, limit } = req.query;
    const maxResults = limit ?? 20;
    const pages = await app.gatewayBackend.searchWikiPages({
      domain,
      query: q,
      page_type: page_type ?? '',
      knowledge_level: knowledge_level ?? '',
      authority_kind: authority_kind ?? '',
      limit: maxResults,
    });
    let results = pages.map(serializeSearchSummary);

    if (results.length === 0 && shouldUseCjkSubstringFallback(q)) {
      const variants = wikiQueryVariants(q);
      const listed = await app.gatewayBackend.listWikiPages({
        domain,
        page_type: page_type ?? '',
        knowledge_level: knowledge_level ?? '',
        authority_kind: authority_kind ?? '',
        include_content: true,
      });
      results = listed.pages
        .filter((row) => pageMatchesQueryVariants(row, variants))
        .sort((a, b) => {
          const authorityDelta = Number(b.authority_kind === 'accepted_ontology') - Number(a.authority_kind === 'accepted_ontology');
          if (authorityDelta !== 0) return authorityDelta;
          const conceptDelta = Number(b.page_type === 'concept' && b.knowledge_level === 'concept_like') - Number(a.page_type === 'concept' && a.knowledge_level === 'concept_like');
          if (conceptDelta !== 0) return conceptDelta;
          return b.confidence - a.confidence;
        })
        .slice(0, maxResults)
        .map(serializeSearchSummary);
    }

    return { results };
  });

  // GET /wiki/index — markdown directory page for a domain
  app.get('/wiki/index', { schema: WikiIndexRouteSchema }, async (req) => {
    const { domain } = req.query;
    const listed = await app.gatewayBackend.listWikiPages({ domain, page_type: '' });
    const pages = listed.pages;

    const byType: Record<string, Array<{ slug: string; title: string; confidence: number }>> = {};
    for (const r of pages) {
      if (!byType[r.page_type]) byType[r.page_type] = [];
      byType[r.page_type].push({ slug: r.slug, title: r.title, confidence: r.confidence });
    }

    const sections = Object.entries(byType).map(([type, ps]) => {
      const lines = ps.map((p) => `- [[${p.slug}]] — ${p.title} (confidence: ${p.confidence.toFixed(2)})`);
      return `## ${type}\n\n${lines.join('\n')}`;
    });

    const index_content = `# Wiki Index — ${domain}\n\n${sections.join('\n\n')}`;
    return { index_content };
  });

  // POST /wiki/log — append an operation log entry
  app.post('/wiki/log', { schema: WikiAppendLogRouteSchema }, async (req, reply) => {
    const { domain, action_type, source_ref, pages_touched, summary } = req.body;
    const log = await app.gatewayBackend.appendWikiLog({
      domain,
      action_type,
      source_ref: source_ref ?? '',
      pages_touched: pages_touched ?? 0,
      summary: summary ?? '',
    });
    reply.status(201);
    if (!log) throw new TdbError('WIKI_LOG_CREATE_FAILED', 500, 'Failed to create log entry');
    return serializeLog(log);
  });

  // GET /wiki/log — recent log entries for a domain
  app.get('/wiki/log', { schema: WikiLogRouteSchema }, async (req) => {
    const { domain, limit } = req.query;
    const logs = await app.gatewayBackend.listWikiLogs({ domain, limit: limit ?? 50 });
    return { logs: logs.map(serializeLog) };
  });

  // GET /wiki/lint — run health checks on a domain's wiki
  app.get('/wiki/lint', { schema: WikiLintRouteSchema }, async (req) => {
    const { domain } = req.query;
    const issues = await app.gatewayBackend.lintWikiDomain({ domain });
    return {
      issues: issues.map((i) => ({
        type: i.type,
        page_id: i.page_id || undefined,
        slug: i.slug || undefined,
        description: i.description,
        severity: i.severity as 'error' | 'warning' | 'info',
      })),
    };
  });

  // POST /wiki/export — write markdown files to disk
  app.post('/wiki/export', { schema: WikiExportRouteSchema }, async (req) => {
    const { domain, output_dir } = req.body;
    const listed = await app.gatewayBackend.listWikiPages({ domain, include_content: true });
    const pages = listed.pages;

    await fs.mkdir(output_dir, { recursive: true });
    let filesWritten = 0;

    for (const row of pages) {
      const filename = `${row.slug.replace(/[^a-zA-Z0-9\u4e00-\u9fff_-]/g, '_')}.md`;
      const filePath = path.join(output_dir, filename);
      let tags: string[] = [];
      try { tags = JSON.parse(row.tags_json) as string[]; } catch { /* empty */ }
      const frontmatter = [
        '---',
        `title: "${row.title}"`,
        `domain: ${row.domain}`,
        `slug: ${row.slug}`,
        `page_type: ${row.page_type}`,
        ...(row.knowledge_level ? [`knowledge_level: ${row.knowledge_level}`] : []),
        ...(row.authority_kind ? [`authority_kind: ${row.authority_kind}`] : []),
        `tags: [${tags.map((t) => `"${t}"`).join(', ')}]`,
        `confidence: ${row.confidence.toFixed(3)}`,
        `updated_at: ${row.updated_at}`,
        '---',
        '',
      ].join('\n');
      await fs.writeFile(filePath, frontmatter + row.content, 'utf-8');
      filesWritten++;
    }

    await app.gatewayBackend.appendWikiLog({
      domain,
      action_type: 'export',
      source_ref: output_dir,
      pages_touched: filesWritten,
      summary: `Exported ${filesWritten} pages to ${output_dir}`,
    });

    return { files_written: filesWritten, output_dir };
  });

  // GET /wiki/pages — list page summaries, optional page_type filter
  app.get('/wiki/pages', { schema: WikiListPagesRouteSchema }, async (req) => {
    const { domain, page_type, knowledge_level, authority_kind, limit, offset } = req.query;
    const listed = await app.gatewayBackend.listWikiPages({
      domain,
      page_type: page_type ?? '',
      knowledge_level: knowledge_level ?? '',
      authority_kind: authority_kind ?? '',
      limit: limit ?? 200,
      offset: offset ?? 0,
    });
    return {
      pages: listed.pages.map(serializePage),
      total: listed.total,
      limit: listed.limit,
      offset: listed.offset,
    };
  });

  // POST /wiki/reinforce — bump confidence and reset last_reinforced_at
  app.post('/wiki/reinforce', { schema: WikiReinforceRouteSchema }, async (req) => {
    const { page_id, delta_confidence } = req.body;
    const page = await app.gatewayBackend.reinforceWikiPage({
      page_id,
      delta_confidence: delta_confidence ?? 0.05,
    });
    if (!page) {
      throw new TdbError('WIKI_PAGE_NOT_FOUND', 404, `Wiki page ${page_id} not found`);
    }
    return serializePage(page);
  });
};

export default wikiRoutes;

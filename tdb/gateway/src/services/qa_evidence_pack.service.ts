import type {
  ConceptAliasRecord,
  GatewayBackendClient,
  OntologyConceptRecord,
  OntologyFactRecord,
  SemanticStatementReferenceRecord,
  WikiPageRecord,
} from '../clients/gateway_backend.types.js';
import { GovernanceService, type OntologyFactHistoryDto } from './governance.service.js';
import { OntologyEvidenceService } from './ontology_evidence.service.js';
import { WikiEvidenceService } from './wiki_evidence.service.js';

export type QaEvidencePackDto = {
  question: string;
  domain: string;
  query_variants: string[];
  wiki_hits: Array<{
    matched_by: string;
    page: {
      page_id: string;
      domain: string;
      slug: string;
      title: string;
      page_type: string;
      knowledge_level?: string;
      authority_kind?: string;
      confidence: number;
      updated_at: string;
    };
    facts: OntologyFactHistoryDto[];
  }>;
  concept_hits: Array<{
    matched_by: string;
    match_source: 'canonical' | 'alias';
    concept: {
      concept_id: string;
      canonical_name: string;
      concept_type: string;
      aliases: string[];
      created_at: string;
      updated_at: string;
    };
    facts: OntologyFactHistoryDto[];
  }>;
  fact_hits: OntologyFactHistoryDto[];
};

type AnchorContext = {
  anchor_terms: string[];
};

function cleanText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function queryVariants(question: string): string[] {
  const compact = cleanText(question).replace(/\s+/g, '');
  const variants = new Set<string>();
  if (compact) {
    variants.add(compact);
  }
  const cjkSpans = compact.match(/[\u4e00-\u9fff]+/g) ?? [];
  for (const span of cjkSpans) {
    for (let size = Math.min(span.length, 8); size >= 2; size -= 1) {
      for (let start = 0; start <= span.length - size; start += 1) {
        variants.add(span.slice(start, start + size));
      }
    }
  }
  return [...variants].sort((left, right) => right.length - left.length);
}

function stripLeadingContext(text: string): string {
  let value = cleanText(text);
  for (const pattern of [/.*的/u, /.*中/u, /.*里/u, /.*上/u, /.*下/u]) {
    const replaced = value.replace(pattern, '');
    if (replaced && replaced !== value) {
      value = replaced;
    }
  }
  return value;
}

function extractAnchorTerms(question: string): string[] {
  const normalized = cleanText(question).replace(/[？?。！!]/g, '');
  const candidates = new Set<string>();
  const patterns = [
    /(.+?)有哪些/u,
    /(.+?)有哪三个/u,
    /(.+?)有哪几/u,
    /(.+?)是什么/u,
    /(.+?)指什么/u,
    /(.+?)如何/u,
    /(.+?)为什么/u,
  ];
  for (const pattern of patterns) {
    const match = normalized.match(pattern);
    if (!match?.[1]) {
      continue;
    }
    const raw = cleanText(match[1]);
    if (!raw) {
      continue;
    }
    candidates.add(raw);
    const stripped = stripLeadingContext(raw);
    if (stripped) {
      candidates.add(stripped);
    }
  }
  return [...candidates]
    .map((item) => cleanText(item).replace(/\s+/g, ''))
    .filter((item) => item.length >= 2)
    .sort((left, right) => right.length - left.length);
}

function parseAliases(record: OntologyConceptRecord): string[] {
  if (!record.aliases_json) {
    return [];
  }
  try {
    const parsed = JSON.parse(record.aliases_json);
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

function serializeWikiPage(page: WikiPageRecord) {
  return {
    page_id: page.page_id,
    domain: page.domain,
    slug: page.slug,
    title: page.title,
    page_type: page.page_type,
    knowledge_level: cleanText(page.knowledge_level) || undefined,
    authority_kind: cleanText(page.authority_kind) || undefined,
    confidence: page.confidence,
    updated_at: page.updated_at,
  };
}

function matchScore(label: string, variant: string): number {
  const normalizedLabel = cleanText(label).replace(/\s+/g, '');
  const normalizedVariant = cleanText(variant).replace(/\s+/g, '');
  if (!normalizedLabel || !normalizedVariant) {
    return 0;
  }
  if (normalizedLabel === normalizedVariant) {
    return normalizedVariant.length + 1000;
  }
  if (normalizedLabel.includes(normalizedVariant)) {
    return normalizedVariant.length;
  }
  return 0;
}

function isUsefulVariant(variant: string): boolean {
  const normalized = cleanText(variant).replace(/\s+/g, '');
  if (normalized.length < 2) {
    return false;
  }
  if (!/[\u4e00-\u9fffA-Za-z0-9]/.test(normalized)) {
    return false;
  }
  if (normalized.length <= 3 && /^(的是|的是|有哪|哪些|用途|广泛|的用|泛的|中盛|泽地|沼泽)$/.test(normalized)) {
    return false;
  }
  return true;
}

function isSpecificTextMatch(label: string, variant: string): boolean {
  const normalizedLabel = cleanText(label).replace(/\s+/g, '');
  const normalizedVariant = cleanText(variant).replace(/\s+/g, '');
  if (!normalizedLabel || !normalizedVariant) {
    return false;
  }
  if (normalizedLabel === normalizedVariant) {
    return true;
  }
  if (normalizedVariant.length >= 4 && normalizedLabel.includes(normalizedVariant)) {
    return true;
  }
  return false;
}

function bestVariantMatch(label: string, variants: string[]): string | undefined {
  let best: { variant: string; score: number } | undefined;
  for (const variant of variants) {
    if (!isUsefulVariant(variant)) {
      continue;
    }
    const score = matchScore(label, variant);
    if (score <= 0) {
      continue;
    }
    if (!best || score > best.score) {
      best = { variant, score };
    }
  }
  return best?.variant;
}

function dedupeFacts(facts: OntologyFactHistoryDto[]): OntologyFactHistoryDto[] {
  return [...new Map(facts.map((fact) => [fact.fact.fact_id, fact])).values()];
}

function variantSpecificityScore(variant: string): number {
  const normalized = cleanText(variant).replace(/\s+/g, '');
  if (!normalized) {
    return 0;
  }
  let score = normalized.length;
  if (normalized.length >= 4) {
    score += 8;
  }
  if (normalized.length >= 6) {
    score += 8;
  }
  return score;
}

function pageAnchorScore(
  page: { slug: string; title: string; confidence: number },
  matchedBy: string,
  anchors: AnchorContext
): number {
  let score = variantSpecificityScore(matchedBy);
  if (cleanText(page.slug) === cleanText(matchedBy) || cleanText(page.title) === cleanText(matchedBy)) {
    score += 20;
  }
  for (const anchor of anchors.anchor_terms) {
    if (isSpecificTextMatch(page.slug, anchor) || isSpecificTextMatch(page.title, anchor)) {
      score += 40 + variantSpecificityScore(anchor);
    }
  }
  score += page.confidence;
  return score;
}

function conceptAnchorScore(
  concept: { canonical_name: string; aliases: string[] },
  matchedBy: string,
  matchSource: 'canonical' | 'alias',
  anchors: AnchorContext
): number {
  let score = variantSpecificityScore(matchedBy);
  if (cleanText(concept.canonical_name) === cleanText(matchedBy)) {
    score += 24;
  }
  if (matchSource === 'canonical') {
    score += 6;
  }
  if (concept.aliases.some((alias) => cleanText(alias) === cleanText(matchedBy))) {
    score += 4;
  }
  for (const anchor of anchors.anchor_terms) {
    if (
      isSpecificTextMatch(concept.canonical_name, anchor) ||
      concept.aliases.some((alias) => isSpecificTextMatch(alias, anchor))
    ) {
      score += 48 + variantSpecificityScore(anchor);
    }
  }
  return score;
}

function factAnchorScore(fact: OntologyFactHistoryDto, variants: string[], anchors: AnchorContext): number {
  const src = cleanText(fact.fact.src_concept_label);
  const dst = cleanText(fact.fact.dst_concept_label);
  let score = 0;
  for (const anchor of anchors.anchor_terms) {
    const specificity = variantSpecificityScore(anchor);
    if (src && isSpecificTextMatch(src, anchor)) {
      score += specificity + 48;
    }
    if (dst && isSpecificTextMatch(dst, anchor)) {
      score += specificity + 16;
    }
    for (const evidence of fact.evidence) {
      const sentence = cleanText(evidence.sentence?.sentence_text);
      if (sentence && sentence.includes(anchor)) {
        score += specificity + 10;
      }
    }
  }
  for (const variant of variants) {
    if (!isUsefulVariant(variant)) {
      continue;
    }
    const specificity = variantSpecificityScore(variant);
    if (src && isSpecificTextMatch(src, variant)) {
      score += specificity + 20;
    }
    if (dst && isSpecificTextMatch(dst, variant)) {
      score += specificity + 8;
    }
    for (const evidence of fact.evidence) {
      const sentence = cleanText(evidence.sentence?.sentence_text);
      if (sentence && sentence.includes(variant)) {
        score += Math.min(specificity, 12);
      }
    }
  }
  return score;
}

export class QaEvidencePackService {
  private readonly governance: GovernanceService;
  private readonly wikiEvidence: WikiEvidenceService;
  private readonly ontologyEvidence: OntologyEvidenceService;

  constructor(private readonly backend: GatewayBackendClient) {
    this.governance = new GovernanceService(backend);
    this.wikiEvidence = new WikiEvidenceService(backend);
    this.ontologyEvidence = new OntologyEvidenceService(backend);
  }

  async buildPack(input: {
    question: string;
    domain: string;
    stream_id?: string;
    wiki_limit?: number;
    concept_limit?: number;
    fact_limit?: number;
    evidence_limit?: number;
  }): Promise<QaEvidencePackDto> {
    const question = cleanText(input.question);
    const variants = queryVariants(question);
    const anchors: AnchorContext = {
      anchor_terms: extractAnchorTerms(question),
    };
    const wikiLimit = input.wiki_limit ?? 5;
    const conceptLimit = input.concept_limit ?? 5;
    const factLimit = input.fact_limit ?? 10;
    const evidenceLimit = input.evidence_limit ?? 3;

    const wikiHits = await this.collectWikiHits({
      domain: input.domain,
      variants,
      anchors,
      stream_id: input.stream_id,
      wiki_limit: wikiLimit,
      fact_limit: factLimit,
      evidence_limit: evidenceLimit,
    });
    const conceptHits = await this.collectConceptHits({
      domain: input.domain,
      variants,
      anchors,
      stream_id: input.stream_id,
      concept_limit: conceptLimit,
      fact_limit: factLimit,
      evidence_limit: evidenceLimit,
    });

    const directFactHits = await this.collectDirectFactHits({
      question,
      stream_id: input.stream_id,
      fact_limit: factLimit,
      evidence_limit: evidenceLimit,
    });
    const factHits = dedupeFacts([
      ...wikiHits.flatMap((item) => item.facts),
      ...conceptHits.flatMap((item) => item.facts),
      ...directFactHits,
    ]).sort(
      (left, right) => factAnchorScore(right, variants, anchors) - factAnchorScore(left, variants, anchors)
    );

    return {
      question,
      domain: input.domain,
      query_variants: variants,
      wiki_hits: wikiHits,
      concept_hits: conceptHits,
      fact_hits: factHits,
    };
  }

  private async collectWikiHits(input: {
    domain: string;
    variants: string[];
    anchors: AnchorContext;
    stream_id?: string;
    wiki_limit: number;
    fact_limit: number;
    evidence_limit: number;
  }): Promise<QaEvidencePackDto['wiki_hits']> {
    const seen = new Set<string>();
    const pages: Array<{ matched_by: string; page: WikiPageRecord }> = [];
    for (const variant of input.variants) {
      if (!isUsefulVariant(variant)) {
        continue;
      }
      if (pages.length >= input.wiki_limit) {
        break;
      }
      const records = await this.backend.searchWikiPages({
        domain: input.domain,
        query: variant,
        page_type: '',
        knowledge_level: '',
        authority_kind: '',
        limit: input.wiki_limit,
      });
      for (const page of records) {
        if (pages.length >= input.wiki_limit) {
          break;
        }
        if (seen.has(page.slug)) {
          continue;
        }
        const matchedBy = bestVariantMatch(`${page.slug} ${page.title}`, input.variants);
        if (!matchedBy) {
          continue;
        }
        if (!isSpecificTextMatch(page.slug, matchedBy) && !isSpecificTextMatch(page.title, matchedBy)) {
          continue;
        }
        seen.add(page.slug);
        pages.push({ matched_by: matchedBy, page });
      }
    }

    const hits = await Promise.all(
      pages.map(async ({ matched_by, page }) => {
        const evidence = await this.wikiEvidence.getPageEvidence({
          domain: input.domain,
          slug: page.slug,
          fact_limit: input.fact_limit,
          evidence_limit: input.evidence_limit,
          stream_id: input.stream_id,
        });
        return {
          matched_by,
          page: serializeWikiPage(page),
          facts: evidence.facts,
        };
      })
    );
    return hits.sort(
      (left, right) =>
        pageAnchorScore(right.page, right.matched_by, input.anchors) -
        pageAnchorScore(left.page, left.matched_by, input.anchors)
    );
  }

  private async collectConceptHits(input: {
    domain: string;
    variants: string[];
    anchors: AnchorContext;
    stream_id?: string;
    concept_limit: number;
    fact_limit: number;
    evidence_limit: number;
  }): Promise<QaEvidencePackDto['concept_hits']> {
    const seen = new Set<string>();
    const matches: Array<{
      matched_by: string;
      match_source: 'canonical' | 'alias';
      concept: OntologyConceptRecord;
    }> = [];

    for (const variant of input.variants) {
      if (!isUsefulVariant(variant)) {
        continue;
      }
      if (matches.length >= input.concept_limit) {
        break;
      }

      const concepts = await this.backend.searchOntologyConcepts({
        query: variant,
        concept_type: '',
        domain: input.domain,
        limit: input.concept_limit,
        offset: 0,
      });
      for (const concept of concepts) {
        if (matches.length >= input.concept_limit) {
          break;
        }
        if (seen.has(concept.concept_id)) {
          continue;
        }
        const matchedBy = bestVariantMatch(concept.canonical_name, input.variants);
        if (!matchedBy) {
          continue;
        }
        if (!isSpecificTextMatch(concept.canonical_name, matchedBy)) {
          continue;
        }
        seen.add(concept.concept_id);
        matches.push({ matched_by: matchedBy, match_source: 'canonical', concept });
      }

      if (matches.length >= input.concept_limit) {
        continue;
      }

      const aliases = await this.backend.searchConceptAliases({
        query: variant,
        concept_id: '',
        limit: input.concept_limit,
        offset: 0,
      });
      for (const alias of aliases) {
        if (matches.length >= input.concept_limit) {
          break;
        }
        if (seen.has(alias.concept_id)) {
          continue;
        }
        const matchedBy = bestVariantMatch(alias.alias_text, input.variants);
        if (!matchedBy) {
          continue;
        }
        if (!isSpecificTextMatch(alias.alias_text, matchedBy)) {
          continue;
        }
        const concept = await this.backend.getOntologyConcept({ concept_id: alias.concept_id });
        if (!concept) {
          continue;
        }
        seen.add(concept.concept_id);
        matches.push({ matched_by: matchedBy, match_source: 'alias', concept });
      }
    }

    const hits = await Promise.all(
      matches.map(async ({ matched_by, match_source, concept }) => {
        const evidence = await this.ontologyEvidence.getConceptEvidence({
          concept_id: concept.concept_id,
          fact_limit: input.fact_limit,
          evidence_limit: input.evidence_limit,
          stream_id: input.stream_id,
        });
        return {
          matched_by,
          match_source,
          concept: evidence.concept,
          facts: evidence.facts,
        };
      })
    );
    return hits.sort(
      (left, right) =>
        conceptAnchorScore(right.concept, right.matched_by, right.match_source, input.anchors) -
        conceptAnchorScore(left.concept, left.matched_by, left.match_source, input.anchors)
    );
  }

  private async collectDirectFactHits(input: {
    question: string;
    stream_id?: string;
    fact_limit: number;
    evidence_limit: number;
  }): Promise<OntologyFactHistoryDto[]> {
    const facts = await this.backend.searchOntologyFacts({
      query: input.question,
      status: 'accepted',
      stream_id: input.stream_id ?? '',
      stream_prefix: false,
      predicate: '',
      extractor: '',
      src_concept_id: '',
      dst_concept_id: '',
      limit: input.fact_limit,
      offset: 0,
    });
    return this.loadFactHistories(facts, input.evidence_limit, input.stream_id);
  }

  private async loadFactHistories(
    facts: OntologyFactRecord[],
    evidenceLimit: number,
    streamId?: string
  ): Promise<OntologyFactHistoryDto[]> {
    const deduped = [
      ...new Map(facts.map((fact) => [fact.statement_id || `fact:${fact.fact_id}`, fact])).values()
    ];
    return Promise.all(
      deduped.map((fact) => this.loadFactHistory(fact, evidenceLimit, streamId))
    );
  }

  private async loadFactHistory(
    fact: OntologyFactRecord,
    evidenceLimit: number,
    streamId?: string
  ): Promise<OntologyFactHistoryDto> {
    if (Number(fact.fact_id) > 0 || !fact.statement_id) {
      return this.governance.getOntologyFactHistory({
        fact_id: Number(fact.fact_id),
        evidence_limit: evidenceLimit,
        stream_id: streamId,
      });
    }

    const provenanceResponse = await this.backend.getSemanticStatementProvenance({
      statement_id: fact.statement_id,
      include_locators: true,
      evidence_limit: evidenceLimit,
    });

    return {
      fact: {
        fact_id: Number(fact.fact_id),
        statement_id: fact.statement_id,
        src_concept_id: fact.src_concept_id,
        src_concept_label: fact.src_concept_label || undefined,
        predicate: fact.predicate,
        dst_concept_id: fact.dst_concept_id,
        dst_concept_label: fact.dst_concept_label || undefined,
        qualifier_json: fact.qualifier_json ? JSON.parse(fact.qualifier_json) : {},
        confidence: Number(fact.confidence),
        extractor: fact.extractor,
        status: fact.status as OntologyFactHistoryDto['fact']['status'],
        review_note: fact.review_note,
        valid_from: fact.valid_from || undefined,
        valid_to: fact.valid_to || undefined,
        created_at: fact.created_at,
        updated_at: fact.updated_at,
      },
      reviews: [],
      evidence: provenanceResponse.references.map(mapStatementReferenceToFactEvidence),
      evidence_count: provenanceResponse.references.length,
      stream_id_filter: streamId,
    };
  }
}

function mapStatementReferenceToFactEvidence(
  reference: SemanticStatementReferenceRecord
): OntologyFactHistoryDto['evidence'][number] {
  const payload = reference.evidence?.evidence_payload_json
    ? JSON.parse(reference.evidence.evidence_payload_json)
    : {};
  const sentenceRef = reference.locators?.[0]?.sentence_ref_json
    ? JSON.parse(reference.locators[0].sentence_ref_json)
    : undefined;
  return {
    stream_id: String((payload as { stream_id?: string }).stream_id ?? ''),
    event_id: String((payload as { event_id?: string }).event_id ?? reference.evidence?.source_id ?? ''),
    asset_id: reference.evidence?.artifact_version_id || undefined,
    version_number: undefined,
    source_span: reference.source_span || undefined,
    evidence_json: payload as Record<string, unknown>,
    sentence: sentenceRef
      ? {
          sent_index: Number((sentenceRef as { sentence_index?: number }).sentence_index ?? 0),
          sentence_text:
            reference.locators?.[0]?.normalized_text ||
            reference.locators?.[0]?.preview_text ||
            '',
        }
      : undefined,
    confidence: 1,
    created_at: reference.evidence?.created_at || '',
    updated_at: reference.evidence?.updated_at || '',
  };
}

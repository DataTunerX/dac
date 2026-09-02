import type {
  GatewayBackendClient,
  OntologyFactRecord,
  SemanticStatementReferenceRecord,
  WikiPageRecord
} from '../clients/gateway_backend.types.js';
import { TdbError } from '../errors/tdb_error.js';
import { GovernanceService, type OntologyFactHistoryDto } from './governance.service.js';

export type WikiPageEvidenceDto = {
  page: WikiPageRecord;
  facts: OntologyFactHistoryDto[];
};

export class WikiEvidenceService {
  private readonly governance: GovernanceService;

  constructor(private readonly backend: GatewayBackendClient) {
    this.governance = new GovernanceService(backend);
  }

  async getPageEvidence(input: {
    domain: string;
    slug: string;
    fact_limit?: number;
    evidence_limit?: number;
    stream_id?: string;
  }): Promise<WikiPageEvidenceDto> {
    const page = await this.backend.getWikiPage({ domain: input.domain, slug: input.slug });
    if (!page) {
      throw new TdbError('WIKI_PAGE_NOT_FOUND', 404, `Wiki page ${input.domain}/${input.slug} not found`);
    }

    const title = page.title.trim();
    const rawFacts = await this.backend.searchOntologyFacts({
      query: title,
      status: 'accepted',
      stream_id: input.stream_id ?? '',
      stream_prefix: false,
      predicate: '',
      extractor: '',
      src_concept_id: '',
      dst_concept_id: '',
      limit: input.fact_limit ?? 20,
      offset: 0
    });

    const matchingFacts = rawFacts.filter((fact) => {
      const src = (fact.src_concept_label ?? '').trim();
      const dst = (fact.dst_concept_label ?? '').trim();
      return src === title || dst === title;
    });

    const dedupedFacts = [
      ...new Map(matchingFacts.map((fact) => [fact.statement_id || `fact:${fact.fact_id}`, fact])).values()
    ];
    const facts = await Promise.all(
      dedupedFacts.map((fact) => this.loadFactHistory(fact, input.evidence_limit ?? 5, input.stream_id))
    );

    return { page, facts };
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
        stream_id: streamId
      });
    }

    const provenanceResponse = await this.backend.getSemanticStatementProvenance({
      statement_id: fact.statement_id,
      include_locators: true,
      evidence_limit: evidenceLimit
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
        updated_at: fact.updated_at
      },
      reviews: [],
      evidence: provenanceResponse.references.map(mapStatementReferenceToFactEvidence),
      evidence_count: provenanceResponse.references.length,
      stream_id_filter: streamId
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
          sentence_text: reference.locators?.[0]?.normalized_text || reference.locators?.[0]?.preview_text || '',
        }
      : undefined,
    confidence: 1,
    created_at: reference.evidence?.created_at || '',
    updated_at: reference.evidence?.updated_at || '',
  };
}

import type {
  GatewayBackendClient,
  OntologyFactRecord,
  SemanticStatementReferenceRecord
} from '../clients/gateway_backend.types.js';
import { TdbError } from '../errors/tdb_error.js';
import { GovernanceService, type OntologyFactHistoryDto } from './governance.service.js';

export type OntologyConceptEvidenceDto = {
  concept: {
    concept_id: string;
    canonical_name: string;
    concept_type: string;
    aliases: string[];
    created_at: string;
    updated_at: string;
  };
  facts: OntologyFactHistoryDto[];
};

export class OntologyEvidenceService {
  private readonly governance: GovernanceService;

  constructor(private readonly backend: GatewayBackendClient) {
    this.governance = new GovernanceService(backend);
  }

  async getConceptEvidence(input: {
    concept_id: string;
    fact_limit?: number;
    evidence_limit?: number;
    stream_id?: string;
  }): Promise<OntologyConceptEvidenceDto> {
    const concept = await this.backend.getOntologyConcept({ concept_id: input.concept_id });
    if (!concept) {
      throw new TdbError('ONTOLOGY_CONCEPT_NOT_FOUND', 404, `ontology concept not found: ${input.concept_id}`);
    }

    const records = await this.backend.listOntologyFacts({
      status: 'accepted',
      stream_id: input.stream_id ?? '',
      stream_prefix: false,
      predicate: '',
      extractor: '',
      src_concept_id: input.concept_id,
      dst_concept_id: '',
      limit: input.fact_limit ?? 20,
      offset: 0,
    });
    const reverseRecords = await this.backend.listOntologyFacts({
      status: 'accepted',
      stream_id: input.stream_id ?? '',
      stream_prefix: false,
      predicate: '',
      extractor: '',
      src_concept_id: '',
      dst_concept_id: input.concept_id,
      limit: input.fact_limit ?? 20,
      offset: 0,
    });

    const dedupedFacts = [
      ...new Map(
        [...records, ...reverseRecords].map((fact) => [fact.statement_id || `fact:${fact.fact_id}`, fact])
      ).values(),
    ];
    const facts = await Promise.all(
      dedupedFacts.map((fact) => this.loadFactHistory(fact, input.evidence_limit ?? 5, input.stream_id))
    );

    return {
      concept: {
        concept_id: concept.concept_id,
        canonical_name: concept.canonical_name,
        concept_type: concept.concept_type,
        aliases: concept.aliases_json ? JSON.parse(concept.aliases_json) : [],
        created_at: concept.created_at,
        updated_at: concept.updated_at,
      },
      facts,
    };
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

    const [statementResponse, provenanceResponse] = await Promise.all([
      this.backend.getSemanticStatement({ statement_id: fact.statement_id }),
      this.backend.getSemanticStatementProvenance({
        statement_id: fact.statement_id,
        include_locators: true,
        evidence_limit: evidenceLimit,
      }),
    ]);

    const statement = statementResponse.statement;
    if (!statement) {
      throw new TdbError(
        'ONTOLOGY_STATEMENT_NOT_FOUND',
        404,
        `semantic statement not found: ${fact.statement_id}`
      );
    }

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
          sentence_text: reference.locators?.[0]?.normalized_text || reference.locators?.[0]?.preview_text || '',
        }
      : undefined,
    confidence: 1,
    created_at: reference.evidence?.created_at || '',
    updated_at: reference.evidence?.updated_at || '',
  };
}

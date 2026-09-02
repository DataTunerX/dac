import { describe, expect, it, vi } from 'vitest';

import type { GatewayBackendClient, OntologyConceptRecord, OntologyFactRecord } from '../src/clients/gateway_backend.types.js';
import { OntologyEvidenceService } from '../src/services/ontology_evidence.service.js';

function createMockClient(overrides: Partial<GatewayBackendClient>): GatewayBackendClient {
  return {
    getOntologyConcept: vi.fn(),
    listOntologyFacts: vi.fn().mockResolvedValue([]),
    getOntologyFact: vi.fn(),
    listOntologyFactReviews: vi.fn().mockResolvedValue([]),
    listOntologyFactEvidence: vi.fn().mockResolvedValue([]),
    getSemanticStatement: vi.fn(),
    getSemanticStatementProvenance: vi.fn().mockResolvedValue({ references: [] }),
    getEventSentences: vi.fn().mockResolvedValue([]),
    ...overrides,
  } as unknown as GatewayBackendClient;
}

describe('OntologyEvidenceService', () => {
  it('returns both outgoing and incoming accepted facts for a concept', async () => {
    const concept: OntologyConceptRecord = {
      concept_id: 'concept:papyrus',
      canonical_name: '纸草',
      concept_type: 'concept',
      aliases_json: '["Papyrus"]',
      created_at: '2026-07-09T14:32:10.641754+00',
      updated_at: '2026-07-10T14:45:34.937406+00',
    };
    const outgoing: OntologyFactRecord = {
      fact_id: 3309,
      src_concept_id: 'concept:papyrus',
      src_concept_label: '纸草',
      predicate: 'characterized_by',
      dst_concept_id: 'concept:writing-material',
      dst_concept_label: '书写原料',
      qualifier_json: '{}',
      confidence: 1,
      extractor: 'pipeline_relation_candidate_v1',
      status: 'accepted',
      review_note: '',
      created_at: '2026-07-10T14:11:32.189Z',
      updated_at: '2026-07-10T14:15:15.118Z',
    } as unknown as OntologyFactRecord;
    const incoming: OntologyFactRecord = {
      fact_id: 3315,
      src_concept_id: 'concept:swamp',
      src_concept_label: '沼泽地',
      predicate: 'produces_output',
      dst_concept_id: 'concept:papyrus',
      dst_concept_label: '纸草',
      qualifier_json: '{}',
      confidence: 1,
      extractor: 'pipeline_relation_candidate_v1',
      status: 'accepted',
      review_note: '',
      created_at: '2026-07-10T14:11:32.189Z',
      updated_at: '2026-07-10T14:15:15.118Z',
    } as unknown as OntologyFactRecord;

    const client = createMockClient({
      getOntologyConcept: vi.fn().mockResolvedValue(concept),
      listOntologyFacts: vi
        .fn()
        .mockResolvedValueOnce([outgoing])
        .mockResolvedValueOnce([incoming]),
      getOntologyFact: vi
        .fn()
        .mockResolvedValueOnce(outgoing)
        .mockResolvedValueOnce(incoming),
      listOntologyFactEvidence: vi.fn().mockResolvedValue([
        {
          stream_id: 'stream-1',
          event_id: 'event-1',
          asset_id: '',
          version_number: 0,
          source_span: 'doc.md',
          evidence_json: JSON.stringify({ sent_index: 0 }),
          confidence: 1,
          created_at: '2026-07-10T14:11:32.189Z',
          updated_at: '2026-07-10T14:15:15.118Z',
        },
      ]),
      getEventSentences: vi.fn().mockResolvedValue([
        {
          stream_id: 'stream-1',
          event_id: 'event-1',
          sent_index: 0,
          start_char: 0,
          end_char: 11,
          sentence_text: '纸草可用来作书写原料。',
        },
      ]),
    });

    const service = new OntologyEvidenceService(client);
    const result = await service.getConceptEvidence({ concept_id: 'concept:papyrus' });

    expect(result.concept.concept_id).toBe('concept:papyrus');
    expect(result.concept.aliases).toEqual(['Papyrus']);
    expect(result.facts).toHaveLength(2);
    expect(result.facts.map((item) => item.fact.fact_id).sort()).toEqual([3309, 3315]);
  });

  it('prefers statement provenance when semantic fact results only have statement_id', async () => {
    const concept: OntologyConceptRecord = {
      concept_id: 'concept:museum',
      canonical_name: '博物馆',
      concept_type: 'concept',
      aliases_json: '[]',
      created_at: '2026-07-09T14:32:10.641754+00',
      updated_at: '2026-07-10T14:45:34.937406+00',
    };
    const semanticFact: OntologyFactRecord = {
      fact_id: 0,
      statement_id: 'stmt-123',
      src_concept_id: 'concept:museum',
      src_concept_label: '博物馆',
      predicate: 'defined_as',
      dst_concept_id: 'concept:public-service',
      dst_concept_label: '公共服务机构',
      qualifier_json: '{}',
      confidence: 0.9,
      extractor: 'phase1_loader',
      status: 'accepted',
      review_note: '',
      created_at: '2026-07-24T20:00:00Z',
      updated_at: '2026-07-24T20:00:00Z',
    } as unknown as OntologyFactRecord;

    const client = createMockClient({
      getOntologyConcept: vi.fn().mockResolvedValue(concept),
      listOntologyFacts: vi
        .fn()
        .mockResolvedValueOnce([semanticFact])
        .mockResolvedValueOnce([]),
      getSemanticStatement: vi.fn().mockResolvedValue({
        statement: {
          statement_id: 'stmt-123',
          subject_concept_id: 'concept:museum',
          subject_name: '博物馆',
          predicate: 'defined_as',
          object_concept_id: 'concept:public-service',
          object_name: '公共服务机构',
          value_type: 'entity',
          value_json: '{}',
          confidence: 0.9,
          status: 'accepted',
          created_by: 'phase1_loader',
          metadata_json: '{}',
          provenance_json: '{}',
          created_at: '2026-07-24T20:00:00Z',
          updated_at: '2026-07-24T20:00:00Z',
        },
        qualifiers: []
      }),
      getSemanticStatementProvenance: vi.fn().mockResolvedValue({
        references: [
          {
            statement_id: 'stmt-123',
            property_id: 'supporting_quote',
            value_type: 'json',
            value_json: '{"quote":"博物馆转向公共服务"}',
            evidence_id: 'ev-1',
            source_span: 'p16:120-168',
            ordinal: 0,
            evidence: {
              evidence_id: 'ev-1',
              case_id: '',
              event_seq: 0,
              source_kind: 'event_sentence',
              source_id: 'evt-1',
              artifact_version_id: '',
              evidence_type: 'text_span',
              evidence_role: 'primary',
              methodology_framework_id: '',
              evidence_payload_json: '{"stream_id":"kb.arch.museum","event_id":"evt-1"}',
              created_by_type: 'import_pipeline',
              created_by_id: 'phase1',
              is_derived: false,
              status: 'active',
              created_at: '2026-07-24T20:00:00Z',
              updated_at: '2026-07-24T20:00:00Z',
            },
            locators: [
              {
                evidence_locator_id: 'loc-1',
                evidence_id: 'ev-1',
                locator_type: 'sentence_ref',
                page_span: '[16,17)',
                char_span: '[120,169)',
                sentence_ref_json: '{"sentence_index":3}',
                bbox_json: '',
                polygon_json: '',
                time_range: '',
                table_cell_json: '',
                measurement_field: '',
                locator_payload_json: '{}',
                normalized_text: '博物馆从藏品中心转向公共服务机构',
                preview_text: '博物馆转向公共服务',
                created_at: '2026-07-24T20:00:00Z',
              }
            ]
          }
        ]
      }),
      getOntologyFact: vi.fn(),
    });

    const service = new OntologyEvidenceService(client);
    const result = await service.getConceptEvidence({ concept_id: 'concept:museum' });

    expect(result.facts).toHaveLength(1);
    expect(result.facts[0].fact.statement_id).toBe('stmt-123');
    expect(result.facts[0].evidence[0].stream_id).toBe('kb.arch.museum');
    expect(client.getOntologyFact).not.toHaveBeenCalled();
  });
});

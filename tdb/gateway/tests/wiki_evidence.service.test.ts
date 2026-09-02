import { describe, expect, it, vi } from 'vitest';

import type { GatewayBackendClient, OntologyFactRecord, WikiPageRecord } from '../src/clients/gateway_backend.types.js';
import { WikiEvidenceService } from '../src/services/wiki_evidence.service.js';

function createMockClient(overrides: Partial<GatewayBackendClient>): GatewayBackendClient {
  return {
    getWikiPage: vi.fn(),
    searchOntologyFacts: vi.fn().mockResolvedValue([]),
    getOntologyFact: vi.fn(),
    listOntologyFactReviews: vi.fn().mockResolvedValue([]),
    listOntologyFactEvidence: vi.fn().mockResolvedValue([]),
    getSemanticStatementProvenance: vi.fn().mockResolvedValue({ references: [] }),
    getEventSentences: vi.fn().mockResolvedValue([]),
    ...overrides,
  } as unknown as GatewayBackendClient;
}

describe('WikiEvidenceService', () => {
  it('returns page-backed fact histories using exact page title matches', async () => {
    const page: WikiPageRecord = {
      page_id: 'page-1',
      domain: 'archeology_expert',
      slug: '纸草',
      title: '纸草',
      content: '# 纸草',
      page_type: 'concept',
      knowledge_level: 'concept_like',
      authority_kind: 'accepted_ontology',
      tags_json: '[]',
      source_count: 1,
      confidence: 0.9,
      last_reinforced_at: '2026-07-10T14:45:34.937406+00',
      created_at: '2026-07-09T14:32:10.641754+00',
      updated_at: '2026-07-10T14:45:34.937406+00',
      superseded_by: '',
    };
    const facts: OntologyFactRecord[] = [
      {
        fact_id: 3309,
        src_concept_id: 'src-1',
        src_concept_label: '纸草',
        predicate: 'characterized_by',
        dst_concept_id: 'dst-1',
        dst_concept_label: '书写原料',
        qualifier_json: '{}',
        confidence: 1,
        extractor: 'pipeline_relation_candidate_v1',
        status: 'accepted',
        review_note: '',
        created_at: '2026-07-10T14:11:32.189Z',
        updated_at: '2026-07-10T14:15:15.118Z',
      } as unknown as OntologyFactRecord,
      {
        fact_id: 9999,
        src_concept_id: 'src-2',
        src_concept_label: '别的概念',
        predicate: 'related',
        dst_concept_id: 'dst-2',
        dst_concept_label: '别的东西',
        qualifier_json: '{}',
        confidence: 0.7,
        extractor: 'test',
        status: 'accepted',
        review_note: '',
        created_at: '2026-07-10T14:11:32.189Z',
        updated_at: '2026-07-10T14:15:15.118Z',
      } as unknown as OntologyFactRecord,
    ];

    const client = createMockClient({
      getWikiPage: vi.fn().mockResolvedValue(page),
      searchOntologyFacts: vi.fn().mockResolvedValue(facts),
      getOntologyFact: vi.fn().mockResolvedValue(facts[0]),
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

    const service = new WikiEvidenceService(client);
    const result = await service.getPageEvidence({ domain: 'archeology_expert', slug: '纸草' });

    expect(result.page.slug).toBe('纸草');
    expect(result.facts).toHaveLength(1);
    expect(result.facts[0].fact.fact_id).toBe(3309);
    expect(result.facts[0].evidence[0].sentence?.sentence_text).toBe('纸草可用来作书写原料。');
  });

  it('uses statement provenance for wiki evidence when fact_id is 0 but statement_id exists', async () => {
    const page: WikiPageRecord = {
      page_id: 'page-2',
      domain: 'archeology_expert',
      slug: '博物馆',
      title: '博物馆',
      content: '# 博物馆',
      page_type: 'concept',
      knowledge_level: 'concept_like',
      authority_kind: 'accepted_ontology',
      tags_json: '[]',
      source_count: 1,
      confidence: 0.9,
      last_reinforced_at: '2026-07-24T20:00:00Z',
      created_at: '2026-07-24T20:00:00Z',
      updated_at: '2026-07-24T20:00:00Z',
      superseded_by: '',
    };
    const facts: OntologyFactRecord[] = [
      {
        fact_id: 0,
        statement_id: 'stmt-456',
        src_concept_id: 'src-1',
        src_concept_label: '博物馆',
        predicate: 'defined_as',
        dst_concept_id: 'dst-1',
        dst_concept_label: '公共服务机构',
        qualifier_json: '{}',
        confidence: 1,
        extractor: 'phase1_loader',
        status: 'accepted',
        review_note: '',
        created_at: '2026-07-24T20:00:00Z',
        updated_at: '2026-07-24T20:00:00Z',
      } as unknown as OntologyFactRecord,
    ];

    const client = createMockClient({
      getWikiPage: vi.fn().mockResolvedValue(page),
      searchOntologyFacts: vi.fn().mockResolvedValue(facts),
      getSemanticStatementProvenance: vi.fn().mockResolvedValue({
        references: [
          {
            statement_id: 'stmt-456',
            property_id: 'supporting_quote',
            value_type: 'json',
            value_json: '{"quote":"博物馆从藏品中心转向公共服务"}',
            evidence_id: 'ev-2',
            source_span: 'p16:120-168',
            ordinal: 0,
            evidence: {
              evidence_id: 'ev-2',
              case_id: '',
              event_seq: 0,
              source_kind: 'event_sentence',
              source_id: 'evt-2',
              artifact_version_id: '',
              evidence_type: 'text_span',
              evidence_role: 'primary',
              methodology_framework_id: '',
              evidence_payload_json: '{"stream_id":"kb.arch.museum","event_id":"evt-2"}',
              created_by_type: 'import_pipeline',
              created_by_id: 'phase1',
              is_derived: false,
              status: 'active',
              created_at: '2026-07-24T20:00:00Z',
              updated_at: '2026-07-24T20:00:00Z',
            },
            locators: [],
          }
        ]
      }),
      getOntologyFact: vi.fn(),
    });

    const service = new WikiEvidenceService(client);
    const result = await service.getPageEvidence({ domain: 'archeology_expert', slug: '博物馆' });

    expect(result.facts).toHaveLength(1);
    expect(result.facts[0].fact.statement_id).toBe('stmt-456');
    expect(result.facts[0].evidence[0].event_id).toBe('evt-2');
    expect(client.getOntologyFact).not.toHaveBeenCalled();
  });
});

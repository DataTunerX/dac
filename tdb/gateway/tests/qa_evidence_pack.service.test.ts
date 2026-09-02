import { describe, expect, it, vi } from 'vitest';

import type {
  ConceptAliasRecord,
  GatewayBackendClient,
  OntologyConceptRecord,
  OntologyFactRecord,
  WikiPageRecord,
} from '../src/clients/gateway_backend.types.js';
import { QaEvidencePackService } from '../src/services/qa_evidence_pack.service.js';

function createMockClient(overrides: Partial<GatewayBackendClient>): GatewayBackendClient {
  return {
    searchWikiPages: vi.fn().mockResolvedValue([]),
    getWikiPage: vi.fn(),
    searchOntologyFacts: vi.fn().mockResolvedValue([]),
    searchOntologyConcepts: vi.fn().mockResolvedValue([]),
    searchConceptAliases: vi.fn().mockResolvedValue([]),
    getOntologyConcept: vi.fn(),
    listOntologyFacts: vi.fn().mockResolvedValue([]),
    getOntologyFact: vi.fn(),
    listOntologyFactReviews: vi.fn().mockResolvedValue([]),
    listOntologyFactEvidence: vi.fn().mockResolvedValue([]),
    getSemanticStatementProvenance: vi.fn().mockResolvedValue({ references: [] }),
    getEventSentences: vi.fn().mockResolvedValue([]),
    ...overrides,
  } as unknown as GatewayBackendClient;
}

describe('QaEvidencePackService', () => {
  it('builds a compact evidence pack from wiki, ontology, and provenance hits', async () => {
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
    const concept: OntologyConceptRecord = {
      concept_id: 'concept:papyrus',
      canonical_name: '纸草',
      concept_type: 'concept',
      aliases_json: '["Papyrus"]',
      created_at: '2026-07-09T14:32:10.641754+00',
      updated_at: '2026-07-10T14:45:34.937406+00',
    };
    const alias: ConceptAliasRecord = {
      concept_id: 'concept:papyrus',
      alias_text: '纸草',
      confidence: 1,
      extractor: 'test',
      created_at: '2026-07-10T14:11:32.189Z',
      updated_at: '2026-07-10T14:15:15.118Z',
    };
    const fact: OntologyFactRecord = {
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

    const client = createMockClient({
      searchWikiPages: vi.fn().mockResolvedValue([page]),
      getWikiPage: vi.fn().mockResolvedValue(page),
      searchOntologyFacts: vi.fn().mockResolvedValue([fact]),
      searchOntologyConcepts: vi.fn().mockResolvedValue([concept]),
      searchConceptAliases: vi.fn().mockResolvedValue([alias]),
      getOntologyConcept: vi.fn().mockResolvedValue(concept),
      listOntologyFacts: vi
        .fn()
        .mockResolvedValueOnce([fact])
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce([fact])
        .mockResolvedValueOnce([]),
      getOntologyFact: vi.fn().mockResolvedValue(fact),
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

    const service = new QaEvidencePackService(client);
    const result = await service.buildPack({
      question: '沼泽地中盛产的纸草有哪些广泛的用途？',
      domain: 'archeology_expert',
      concept_limit: 3,
      wiki_limit: 3,
      fact_limit: 5,
      evidence_limit: 2,
    });

    expect(result.question).toContain('纸草');
    expect(result.query_variants[0].length).toBeGreaterThan(1);
    expect(result.wiki_hits).toHaveLength(1);
    expect(result.concept_hits).toHaveLength(1);
    expect(result.fact_hits).toHaveLength(1);
    expect(result.fact_hits[0].evidence[0].sentence?.sentence_text).toBe('纸草可用来作书写原料。');
  });

  it('filters weak substring-only wiki and concept matches', async () => {
    const usefulPage: WikiPageRecord = {
      page_id: 'page-1',
      domain: 'archeology_expert',
      slug: '沼泽地',
      title: '沼泽地',
      content: '# 沼泽地',
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
    const noisyPage: WikiPageRecord = {
      ...usefulPage,
      page_id: 'page-2',
      slug: '这种“阅兵宫”的用途',
      title: '这种“阅兵宫”的用途',
    };
    const usefulConcept: OntologyConceptRecord = {
      concept_id: 'concept:marsh',
      canonical_name: '沼泽地',
      concept_type: 'concept',
      aliases_json: '[]',
      created_at: '2026-07-09T14:32:10.641754+00',
      updated_at: '2026-07-10T14:45:34.937406+00',
    };
    const noisyConcept: OntologyConceptRecord = {
      concept_id: 'concept:usage',
      canonical_name: '这种“阅兵宫”的用途',
      concept_type: 'concept',
      aliases_json: '[]',
      created_at: '2026-07-09T14:32:10.641754+00',
      updated_at: '2026-07-10T14:45:34.937406+00',
    };

    const client = createMockClient({
      searchWikiPages: vi
        .fn()
        .mockResolvedValueOnce([usefulPage, noisyPage])
        .mockResolvedValue([]),
      getWikiPage: vi.fn().mockResolvedValue(usefulPage),
      searchOntologyConcepts: vi
        .fn()
        .mockResolvedValueOnce([usefulConcept, noisyConcept])
        .mockResolvedValue([]),
      searchConceptAliases: vi.fn().mockResolvedValue([]),
      getOntologyConcept: vi.fn().mockResolvedValue(usefulConcept),
      searchOntologyFacts: vi.fn().mockResolvedValue([]),
      listOntologyFacts: vi.fn().mockResolvedValue([]),
      getOntologyFact: vi.fn(),
    });

    const service = new QaEvidencePackService(client);
    const result = await service.buildPack({
      question: '沼泽地中盛产的纸草有哪些广泛的用途？',
      domain: 'archeology_expert',
      concept_limit: 5,
      wiki_limit: 5,
    });

    expect(result.wiki_hits.map((item) => item.page.slug)).toEqual(['沼泽地']);
    expect(result.concept_hits.map((item) => item.concept.canonical_name)).toEqual(['沼泽地']);
  });

  it('ranks answer-anchor concepts and facts ahead of background concepts', async () => {
    const papyrusPage: WikiPageRecord = {
      page_id: 'page-papyrus',
      domain: 'archeology_expert',
      slug: '纸草',
      title: '纸草',
      content: '# 纸草',
      page_type: 'concept',
      knowledge_level: 'concept_like',
      authority_kind: 'accepted_ontology',
      tags_json: '[]',
      source_count: 1,
      confidence: 0.85,
      last_reinforced_at: '2026-07-10T14:45:34.937406+00',
      created_at: '2026-07-09T14:32:10.641754+00',
      updated_at: '2026-07-10T14:45:34.937406+00',
      superseded_by: '',
    };
    const marshPage: WikiPageRecord = {
      ...papyrusPage,
      page_id: 'page-marsh',
      slug: '沼泽地',
      title: '沼泽地',
      confidence: 0.95,
    };
    const papyrusConcept: OntologyConceptRecord = {
      concept_id: 'concept:papyrus',
      canonical_name: '纸草',
      concept_type: 'concept',
      aliases_json: '[]',
      created_at: '2026-07-09T14:32:10.641754+00',
      updated_at: '2026-07-10T14:45:34.937406+00',
    };
    const marshConcept: OntologyConceptRecord = {
      concept_id: 'concept:marsh',
      canonical_name: '沼泽地',
      concept_type: 'concept',
      aliases_json: '[]',
      created_at: '2026-07-09T14:32:10.641754+00',
      updated_at: '2026-07-10T14:45:34.937406+00',
    };
    const papyrusFact: OntologyFactRecord = {
      fact_id: 3309,
      src_concept_id: 'concept:papyrus',
      src_concept_label: '纸草',
      predicate: 'characterized_by',
      dst_concept_id: 'concept:writing-material',
      dst_concept_label: '书写原料',
      qualifier_json: '{}',
      confidence: 1,
      extractor: 'test',
      status: 'accepted',
      review_note: '',
      created_at: '2026-07-10T14:11:32.189Z',
      updated_at: '2026-07-10T14:15:15.118Z',
    } as unknown as OntologyFactRecord;
    const marshFact: OntologyFactRecord = {
      fact_id: 3221,
      src_concept_id: 'concept:plants',
      src_concept_label: '纸草和芦苇',
      predicate: 'located_in',
      dst_concept_id: 'concept:marsh',
      dst_concept_label: '沼泽地',
      qualifier_json: '{}',
      confidence: 1,
      extractor: 'test',
      status: 'accepted',
      review_note: '',
      created_at: '2026-07-10T14:11:32.189Z',
      updated_at: '2026-07-10T14:15:15.118Z',
    } as unknown as OntologyFactRecord;

    const client = createMockClient({
      searchWikiPages: vi
        .fn()
        .mockResolvedValueOnce([papyrusPage, marshPage])
        .mockResolvedValueOnce([marshPage])
        .mockResolvedValue([]),
      getWikiPage: vi
        .fn()
        .mockResolvedValueOnce(papyrusPage)
        .mockResolvedValueOnce(marshPage),
      searchOntologyConcepts: vi
        .fn()
        .mockResolvedValueOnce([papyrusConcept, marshConcept])
        .mockResolvedValueOnce([marshConcept])
        .mockResolvedValue([]),
      searchConceptAliases: vi.fn().mockResolvedValue([]),
      getOntologyConcept: vi
        .fn()
        .mockResolvedValueOnce(papyrusConcept)
        .mockResolvedValueOnce(marshConcept),
      searchOntologyFacts: vi.fn().mockResolvedValue([marshFact, papyrusFact]),
      listOntologyFacts: vi
        .fn()
        .mockResolvedValueOnce([papyrusFact])
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce([marshFact]),
      getOntologyFact: vi.fn().mockImplementation(async ({ fact_id }: { fact_id: number }) => {
        if (fact_id === 3309) {
          return papyrusFact;
        }
        if (fact_id === 3221) {
          return marshFact;
        }
        return undefined;
      }),
      listOntologyFactEvidence: vi.fn().mockImplementation(async ({ fact_id }: { fact_id: number }) => {
        if (fact_id === 3309) {
          return [
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
          ];
        }
        if (fact_id === 3221) {
          return [
            {
              stream_id: 'stream-1',
              event_id: 'event-1',
              asset_id: '',
              version_number: 0,
              source_span: 'doc.md',
              evidence_json: JSON.stringify({ sent_index: 1 }),
              confidence: 1,
              created_at: '2026-07-10T14:11:32.189Z',
              updated_at: '2026-07-10T14:15:15.118Z',
            },
          ];
        }
        return [];
      }),
      getEventSentences: vi.fn().mockResolvedValue([
        {
          stream_id: 'stream-1',
          event_id: 'event-1',
          sent_index: 0,
          start_char: 0,
          end_char: 12,
          sentence_text: '纸草可用来作书写原料。',
        },
        {
          stream_id: 'stream-1',
          event_id: 'event-1',
          sent_index: 1,
          start_char: 13,
          end_char: 28,
          sentence_text: '纸草和芦苇生长在沼泽地中。',
        },
      ]),
    });

    const service = new QaEvidencePackService(client);
    const result = await service.buildPack({
      question: '沼泽地中盛产的纸草有哪些广泛的用途？',
      domain: 'archeology_expert',
      concept_limit: 5,
      wiki_limit: 5,
      fact_limit: 10,
      evidence_limit: 2,
    });

    expect(result.wiki_hits[0].page.slug).toBe('纸草');
    expect(result.concept_hits[0].concept.canonical_name).toBe('纸草');
    expect(result.fact_hits[0].fact.fact_id).toBe(3309);
  });

  it('prefers semantic statement provenance for direct fact hits when fact_id is 0', async () => {
    const semanticFact: OntologyFactRecord = {
      fact_id: 0,
      statement_id: 'stmt-qa-1',
      src_concept_id: 'concept:museum',
      src_concept_label: '博物馆',
      predicate: 'defined_as',
      dst_concept_id: 'concept:public-service',
      dst_concept_label: '公共服务机构',
      qualifier_json: '{}',
      confidence: 0.92,
      extractor: 'phase1_loader',
      status: 'accepted',
      review_note: '',
      created_at: '2026-07-24T20:00:00Z',
      updated_at: '2026-07-24T20:00:00Z',
    } as unknown as OntologyFactRecord;

    const client = createMockClient({
      searchWikiPages: vi.fn().mockResolvedValue([]),
      searchOntologyConcepts: vi.fn().mockResolvedValue([]),
      searchConceptAliases: vi.fn().mockResolvedValue([]),
      searchOntologyFacts: vi.fn().mockResolvedValue([semanticFact]),
      getSemanticStatementProvenance: vi.fn().mockResolvedValue({
        references: [
          {
            statement_id: 'stmt-qa-1',
            property_id: 'supporting_quote',
            value_type: 'json',
            value_json: '{"quote":"博物馆转向公共服务"}',
            evidence_id: 'ev-qa-1',
            source_span: 'p16:120-168',
            ordinal: 0,
            evidence: {
              evidence_id: 'ev-qa-1',
              case_id: '',
              event_seq: 0,
              source_kind: 'event_sentence',
              source_id: 'evt-qa-1',
              artifact_version_id: '',
              evidence_type: 'text_span',
              evidence_role: 'primary',
              methodology_framework_id: '',
              evidence_payload_json: '{"stream_id":"kb.arch.museum","event_id":"evt-qa-1"}',
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

    const service = new QaEvidencePackService(client);
    const result = await service.buildPack({
      question: '博物馆的定义发生了什么变化？',
      domain: 'archeology_expert',
      concept_limit: 5,
      wiki_limit: 5,
      fact_limit: 10,
      evidence_limit: 2,
    });

    expect(result.fact_hits).toHaveLength(1);
    expect(result.fact_hits[0].fact.statement_id).toBe('stmt-qa-1');
    expect(result.fact_hits[0].evidence[0].event_id).toBe('evt-qa-1');
    expect(client.getOntologyFact).not.toHaveBeenCalled();
  });
});

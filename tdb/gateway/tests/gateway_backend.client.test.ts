import { describe, expect, it, vi } from 'vitest';

import { createGatewayBackendClient } from '../src/clients/gateway_backend.client.js';

describe('GatewayBackendClient', () => {
  it('maps protobuf hits into the existing HTTP search hit shape', async () => {
    const transport = {
      searchQuery: vi.fn().mockResolvedValue({
        resolvedStreamIds: ['stream-a'],
        hits: [
          {
            docId: 'doc-1',
            caseId: 'case-1',
            streamId: 'stream-a',
            eventId: 'event-1',
            eventSeq: 7,
            content: 'alice reviewed the escalation packet',
            metadataJson: '{"source":"test"}',
            lexicalScore: 0.9,
            vectorScore: 0,
            hybridScore: 0.9
          }
        ]
      })
    };

    const client = createGatewayBackendClient({
      address: '127.0.0.1:50051',
      timeoutMs: 1500,
      transport: transport as never
    });

    const result = await client.searchQuery({
      query: 'alice escalation',
      stream_id: 'stream-a',
      limit: 5
    });

    expect(result).toEqual({
      resolved_stream_ids: ['stream-a'],
      hits: [
        {
          doc_id: 'doc-1',
          case_id: 'case-1',
          stream_id: 'stream-a',
          event_id: 'event-1',
          event_seq: 7,
          content: 'alice reviewed the escalation packet',
          metadata: { source: 'test' },
          lexical_score: 0.9,
          vector_score: 0,
          hybrid_score: 0.9
        }
      ]
    });
  });

  it('translates unavailable backend failures into BACKEND_UNAVAILABLE', async () => {
    const transport = {
      searchQuery: vi.fn().mockRejectedValue({
        code: 'UNAVAILABLE',
        details: 'connect failed'
      })
    };

    const client = createGatewayBackendClient({
      address: '127.0.0.1:50051',
      timeoutMs: 1500,
      transport: transport as never
    });

    await expect(
      client.searchQuery({
        query: 'alice escalation'
      })
    ).rejects.toMatchObject({
      code: 'BACKEND_UNAVAILABLE',
      statusCode: 503
    });
  });

  it('maps semantic statement get responses into the gateway client shape', async () => {
    const transport = {
      getSemanticStatement: vi.fn().mockResolvedValue({
        statement: {
          statementId: 'stmt-1',
          statementKey: 'stmt:key:1',
          subjectId: 'concept:museum',
          subjectLabel: '博物馆',
          propertyId: 'defined_as',
          valueType: 'entity',
          valueEntityId: 'concept:society-service',
          valueEntityLabel: '为社会及其发展服务的非营利的永久机构',
          valueJson: '',
          status: 'accepted',
          confidence: 0.9,
          createdBy: 'pipeline_relation_candidate_v1',
          metadataJson: '{"statement_scope":"chapter"}',
          createdAt: '2026-07-24T18:09:21Z',
          updatedAt: '2026-07-24T18:09:21Z'
        },
        qualifiers: [
          {
            statementId: 'stmt-1',
            propertyId: 'time',
            valueType: 'string',
            valueJson: '"1989年9月"',
            valueEntityId: '',
            ordinal: 0
          }
        ]
      })
    };

    const client = createGatewayBackendClient({
      address: '127.0.0.1:50051',
      timeoutMs: 1500,
      transport: transport as never
    });

    const result = await client.getSemanticStatement({
      statement_id: 'stmt-1'
    });

    expect(result).toEqual({
      statement: {
        statement_id: 'stmt-1',
        subject_concept_id: 'concept:museum',
        subject_name: '博物馆',
        predicate: 'defined_as',
        object_concept_id: 'concept:society-service',
        object_name: '为社会及其发展服务的非营利的永久机构',
        value_type: 'entity',
        value_json: {},
        status: 'accepted',
        confidence: 0.9,
        created_by: 'pipeline_relation_candidate_v1',
        metadata_json: '{"statement_scope":"chapter"}',
        provenance_json: '{}',
        created_at: '2026-07-24T18:09:21Z',
        updated_at: '2026-07-24T18:09:21Z'
      },
      qualifiers: [
        {
          // carried through from the backend row; the gateway response schema
          // marks it required, so dropping it here made every statement that
          // has qualifiers fail serialization with a 500
          statement_id: 'stmt-1',
          property_id: 'time',
          value_type: 'string',
          value_json: '1989年9月',
          value_entity_id: '',
          ordinal: 0
        }
      ]
    });
  });

  it('maps semantic statement provenance responses including evidence locators', async () => {
    const transport = {
      getSemanticStatementProvenance: vi.fn().mockResolvedValue({
        statement: {
          statementId: 'stmt-1',
          statementKey: 'stmt:key:1',
          subjectId: 'concept:museum',
          subjectLabel: '博物馆',
          propertyId: 'defined_as',
          valueType: 'entity',
          valueEntityId: 'concept:society-service',
          valueEntityLabel: '为社会及其发展服务的非营利的永久机构',
          valueJson: '',
          status: 'accepted',
          confidence: 0.9,
          createdBy: 'pipeline_relation_candidate_v1',
          metadataJson: '{"statement_scope":"chapter"}',
          createdAt: '2026-07-24T18:09:21Z',
          updatedAt: '2026-07-24T18:09:21Z'
        },
        qualifiers: [],
        references: [
          {
            statementId: 'stmt-1',
            propertyId: 'source',
            sourceSpan: '/work/input/ch04.md',
            ordinal: 0,
            evidenceId: 'evid-1',
            valueType: 'entity',
            valueJson: '',
            evidence: {
              evidenceId: 'evid-1',
              caseId: '',
              eventSeq: 0,
              sourceKind: 'open_layer_span',
              sourceId: 'e_ch04_s1_p0001',
              artifactVersionId: '',
              evidenceType: 'provenance_record',
              evidenceRole: 'primary',
              methodologyFrameworkId: '',
              evidencePayloadJson: '{"stream_id":"archaeology.phase1.fundamentals_of_chinese_museology.ch04","event_id":"71856b53-d384-4a04-a7e0-65df251531dc"}',
              createdByType: 'pipeline',
              createdById: 'load_open_layer_evidence_to_tdb',
              isDerived: false,
              status: 'active',
              createdAt: '2026-07-24T18:09:21Z',
              updatedAt: '2026-07-24T18:09:21Z'
            },
            locators: [
              {
                evidenceLocatorId: 'loc-1',
                evidenceId: 'evid-1',
                locatorType: 'text_span',
                pageSpan: '[58,59)',
                charSpan: '[120,188)',
                sentenceRefJson: '{"stream_id":"archaeology.phase1.fundamentals_of_chinese_museology.ch04","event_id":"71856b53-d384-4a04-a7e0-65df251531dc"}',
                bboxJson: '',
                polygonJson: '',
                timeRange: '',
                tableCellJson: '',
                measurementField: '',
                locatorPayloadJson: '{}',
                normalizedText: '传统的博物馆观念不能不有所变革。',
                previewText: '传统的博物馆观念不能不有所变革。',
                createdAt: '2026-07-24T18:09:21Z'
              }
            ]
          }
        ]
      })
    };

    const client = createGatewayBackendClient({
      address: '127.0.0.1:50051',
      timeoutMs: 1500,
      transport: transport as never
    });

    const result = await client.getSemanticStatementProvenance({
      statement_id: 'stmt-1',
      include_locators: true
    });

    expect(result.references[0]).toMatchObject({
      statement_id: 'stmt-1',
      evidence_id: 'evid-1',
      evidence: {
        source_kind: 'open_layer_span',
        evidence_payload: {
          stream_id: 'archaeology.phase1.fundamentals_of_chinese_museology.ch04'
        }
      },
      locators: [
        {
          locator_type: 'text_span',
          sentence_ref: {
            event_id: '71856b53-d384-4a04-a7e0-65df251531dc'
          },
          preview_text: '传统的博物馆观念不能不有所变革。'
        }
      ]
    });
  });

  it('maps current semantic statement proto field names into the gateway client shape', async () => {
    const transport = {
      getSemanticStatement: vi.fn().mockResolvedValue({
        statement: {
          statement_id: 'stmt-2',
          subject_concept_id: 'concept:canal',
          subject_name: '运河',
          predicate: 'explains',
          object_concept_id: 'concept:railway-threat',
          object_name: '运河会搞垮铁路',
          value_type: 'entity',
          value_json: '{}',
          status: 'accepted',
          confidence: 1,
          created_by: 'pipeline_relation_candidate_v1',
          metadata_json: '{"source":"semantic_projection"}',
          provenance_json: '{}',
          created_at: '2026-07-24T21:33:27Z',
          updated_at: '2026-07-24T21:33:27Z'
        },
        qualifiers: []
      })
    };

    const client = createGatewayBackendClient({
      address: '127.0.0.1:50051',
      timeoutMs: 1500,
      transport: transport as never
    });

    const result = await client.getSemanticStatement({
      statement_id: 'stmt-2'
    });

    expect(result.statement).toEqual({
      statement_id: 'stmt-2',
      subject_concept_id: 'concept:canal',
      subject_name: '运河',
      predicate: 'explains',
      object_concept_id: 'concept:railway-threat',
      object_name: '运河会搞垮铁路',
      value_type: 'entity',
      value_json: {},
      status: 'accepted',
      confidence: 1,
      created_by: 'pipeline_relation_candidate_v1',
      metadata_json: '{"source":"semantic_projection"}',
      provenance_json: '{}',
      created_at: '2026-07-24T21:33:27Z',
      updated_at: '2026-07-24T21:33:27Z'
    });
  });
});

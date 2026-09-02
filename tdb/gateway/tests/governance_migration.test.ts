import { describe, expect, it, vi } from 'vitest';
import { GovernanceService } from '../src/services/governance.service.js';
import type { 
  GatewayBackendClient,
  OntologyAlertRecord,
  OntologyCaseDecisionRecord,
  OntologyCaseRecord,
  OntologyFactRecord,
  OntologyOpsRuleConfigRecord,
  OntologyOpsRuleRunRecord
} from '../src/clients/gateway_backend.types.js';

function createMockClient(overrides: Partial<GatewayBackendClient>): GatewayBackendClient {
  return {
    getOntologyCase: vi.fn().mockResolvedValue(undefined),
    getActiveOntologyCaseByTitle: vi.fn().mockResolvedValue(undefined),
    getOntologyFact: vi.fn().mockResolvedValue(undefined),
    listOntologyFactReviews: vi.fn().mockResolvedValue([]),
    listOntologyFactEvidence: vi.fn().mockResolvedValue([]),
    listOntologyFactLinkedCases: vi.fn().mockResolvedValue([]),
    listOntologyFactLinkedAlerts: vi.fn().mockResolvedValue([]),
    getSemanticStatement: vi.fn().mockResolvedValue({ statement: undefined }),
    getSemanticStatementProvenance: vi.fn().mockResolvedValue({ statement: undefined, references: [] }),
    getEventSentences: vi.fn().mockResolvedValue([]),
    listConflictPredicateOntologyCandidates: vi.fn().mockResolvedValue([]),
    listOntologyCaseDecisions: vi.fn().mockResolvedValue([]),
    insertOntologyCase: vi.fn(),
    insertOntologyCaseDecision: vi.fn(),
    insertOntologyCaseEvent: vi.fn(),
    ...overrides
  } as unknown as GatewayBackendClient;
}

function buildConflictCandidate(): OntologyFactRecord {
  return {
    fact_id: 101,
    src_concept_id: 'product:a',
    predicate: 'supports_consistency_group_snapshot',
    dst_concept_id: 'true',
    qualifier_json: '{}',
    confidence: 0.9,
    extractor: 'test',
    status: 'accepted',
    review_note: '',
    valid_from: '2026-05-08T10:30:00Z',
    valid_to: '9999-12-31T23:59:59Z',
    created_at: '2026-05-08T10:30:00Z',
    updated_at: '2026-05-08T10:30:00Z',
    stream_id: 'storage-product-a',
    fact_count: 2,
    dst_count: 2,
    fact_ids: [101, 104],
    dst_values: ['true', 'false']
  };
}

function buildCaseRecord(overrides: Partial<OntologyCaseRecord> = {}): OntologyCaseRecord {
  return {
    case_id: 42,
    stream_id: 'storage-product-a',
    title: 'Capability conflict supports_consistency_group_snapshot for product:a',
    description: 'Existing case reused by draft flow',
    status: 'open',
    priority: 'p1',
    owner: 'storage_expert',
    created_by: 'system',
    created_at: '2026-05-08T10:30:00Z',
    updated_at: '2026-05-08T10:30:00Z',
    closed_at: '',
    ...overrides
  };
}

function buildDecisionRecord(
  overrides: Partial<OntologyCaseDecisionRecord> = {}
): OntologyCaseDecisionRecord {
  return {
    case_decision_id: 9,
    case_id: 42,
    decision_kind: 'capability_resolution_draft',
    verdict: 'needs_review',
    summary: 'product:a has conflicting supports_consistency_group_snapshot values and requires review',
    rationale:
      'Detected 2 distinct supports_consistency_group_snapshot values across 2 facts for product:a in storage-product-a; no automatic resolution rule selected a working truth.',
    as_of_system_time: '2026-05-08T10:30:00Z',
    as_of_effective_time: '2026-05-08T10:30:00Z',
    snapshot_id: '',
    source_evidence_json: '[]',
    supersedes_case_decision_id: 0,
    created_by: 'acceptance_test',
    created_at: '2026-05-08T10:30:00Z',
    ...overrides
  };
}

describe('GovernanceService Migration Verification', () => {
  it('prefers a two-sentence provenance window over unrelated dst-only fallback', async () => {
    const fact = {
      fact_id: 3221,
      src_concept_id: 'src-1',
      src_concept_label: '纸草和芦苇',
      predicate: 'located_in',
      dst_concept_id: 'dst-1',
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
      getOntologyFact: vi.fn().mockResolvedValue(fact),
      listOntologyFactReviews: vi.fn().mockResolvedValue([]),
      listOntologyFactEvidence: vi.fn().mockResolvedValue([
        {
          stream_id: 'stream-1',
          event_id: 'event-1',
          asset_id: '',
          version_number: 0,
          source_span: 'doc.md',
          evidence_json: '{}',
          confidence: 0,
          created_at: '2026-07-10T14:11:32.189Z',
          updated_at: '2026-07-10T14:15:15.118Z',
        },
      ]),
      getEventSentences: vi.fn().mockResolvedValue([
        {
          stream_id: 'stream-1',
          event_id: 'event-1',
          sent_index: 46,
          start_char: 2100,
          end_char: 2140,
          sentence_text: '在这一地区，沼泽中长满了纸草和芦苇。',
        },
        {
          stream_id: 'stream-1',
          event_id: 'event-1',
          sent_index: 47,
          start_char: 2141,
          end_char: 2200,
          sentence_text: '当地人会利用这些植物制作绳索、席垫和书写材料。',
        },
        {
          stream_id: 'stream-1',
          event_id: 'event-1',
          sent_index: 48,
          start_char: 2201,
          end_char: 2260,
          sentence_text: '这个地区以法雍为中心，在史前时期曾有广袤的湖区和沼泽地。',
        },
      ]),
    });

    const service = new GovernanceService(client);
    const result = await service.getOntologyFactHistory({ fact_id: 3221, evidence_limit: 3 });

    expect(result.evidence[0].sentence?.sent_index).toBe(46);
    expect(result.evidence[0].sentence?.sentence_text).toContain('纸草和芦苇');
  });

  it('uses semantic statement history when fact_id is 0 but statement_id is present', async () => {
    const client = createMockClient({
      getSemanticStatement: vi.fn().mockResolvedValue({
        statement: {
          statement_id: 'stmt-1',
          subject_concept_id: 'entity:museum',
          subject_name: '博物馆',
          predicate: 'defined_as',
          object_concept_id: 'concept:public_service_institution',
          object_name: '社会/公共服务机构',
          confidence: 0.97,
          created_by: 'phase1_semantic',
          status: 'accepted',
          created_at: '2026-07-24T10:00:00Z',
          updated_at: '2026-07-24T10:05:00Z'
        }
      }),
      getSemanticStatementProvenance: vi.fn().mockResolvedValue({
        statement: undefined,
        references: [
          {
            evidence: {
              evidence_id: 'ev-1',
              artifact_version_id: 'artifact-v1',
              source_id: 'evt-1',
              evidence_payload_json: JSON.stringify({
                stream_id: 'arch-book',
                event_id: 'evt-1'
              }),
              created_at: '2026-07-24T10:00:00Z',
              updated_at: '2026-07-24T10:05:00Z'
            },
            locators: [
              {
                sentence_ref_json: JSON.stringify({ sentence_index: 12 }),
                normalized_text: '书中认为，博物馆已从以藏品为中心转向以社会服务为中心。',
                preview_text: ''
              }
            ],
            source_span: 'chapter_1.md:120-145'
          }
        ]
      }),
      getEventSentences: vi.fn().mockResolvedValue([])
    });

    const service = new GovernanceService(client);
    const result = await service.getOntologyFactHistory({
      fact_id: 0,
      statement_id: 'stmt-1',
      evidence_limit: 5
    });

    expect(result.fact.fact_id).toBe(0);
    expect(result.fact.statement_id).toBe('stmt-1');
    expect(result.fact.predicate).toBe('defined_as');
    expect(result.evidence).toHaveLength(1);
    expect(result.evidence[0].stream_id).toBe('arch-book');
    expect(result.evidence[0].sentence).toEqual({
      sent_index: 12,
      sentence_text: '书中认为，博物馆已从以藏品为中心转向以社会服务为中心。'
    });
    expect(client.getOntologyFact).not.toHaveBeenCalled();
    expect(client.listOntologyFactReviews).not.toHaveBeenCalled();
    expect(client.listOntologyFactEvidence).not.toHaveBeenCalled();
  });

  it('identifies stale pending facts and creates alerts/cases correctly', async () => {
    // Mock the GatewayBackendClient with the new gRPC method signatures
    const mockClient = {
      listApplicableOntologyOpsRuleConfig: vi.fn().mockResolvedValue([
        { 
          rule_name: 'stale_pending', 
          enabled: true, 
          stale_days: 30,
          severity: 'medium'
        } as OntologyOpsRuleConfigRecord
      ]),
      listStalePendingOntologyCandidates: vi.fn().mockResolvedValue([
        { 
          stream_id: 'stream-1', 
          stale_fact_count: 2, 
          fact_ids: [1001, 1002] 
        } as unknown as OntologyFactRecord
      ]),
      listConflictPredicateOntologyCandidates: vi.fn().mockResolvedValue([]),
      getActiveOntologyCaseByTitle: vi.fn().mockResolvedValue(null),
      insertOntologyCase: vi.fn().mockResolvedValue({ 
        case_id: 5001,
        title: 'Rule stale_pending for stream-1 (> 30d)'
      } as OntologyCaseRecord),
      insertOntologyCaseEvent: vi.fn().mockResolvedValue({}),
      getActiveOntologyAlertByRuleKey: vi.fn().mockResolvedValue(null),
      insertOntologyAlert: vi.fn().mockResolvedValue({ 
        alert_id: 9001,
        case_id: 5001 
      } as OntologyAlertRecord),
      linkOntologyAlertFact: vi.fn().mockResolvedValue({}),
      insertOntologyOpsRuleRun: vi.fn().mockResolvedValue({
        run_id: 1,
        candidate_count: 1,
        created_case_count: 1,
        existing_case_count: 0,
        created_alert_count: 1,
        existing_alert_count: 0,
        started_at: new Date().toISOString(),
        finished_at: new Date().toISOString()
      } as OntologyOpsRuleRunRecord)
    } as unknown as GatewayBackendClient;

    const service = new GovernanceService(mockClient);
    
    const result = await service.runOntologyOpsRules({ 
      dry_run: false, 
      stream_id: 'stream-1' 
    });

    // Verify service output
    expect(result.candidate_count).toBe(1);
    expect(result.created_case_count).toBe(1);
    expect(result.created_alert_count).toBe(1);

    // Verify correct calls to NEW GatewayBackendClient methods
    expect(mockClient.listApplicableOntologyOpsRuleConfig).toHaveBeenCalledWith({ stream_id: 'stream-1' });
    expect(mockClient.listStalePendingOntologyCandidates).toHaveBeenCalled();
    expect(mockClient.insertOntologyCase).toHaveBeenCalled();
    expect(mockClient.insertOntologyAlert).toHaveBeenCalled();
    expect(mockClient.linkOntologyAlertFact).toHaveBeenCalledTimes(2); // For fact 1001 and 1002
    expect(mockClient.insertOntologyOpsRuleRun).toHaveBeenCalled();
  });

  it('identifies conflicting predicates and handles existing cases', async () => {
    const mockClient = {
      listApplicableOntologyOpsRuleConfig: vi.fn().mockResolvedValue([
        { 
          rule_name: 'conflict_predicate', 
          enabled: true, 
          conflict_predicate: 'has_owner',
          severity: 'high'
        } as OntologyOpsRuleConfigRecord
      ]),
      listStalePendingOntologyCandidates: vi.fn().mockResolvedValue([]),
      listConflictPredicateOntologyCandidates: vi.fn().mockResolvedValue([
        { 
          stream_id: 'stream-2', 
          src_concept_id: 'concept-A',
          dst_count: 2,
          fact_count: 2,
          fact_ids: [2001, 2002],
          dst_values: ['owner-1', 'owner-2']
        } as unknown as OntologyFactRecord
      ]),
      getActiveOntologyCaseByTitle: vi.fn().mockResolvedValue({ 
        case_id: 5002,
        title: 'Rule conflict has_owner for concept-A'
      } as OntologyCaseRecord),
      insertOntologyCase: vi.fn(),
      insertOntologyCaseEvent: vi.fn().mockResolvedValue({}),
      getActiveOntologyAlertByRuleKey: vi.fn().mockResolvedValue({
        alert_id: 9002,
        severity: 'medium',
        trigger_count: 1
      } as unknown as OntologyAlertRecord),
      refreshTriggeredOntologyAlert: vi.fn().mockResolvedValue({
        alert_id: 9002,
        severity: 'high'
      } as OntologyAlertRecord),
      linkOntologyAlertFact: vi.fn().mockResolvedValue({}),
      insertOntologyOpsRuleRun: vi.fn().mockResolvedValue({ 
        run_id: 2,
        started_at: new Date().toISOString(),
        finished_at: new Date().toISOString()
      } as OntologyOpsRuleRunRecord)
    } as unknown as GatewayBackendClient;

    const service = new GovernanceService(mockClient);
    
    await service.runOntologyOpsRules({ dry_run: false });

    // Should NOT create new case but link to existing
    expect(mockClient.insertOntologyCase).not.toHaveBeenCalled();
    expect(mockClient.getActiveOntologyAlertByRuleKey).toHaveBeenCalled();
    // Should refresh alert severity from medium to high
    expect(mockClient.refreshTriggeredOntologyAlert).toHaveBeenCalledWith(expect.objectContaining({
      alert_id: 9002,
      severity: 'high'
    }));
  });

  it('creates a draft decision on an existing case from a conflict candidate', async () => {
    const client = createMockClient({
      getOntologyCase: vi.fn().mockResolvedValue(buildCaseRecord()),
      listConflictPredicateOntologyCandidates: vi.fn().mockResolvedValue([buildConflictCandidate()]),
      listOntologyCaseDecisions: vi.fn().mockResolvedValue([]),
      insertOntologyCaseDecision: vi.fn().mockResolvedValue(buildDecisionRecord()),
      insertOntologyCaseEvent: vi.fn().mockResolvedValue({
        event_id: 1,
        case_id: 42,
        action: 'note',
        actor: 'acceptance_test',
        note: 'decision recorded: capability_resolution_draft -> needs_review',
        payload_json: '{}',
        created_at: '2026-05-08T10:30:00Z'
      })
    });

    const service = new GovernanceService(client);
    const result = await service.createConflictDraftDecision({
      case_id: 42,
      stream_id: 'storage-product-a',
      predicate: 'supports_consistency_group_snapshot',
      src_concept_id: 'product:a',
      actor: 'acceptance_test'
    });

    expect(result.created_case).toBe(false);
    expect(result.deduped).toBe(false);
    expect(result.decision?.decision_kind).toBe('capability_resolution_draft');
  });

  it('creates a new case when no case_id is provided and a title collision exists on another stream', async () => {
    const createdCase = buildCaseRecord({ case_id: 77 });
    const insertOntologyCase = vi.fn().mockResolvedValue(createdCase);
    const client = createMockClient({
      getOntologyCase: vi.fn().mockResolvedValue(createdCase),
      getActiveOntologyCaseByTitle: vi.fn().mockResolvedValue(
        buildCaseRecord({ case_id: 88, stream_id: 'storage-product-b' })
      ),
      listConflictPredicateOntologyCandidates: vi.fn().mockResolvedValue([buildConflictCandidate()]),
      listOntologyCaseDecisions: vi.fn().mockResolvedValue([]),
      insertOntologyCase,
      insertOntologyCaseDecision: vi.fn().mockResolvedValue(
        buildDecisionRecord({
          case_id: 77
        })
      ),
      insertOntologyCaseEvent: vi.fn().mockResolvedValue({
        event_id: 1,
        case_id: 77,
        action: 'note',
        actor: 'acceptance_test',
        note: 'decision recorded: capability_resolution_draft -> needs_review',
        payload_json: '{}',
        created_at: '2026-05-08T10:30:00Z'
      })
    });

    const service = new GovernanceService(client);
    const result = await service.createConflictDraftDecision({
      predicate: 'supports_consistency_group_snapshot',
      src_concept_id: 'product:a',
      actor: 'acceptance_test'
    });

    expect(insertOntologyCase).toHaveBeenCalledWith(
      expect.objectContaining({
        stream_id: 'storage-product-a',
        title: 'Capability conflict supports_consistency_group_snapshot for product:a'
      })
    );
    expect(result.created_case).toBe(true);
    expect(result.case?.case_id).toBe(77);
    expect(result.case?.stream_id).toBe('storage-product-a');
  });

  it('returns an existing matching draft without inserting a new one', async () => {
    const existingEvidence = JSON.stringify([
      {
        draft_type: 'conflict_predicate',
        stream_id: 'storage-product-a',
        src_concept_id: 'product:a',
        predicate: 'supports_consistency_group_snapshot',
        fact_ids: [101, 104],
        dst_values: ['false', 'true'],
        fact_count: 2,
        dst_count: 2,
        draft_key: 'storage-product-a|product:a|supports_consistency_group_snapshot|false,true'
      }
    ]);

    const client = createMockClient({
      getOntologyCase: vi.fn().mockResolvedValue(buildCaseRecord()),
      listConflictPredicateOntologyCandidates: vi.fn().mockResolvedValue([buildConflictCandidate()]),
      listOntologyCaseDecisions: vi.fn().mockResolvedValue([
        buildDecisionRecord({
          case_decision_id: 5,
          summary: 'existing',
          rationale: 'existing',
          source_evidence_json: existingEvidence,
          created_by: 'system'
        })
      ]),
      insertOntologyCaseDecision: vi.fn()
    });

    const service = new GovernanceService(client);
    const result = await service.createConflictDraftDecision({
      case_id: 42,
      stream_id: 'storage-product-a',
      predicate: 'supports_consistency_group_snapshot',
      src_concept_id: 'product:a'
    });

    expect(result.deduped).toBe(true);
    expect(client.insertOntologyCaseDecision).not.toHaveBeenCalled();
  });

  it('returns the computed candidate in dry-run mode without writing', async () => {
    const client = createMockClient({
      listConflictPredicateOntologyCandidates: vi.fn().mockResolvedValue([buildConflictCandidate()])
    });

    const service = new GovernanceService(client);
    const result = await service.createConflictDraftDecision({
      stream_id: 'storage-product-a',
      predicate: 'supports_consistency_group_snapshot',
      src_concept_id: 'product:a',
      dry_run: true
    });

    expect(result.case).toBeUndefined();
    expect(result.decision).toBeUndefined();
    expect(result.created_case).toBe(false);
    expect(result.deduped).toBe(false);
    expect(result.candidate.fact_ids).toEqual([101, 104]);
  });

  it('enriches ontology fact provenance evidence with sentence text', async () => {
    const client = createMockClient({
      getOntologyFact: vi.fn().mockResolvedValue({
        fact_id: 77,
        src_concept_id: 'entity:papyrus',
        src_concept_label: '纸草',
        predicate: 'characterized_by',
        dst_concept_id: 'concept:writing-material',
        dst_concept_label: '书写原料',
        qualifier_json: '{}',
        confidence: 1,
        extractor: 'pipeline_relation_candidate_v1',
        status: 'accepted',
        review_note: '',
        valid_from: '',
        valid_to: '',
        created_at: '2026-07-10T14:11:32.189Z',
        updated_at: '2026-07-10T14:15:15.118Z'
      } as unknown as OntologyFactRecord),
      listOntologyFactReviews: vi.fn().mockResolvedValue([]),
      listOntologyFactEvidence: vi.fn().mockResolvedValue([
        {
          stream_id: 'stream-1',
          event_id: 'event-1',
          asset_id: '',
          version_number: 0,
          source_span: 'ch2_ancient_egypt_full.md',
          evidence_json: JSON.stringify({ sent_index: 0 }),
          confidence: 0.95,
          created_at: '2026-07-10T14:11:32.189Z',
          updated_at: '2026-07-10T14:15:15.118Z'
        }
      ]),
      getEventSentences: vi.fn().mockResolvedValue([
        {
          stream_id: 'stream-1',
          event_id: 'event-1',
          sent_index: 0,
          start_char: 0,
          end_char: 18,
          sentence_text: '纸草可用来作书写原料。'
        }
      ]),
      listOntologyFactLinkedCases: vi.fn().mockResolvedValue([]),
      listOntologyFactLinkedAlerts: vi.fn().mockResolvedValue([])
    });

    const service = new GovernanceService(client);
    const result = await service.getOntologyFactProvenance({ fact_id: 77 });

    expect(result.evidence).toHaveLength(1);
    expect(result.evidence[0].sentence).toEqual({
      sent_index: 0,
      start_char: 0,
      end_char: 18,
      sentence_text: '纸草可用来作书写原料。'
    });
    expect(client.getEventSentences).toHaveBeenCalledWith({ stream_id: 'stream-1', limit: 2000 });
  });

  it('falls back to event-level sentence text when evidence_json has no sent_index', async () => {
    const client = createMockClient({
      getOntologyFact: vi.fn().mockResolvedValue({
        fact_id: 88,
        src_concept_id: 'entity:papyrus',
        src_concept_label: '纸草',
        predicate: 'characterized_by',
        dst_concept_id: 'concept:writing-material',
        dst_concept_label: '书写原料',
        qualifier_json: '{}',
        confidence: 1,
        extractor: 'pipeline_relation_candidate_v1',
        status: 'accepted',
        review_note: '',
        valid_from: '',
        valid_to: '',
        created_at: '2026-07-10T14:11:32.189Z',
        updated_at: '2026-07-10T14:15:15.118Z'
      } as unknown as OntologyFactRecord),
      listOntologyFactReviews: vi.fn().mockResolvedValue([]),
      listOntologyFactEvidence: vi.fn().mockResolvedValue([
        {
          stream_id: 'stream-legacy',
          event_id: 'event-legacy',
          asset_id: '',
          version_number: 0,
          source_span: 'ch2_ancient_egypt_full.md',
          evidence_json: JSON.stringify({}),
          confidence: 0,
          created_at: '2026-07-10T14:11:32.189Z',
          updated_at: '2026-07-10T14:15:15.118Z'
        }
      ]),
      getEventSentences: vi.fn().mockResolvedValue([
        {
          stream_id: 'stream-legacy',
          event_id: 'event-legacy',
          sent_index: 0,
          start_char: 0,
          end_char: 11,
          sentence_text: '纸草盛产于沼泽地。'
        },
        {
          stream_id: 'stream-legacy',
          event_id: 'event-legacy',
          sent_index: 1,
          start_char: 11,
          end_char: 29,
          sentence_text: '可用来作书写原料、织布、编席，还可以入食。'
        }
      ]),
      listOntologyFactLinkedCases: vi.fn().mockResolvedValue([]),
      listOntologyFactLinkedAlerts: vi.fn().mockResolvedValue([])
    });

    const service = new GovernanceService(client);
    const result = await service.getOntologyFactProvenance({ fact_id: 88 });

    expect(result.evidence).toHaveLength(1);
    expect(result.evidence[0].evidence_json.sentence_selection).toBe('event_fallback');
    expect(result.evidence[0].sentence).toEqual({
      sent_index: 0,
      start_char: 0,
      end_char: 29,
      sentence_text: '纸草盛产于沼泽地。 可用来作书写原料、织布、编席，还可以入食。'
    });
  });

  it('uses semantic statement provenance when fact_id is 0 and omits legacy linked lookups', async () => {
    const client = createMockClient({
      getSemanticStatement: vi.fn().mockResolvedValue({
        statement: {
          statement_id: 'stmt-2',
          subject_concept_id: 'entity:museum',
          subject_name: '博物馆',
          predicate: 'implies',
          object_concept_id: 'concept:management_public_oriented',
          object_name: '管理应面向公众服务',
          confidence: 0.93,
          created_by: 'phase1_semantic',
          status: 'accepted',
          created_at: '2026-07-24T10:10:00Z',
          updated_at: '2026-07-24T10:15:00Z'
        }
      }),
      getSemanticStatementProvenance: vi.fn().mockResolvedValue({
        statement: undefined,
        references: [
          {
            evidence: {
              evidence_id: 'ev-2',
              artifact_version_id: 'artifact-v2',
              source_id: 'evt-2',
              evidence_payload_json: JSON.stringify({
                stream_id: 'arch-book',
                event_id: 'evt-2'
              }),
              created_at: '2026-07-24T10:10:00Z',
              updated_at: '2026-07-24T10:15:00Z'
            },
            locators: [
              {
                sentence_ref_json: JSON.stringify({ sentence_index: 21 }),
                normalized_text: '这意味着博物馆管理不能只重藏品保管，还要强化教育、传播与公众责任。',
                preview_text: ''
              }
            ],
            source_span: 'chapter_1.md:180-205'
          }
        ]
      }),
      getEventSentences: vi.fn().mockResolvedValue([])
    });

    const service = new GovernanceService(client);
    const result = await service.getOntologyFactProvenance({
      fact_id: 0,
      statement_id: 'stmt-2',
      evidence_limit: 5
    });

    expect(result.fact.statement_id).toBe('stmt-2');
    expect(result.evidence).toHaveLength(1);
    expect(result.linked_cases).toEqual([]);
    expect(result.linked_alerts).toEqual([]);
    expect(client.listOntologyFactLinkedCases).not.toHaveBeenCalled();
    expect(client.listOntologyFactLinkedAlerts).not.toHaveBeenCalled();
  });

  it('listOntologyOpsRuleConfig returns count matching the configs (issue #31)', async () => {
    const record: OntologyOpsRuleConfigRecord = {
      config_id: 7,
      stream_id: 'archaeology.phase1.demo.ch01',
      rule_name: 'stale_fact',
      enabled: true,
      stale_days: 30,
      conflict_predicate: 'located_at',
      severity: 'warn',
      note: '',
      updated_by: 'tester',
      updated_at: '2026-08-03T00:00:00Z'
    };
    const client = createMockClient({
      listOntologyOpsRuleConfig: vi.fn().mockResolvedValue([record])
    });
    const service = new GovernanceService(client);

    const result = await service.listOntologyOpsRuleConfig({ stream_id: 'archaeology.phase1.demo.ch01' });

    expect(result.count).toBe(1);
    expect(result.configs).toHaveLength(1);
    expect(result.stream_id_filter).toBe('archaeology.phase1.demo.ch01');
  });

  it('listOntologyOpsRuleConfig returns count 0 for zero configs (issue #31 500 repro)', async () => {
    const client = createMockClient({
      listOntologyOpsRuleConfig: vi.fn().mockResolvedValue([])
    });
    const service = new GovernanceService(client);

    const result = await service.listOntologyOpsRuleConfig({});

    // Missing `count` is what tripped Fastify response serialization -> HTTP 500.
    expect(result.count).toBe(0);
    expect(result.configs).toEqual([]);
  });
});

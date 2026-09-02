import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import net from 'node:net';
import { fileURLToPath } from 'node:url';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { DatabasePool } from 'slonik';
import { sql } from '../src/db/sql.js';
import { createDbPool } from '../src/db/pool.js';

import { buildApp } from '../src/app.js';

const TEST_DB_URL = process.env.TEST_DATABASE_URL ?? process.env.DATABASE_URL;
const describeDb = TEST_DB_URL ? describe : describe.skip;
const MIGRATE_SCRIPT_PATH = fileURLToPath(new URL('../../scripts/db_migrate.sh', import.meta.url));
const PHASED_PLAN_SAMPLE_PATH = fileURLToPath(
  new URL('../../docs/query_plan_ingest_phased.sample.json', import.meta.url)
);
const BUSINESS_LOOP_PLAN_SAMPLE_PATH = fileURLToPath(
  new URL('../../docs/query_plan_examples/06_decision_replay_business_loop.json', import.meta.url)
);
const REPO_ROOT = fileURLToPath(new URL('../..', import.meta.url));
const GATEWAY_BACKEND_ADDR = '127.0.0.1:50071';

describeDb('v2 acceptance behaviors', () => {
  let app: Awaited<ReturnType<typeof buildApp>>;
  let db: DatabasePool;
  let backendProc: ChildProcess | undefined;

  beforeAll(async () => {
    execFileSync(
      'psql',
      [
        TEST_DB_URL!,
        '-v',
        'ON_ERROR_STOP=1',
        '-c',
        'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
      ],
      { stdio: 'pipe' }
    );
    execFileSync(MIGRATE_SCRIPT_PATH, [], {
      env: {
        ...process.env,
        DATABASE_URL: TEST_DB_URL!,
        TDB_MIGRATION_PROFILE: 'full'
      },
      stdio: 'pipe'
    });

    backendProc = spawn('cargo', ['run', '--bin', 'tdb_gateway_backend'], {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        DATABASE_URL: TEST_DB_URL!,
        TDB_GATEWAY_BACKEND_ADDR: GATEWAY_BACKEND_ADDR,
        TDB_ENABLE_PGVECTOR: 'false'
      },
      stdio: 'pipe'
    });
    await waitForPort('127.0.0.1', 50071);

    db = await createDbPool(TEST_DB_URL!);
    app = await buildApp({
      logLevel: 'silent',
      backend: {
        address: GATEWAY_BACKEND_ADDR,
        timeoutMs: 3000
      }
    });
  });

  afterAll(async () => {
    if (db) {
      await db.end();
    }
    if (app) {
      await app.close();
    }
    if (backendProc && backendProc.exitCode === null) {
      backendProc.kill('SIGTERM');
    }
  });

  async function seedConflictDraftFixture(): Promise<{
    streamId: string;
    srcConceptId: string;
  }> {
    const streamId = `conflict-draft-${randomUUID()}`;
    const srcConceptId = `product-${randomUUID()}`;

    const objectType = await app.inject({
      method: 'POST',
      url: '/v2/ontology/object-type/upsert',
      payload: {
        type_id: 'entity',
        display_name: 'Entity'
      }
    });
    expect(objectType.statusCode).toBe(201);

    const relationType = await app.inject({
      method: 'POST',
      url: '/v2/ontology/relation-type/upsert',
      payload: {
        predicate: 'supports_consistency_group_snapshot',
        src_type_id: 'entity',
        dst_type_id: 'entity',
        display_name: 'Supports Consistency Group Snapshot'
      }
    });
    expect(relationType.statusCode).toBe(201);

    const append = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        stream_id: streamId,
        event_type: 'fact_observed',
        payload: {
          session_id: 'conflict-draft-sess',
          text: 'Conflicting capability facts seeded for conflict draft acceptance coverage.'
        },
        event_text: 'Conflicting capability facts seeded for conflict draft acceptance coverage.',
        valid_time: '2026-04-12T00:00:00Z'
      }
    });
    expect(append.statusCode).toBe(201);
    const eventId = append.json().event_id as string;

    await db.query(sql.typeAlias('void')`
      INSERT INTO ontology_concept (concept_id, canonical_name, concept_type)
      VALUES
        (${srcConceptId}, 'Storage Product A', 'entity'),
        ('capability:true', 'Consistency Group Snapshot Enabled', 'entity'),
        ('capability:false', 'Consistency Group Snapshot Disabled', 'entity')
      ON CONFLICT (concept_id) DO NOTHING
    `);

    for (const [dst, confidence, label] of [
      ['capability:true', 0.83, 'a'],
      ['capability:false', 0.79, 'b']
    ] as const) {
      const factRow = await db.one(sql.typeAlias('record')`
        INSERT INTO ontology_fact (
          src_concept_id,
          predicate,
          dst_concept_id,
          qualifier_json,
          confidence,
          extractor,
          status
        ) VALUES (
          ${srcConceptId},
          'supports_consistency_group_snapshot',
          ${dst},
          '{}'::jsonb,
          ${confidence},
          'acceptance_test',
          'accepted'
        )
        RETURNING fact_id::text
      `);
      const factId = Number((factRow as Record<string, unknown>).fact_id);
      await db.query(sql.typeAlias('void')`
        INSERT INTO ontology_fact_evidence (
          fact_id,
          stream_id,
          event_id,
          source_span,
          evidence_json,
          confidence
        ) VALUES (
          ${factId},
          ${streamId},
          ${eventId},
          '0:64',
          ${JSON.stringify({ sent_index: 0, text_hash: `conflict-draft-${label}`, seg_version: 'v1' })}::jsonb,
          0.9
        )
      `);
    }

    return { streamId, srcConceptId };
  }

  it('bitemporal property as-of reflects as_of_system_time', async () => {
    const objectId = randomUUID();
    const validFrom = '2026-02-01T00:00:00Z';

    const first = await app.inject({
      method: 'POST',
      url: '/v2/state/property/upsert',
      payload: {
        object_id: objectId,
        key: 'status',
        value: { value: 'draft' },
        valid_from: validFrom,
        system_from: '2026-02-01T00:00:01Z'
      }
    });
    expect(first.statusCode).toBe(201);

    const second = await app.inject({
      method: 'POST',
      url: '/v2/state/property/upsert',
      payload: {
        object_id: objectId,
        key: 'status',
        value: { value: 'approved' },
        valid_from: validFrom,
        system_from: '2026-02-01T00:00:10Z'
      }
    });
    expect(second.statusCode).toBe(201);

    const asOfEarly = await app.inject({
      method: 'GET',
      url: `/v2/state/property/asof?object_id=${objectId}&key=status&as_of_valid_time=2026-02-01T00:00:20Z&as_of_system_time=2026-02-01T00:00:05Z`
    });
    expect(asOfEarly.statusCode).toBe(200);
    expect(asOfEarly.json().property.value.value).toBe('draft');

    const asOfLate = await app.inject({
      method: 'GET',
      url: `/v2/state/property/asof?object_id=${objectId}&key=status&as_of_valid_time=2026-02-01T00:00:20Z&as_of_system_time=2026-02-01T00:00:20Z`
    });
    expect(asOfLate.statusCode).toBe(200);
    expect(asOfLate.json().property.value.value).toBe('approved');
  });

  it('decision evidence keeps referenced artifact version stable', async () => {
    const artifactRes = await app.inject({
      method: 'POST',
      url: '/v2/artifact/create',
      payload: { artifact_type: 'policy', name: `policy-${randomUUID()}` }
    });
    expect(artifactRes.statusCode).toBe(201);
    const artifactId = artifactRes.json().artifact_id as string;

    const v1 = await app.inject({
      method: 'POST',
      url: '/v2/artifact/version/create',
      payload: {
        artifact_id: artifactId,
        version_number: 1,
        status: 'approved',
        valid_from: '2026-01-01T00:00:00Z',
        content_ref: 's3://bucket/policy-v1'
      }
    });
    expect(v1.statusCode).toBe(201);

    const v2 = await app.inject({
      method: 'POST',
      url: '/v2/artifact/version/create',
      payload: {
        artifact_id: artifactId,
        version_number: 2,
        status: 'approved',
        valid_from: '2026-02-01T00:00:00Z',
        content_ref: 's3://bucket/policy-v2'
      }
    });
    expect(v2.statusCode).toBe(201);

    const caseId = randomUUID();
    const decision = await app.inject({
      method: 'POST',
      url: '/v2/decision/create',
      payload: {
        case_id: caseId,
        event_seq: 1,
        projection_version: 'v1',
        chosen_action: 'allow'
      }
    });
    expect(decision.statusCode).toBe(201);
    const decisionId = decision.json().decision_id as string;

    const attach = await app.inject({
      method: 'POST',
      url: '/v2/decision/evidence/attach',
      payload: {
        decision_id: decisionId,
        artifact_version_id: v1.json().artifact_version_id,
        citation: { section: '1.2' }
      }
    });
    expect(attach.statusCode).toBe(201);

    const get = await app.inject({
      method: 'GET',
      url: `/v2/decision/get?case_id=${caseId}&event_seq=1&projection_version=v1`
    });
    expect(get.statusCode).toBe(200);
    expect(get.json().evidence).toHaveLength(1);
    expect(get.json().evidence[0].artifact_version_id).toBe(v1.json().artifact_version_id);
    expect(get.json().evidence[0].artifact_version_id).not.toBe(v2.json().artifact_version_id);
  });

  it('ontology concept upsert/get/list works through gateway backend rpc', async () => {
    const conceptId = `concept-${randomUUID()}`;

    const upsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/concept/upsert',
      payload: {
        concept_id: conceptId,
        canonical_name: 'Worcester Plant',
        concept_type: 'location',
        aliases: ['Worcester factory', 'Plant Worcester']
      }
    });
    expect(upsert.statusCode).toBe(201);
    expect(upsert.json().concept_id).toBe(conceptId);

    const get = await app.inject({
      method: 'GET',
      url: `/v2/ontology/concept/get?concept_id=${conceptId}`
    });
    expect(get.statusCode).toBe(200);
    expect(get.json().concept?.concept_id).toBe(conceptId);
    expect(get.json().concept?.canonical_name).toBe('Worcester Plant');

    const list = await app.inject({
      method: 'GET',
      url: '/v2/ontology/concept/list?concept_type=location&q=Worcester&limit=10'
    });
    expect(list.statusCode).toBe(200);
    expect(
      (list.json().concepts as Array<{ concept_id: string }>).some((item) => item.concept_id === conceptId)
    ).toBe(true);
  });

  it('ontology concept object-type assignment upsert/list works through gateway backend rpc', async () => {
    const conceptId = `concept-${randomUUID()}`;

    const concept = await app.inject({
      method: 'POST',
      url: '/v2/ontology/concept/upsert',
      payload: {
        concept_id: conceptId,
        canonical_name: '龙泉青瓷',
        concept_type: 'entity',
        aliases: []
      }
    });
    expect(concept.statusCode).toBe(201);

    const objectType = await app.inject({
      method: 'POST',
      url: '/v2/ontology/object-type/upsert',
      payload: {
        type_id: 'ware',
        display_name: 'Ware',
        description: 'Ceramics ware concept',
        enabled: true
      }
    });
    expect(objectType.statusCode).toBe(201);

    const upsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/concept-type-assignment/upsert',
      payload: {
        domain: 'ceramics',
        concept_id: conceptId,
        object_type_id: 'ware',
        assignment_status: 'accepted',
        source_kind: 'concept_typing_artifact',
        confidence: 0.96,
        metadata: {
          candidate_label: '龙泉青瓷'
        }
      }
    });
    expect(upsert.statusCode).toBe(201);
    expect(upsert.json().concept_id).toBe(conceptId);
    expect(upsert.json().object_type_id).toBe('ware');

    const list = await app.inject({
      method: 'GET',
      url: `/v2/ontology/concept-type-assignment/list?domain=ceramics&concept_id=${conceptId}&object_type_id=ware&assignment_status=accepted&limit=10`
    });
    expect(list.statusCode).toBe(200);
    expect(list.json().assignments).toHaveLength(1);
    expect(list.json().assignments[0].concept_id).toBe(conceptId);
    expect(list.json().assignments[0].object_type_id).toBe('ware');
    expect(list.json().assignments[0].assignment_status).toBe('accepted');
  });

  it('ontology fact upsert-with-evidence supports search, neighbors, and archive', async () => {
    const srcConceptId = `concept-src-${randomUUID()}`;
    const dstConceptId = `concept-dst-${randomUUID()}`;

    for (const payload of [
      {
        type_id: 'entity',
        display_name: 'Entity'
      },
      {
        type_id: 'location',
        display_name: 'Location'
      }
    ]) {
      const res = await app.inject({
        method: 'POST',
        url: '/v2/ontology/object-type/upsert',
        payload
      });
      expect(res.statusCode).toBe(201);
    }

    const relationType = await app.inject({
      method: 'POST',
      url: '/v2/ontology/relation-type/upsert',
      payload: {
        predicate: 'occurs_at',
        src_type_id: 'entity',
        dst_type_id: 'location',
        display_name: 'Occurs At'
      }
    });
    expect(relationType.statusCode).toBe(201);

    for (const payload of [
      {
        concept_id: srcConceptId,
        canonical_name: 'Sensor A',
        concept_type: 'entity',
        aliases: ['sensor-a']
      },
      {
        concept_id: dstConceptId,
        canonical_name: 'Line 1',
        concept_type: 'location',
        aliases: ['line-1']
      }
    ]) {
      const res = await app.inject({
        method: 'POST',
        url: '/v2/ontology/concept/upsert',
        payload
      });
      expect(res.statusCode).toBe(201);
    }

    const factWrite = await app.inject({
      method: 'POST',
      url: '/v2/ontology/fact/upsert-with-evidence',
      payload: {
        src_concept_id: srcConceptId,
        predicate: 'occurs_at',
        dst_concept_id: dstConceptId,
        qualifier: { source: 'manual' },
        confidence: 0.92,
        extractor: 'manual_review',
        status: 'accepted',
        review_note: 'operator confirmed',
        evidence: [
          {
            stream_id: 'manufacturing-demo',
            event_id: `event-${randomUUID()}`,
            source_span: 'Sensor A occurs at Line 1',
            evidence: { sent_index: 0, start_char: 0, end_char: 25 },
            confidence: 0.92
          }
        ]
      }
    });
    expect(factWrite.statusCode).toBe(201);
    const factId = factWrite.json().fact.fact_id as number;

    const factSearch = await app.inject({
      method: 'GET',
      url: `/v2/ontology/fact/search?predicate=occurs_at&stream_id=manufacturing-demo&limit=10`
    });
    expect(factSearch.statusCode).toBe(200);
    expect((factSearch.json().facts as Array<{ fact_id: number }>).some((item) => item.fact_id === factId)).toBe(true);

    const neighborRes = await app.inject({
      method: 'GET',
      url: `/v2/ontology/concept/neighbors?concept_id=${srcConceptId}&direction=out&limit=10`
    });
    expect(neighborRes.statusCode).toBe(200);
    expect(
      (neighborRes.json().neighbors as Array<{ predicate: string; neighbor_concept_id: string }>).some(
        (item) => item.predicate === 'occurs_at' && item.neighbor_concept_id === dstConceptId
      )
    ).toBe(true);

    const archiveRes = await app.inject({
      method: 'POST',
      url: '/v2/ontology/fact/archive',
      payload: {
        fact_id: factId,
        reviewer: 'gateway-test',
        note: 'archived by test'
      }
    });
    expect(archiveRes.statusCode).toBe(200);

    const archivedGet = await app.inject({
      method: 'GET',
      url: `/v2/ontology/fact/get?fact_id=${factId}`
    });
    expect(archivedGet.statusCode).toBe(200);
    expect(archivedGet.json().fact?.status).toBe('rejected');
  });

  it('semantic-only statements expose statement_id and provenance through v2 APIs', async () => {
    const suffix = randomUUID();
    const subjectConceptId = `concept-museum-${suffix}`;
    const objectConceptId = `concept-public-service-${suffix}`;
    const streamId = `semantic-${suffix}`;
    const eventId = `evt-${suffix}`;
    const statementKey = `stmt-key-${suffix}`;

    const subjectConcept = await app.inject({
      method: 'POST',
      url: '/v2/ontology/concept/upsert',
      payload: {
        concept_id: subjectConceptId,
        canonical_name: '博物馆',
        concept_type: 'entity',
        aliases: ['Museum']
      }
    });
    expect(subjectConcept.statusCode).toBe(201);

    const objectConcept = await app.inject({
      method: 'POST',
      url: '/v2/ontology/concept/upsert',
      payload: {
        concept_id: objectConceptId,
        canonical_name: '公共服务机构',
        concept_type: 'entity',
        aliases: []
      }
    });
    expect(objectConcept.statusCode).toBe(201);

    const relationType = await app.inject({
      method: 'POST',
      url: '/v2/ontology/relation-type/upsert',
      payload: {
        predicate: 'defined_as',
        src_type_id: 'entity',
        dst_type_id: 'entity',
        display_name: 'Defined As'
      }
    });
    expect(relationType.statusCode).toBe(201);

    const evidenceUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ledger/evidence/upsert',
      payload: {
        source_kind: 'event_sentence',
        source_id: eventId,
        evidence_type: 'text_span',
        evidence_role: 'primary',
        evidence_payload: {
          stream_id: streamId,
          event_id: eventId,
          quote: '博物馆从藏品中心机构转向公共服务机构'
        },
        created_by_type: 'import_pipeline',
        created_by_id: 'phase1',
        status: 'active'
      }
    });
    expect(evidenceUpsert.statusCode).toBe(201);
    const evidenceId = evidenceUpsert.json().evidence_id as string;

    const locatorUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ledger/evidence/locator/upsert',
      payload: {
        evidence_id: evidenceId,
        locator_type: 'sentence_ref',
        page_span: '[16,17)',
        char_span: '[120,169)',
        sentence_ref: { page: 16, sentence_index: 3 },
        locator_payload: { chapter: 'ch16' },
        normalized_text: '博物馆从藏品中心机构转向公共服务机构',
        preview_text: '博物馆转向公共服务'
      }
    });
    expect(locatorUpsert.statusCode).toBe(201);

    const semanticUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/semantic/upsert-batch',
      payload: {
        entities: [
          {
            entity_id: subjectConceptId,
            entity_kind: 'item',
            semantic_role: 'concept',
            namespace: 'acceptance_test',
            status: 'active',
            metadata_json: {}
          },
          {
            entity_id: objectConceptId,
            entity_kind: 'item',
            semantic_role: 'concept',
            namespace: 'acceptance_test',
            status: 'active',
            metadata_json: {}
          },
          {
            entity_id: 'defined_as',
            entity_kind: 'property',
            semantic_role: 'object_property',
            namespace: 'acceptance_test',
            status: 'active',
            property_datatype: 'entity',
            metadata_json: {}
          },
          {
            entity_id: 'supporting_quote',
            entity_kind: 'property',
            semantic_role: 'annotation_property',
            namespace: 'acceptance_test',
            status: 'active',
            property_datatype: 'json',
            metadata_json: {}
          }
        ],
        statements: [
          {
            statement_key: statementKey,
            subject_id: subjectConceptId,
            property_id: 'defined_as',
            value_type: 'entity',
            value_entity_id: objectConceptId,
            value_json: {},
            status: 'accepted',
            confidence: 0.91,
            created_by: 'phase1_loader',
            metadata_json: { loader: 'phase1' }
          }
        ],
        qualifiers: [],
        references: [
          {
            statement_key: statementKey,
            property_id: 'supporting_quote',
            value_type: 'json',
            value_json: { quote: '博物馆从藏品中心机构转向公共服务机构' },
            evidence_id: evidenceId,
            source_span: 'p16:120-168',
            ordinal: 0
          }
        ]
      }
    });
    expect(semanticUpsert.statusCode).toBe(201);
    expect(semanticUpsert.json().semantic_statement_count).toBe(1);

    const factSearch = await app.inject({
      method: 'GET',
      url: `/v2/ontology/fact/search?predicate=defined_as&stream_id=${streamId}&limit=10`
    });
    expect(factSearch.statusCode).toBe(200);
    const facts = factSearch.json().facts as Array<{
      fact_id: number;
      statement_id?: string;
      src_concept_id: string;
    }>;
    expect(facts).toHaveLength(1);
    expect(facts[0].fact_id).toBe(0);
    expect(facts[0].statement_id).toBeTruthy();
    expect(facts[0].src_concept_id).toBe(subjectConceptId);
    const statementId = facts[0].statement_id as string;

    const statementGet = await app.inject({
      method: 'GET',
      url: `/v2/ontology/statement/get?statement_id=${statementId}`
    });
    expect(statementGet.statusCode).toBe(200);
    expect(statementGet.json().statement).toMatchObject({
      statement_id: statementId,
      subject_concept_id: subjectConceptId,
      predicate: 'defined_as',
      object_concept_id: objectConceptId
    });

    const statementProvenance = await app.inject({
      method: 'GET',
      url: `/v2/ontology/statement/provenance?statement_id=${statementId}&include_locators=true&evidence_limit=10`
    });
    expect(statementProvenance.statusCode).toBe(200);
    const references = statementProvenance.json().references as Array<{
      evidence_id?: string;
      locators: Array<{ preview_text?: string }>;
    }>;
    expect(references).toHaveLength(1);
    expect(references[0].evidence_id).toBe(evidenceId);
    expect(references[0].locators[0].preview_text).toBe('博物馆转向公共服务');

    const evidenceStatements = await app.inject({
      method: 'GET',
      url: `/v2/ledger/evidence/statements?evidence_id=${evidenceId}&include_locators=true&limit=10`
    });
    expect(evidenceStatements.statusCode).toBe(200);
    const reverseReferences = evidenceStatements.json().references as Array<{
      statement_id: string;
      evidence_id?: string;
    }>;
    expect(reverseReferences).toHaveLength(1);
    expect(reverseReferences[0].statement_id).toBe(statementId);
    expect(reverseReferences[0].evidence_id).toBe(evidenceId);
  });

  it('term mapping registry CRUD and interpret work through gateway backend rpc', async () => {
    const registryUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/term-mapping/registry/upsert',
      payload: {
        domain: 'ceramics',
        registry_name: 'antique_expert_query_zh',
        version_label: 'v1',
        status: 'active',
        description: 'Ceramics query interpretation registry',
        owner: 'antique_expert',
        metadata: {
          locale: 'zh-CN'
        }
      }
    });
    expect(registryUpsert.statusCode).toBe(201);
    const registryId = registryUpsert.json().registry_id as string;

    const registryGet = await app.inject({
      method: 'GET',
      url: `/v2/ontology/term-mapping/registry/get?registry_id=${registryId}`
    });
    expect(registryGet.statusCode).toBe(200);
    expect(registryGet.json().registry?.domain).toBe('ceramics');

    const registryList = await app.inject({
      method: 'GET',
      url: '/v2/ontology/term-mapping/registry/list?domain=ceramics&status=active&limit=10'
    });
    expect(registryList.statusCode).toBe(200);
    expect(
      (registryList.json().registries as Array<{ registry_id: string }>).some(
        (item) => item.registry_id === registryId
      )
    ).toBe(true);

    const ruleUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/term-mapping/rule/upsert',
      payload: {
        registry_id: registryId,
        raw_term: '花口',
        language: 'zh',
        context_hint: 'ceramics query',
        term_type: 'shape_feature',
        normalization_status: 'ambiguous',
        canonical_term: '葵口',
        is_compound: false,
        split_rule: {},
        semantic_slot: 'form_feature',
        json_targets: ['identification.form_features[]'],
        ontology_target_kind: 'concept',
        ambiguity_flag: true,
        ambiguity_note: 'Often overlaps with lobed or floral rim wording.',
        review_status: 'reviewed',
        confidence: 0.72,
        metadata: {
          source: 'acceptance-test'
        }
      }
    });
    expect(ruleUpsert.statusCode).toBe(201);
    const ruleId = ruleUpsert.json().rule_id as string;

    const ruleGet = await app.inject({
      method: 'GET',
      url: `/v2/ontology/term-mapping/rule/get?rule_id=${ruleId}`
    });
    expect(ruleGet.statusCode).toBe(200);
    expect(ruleGet.json().rule?.raw_term).toBe('花口');
    expect(ruleGet.json().rule?.canonical_term).toBe('葵口');

    const ruleSearch = await app.inject({
      method: 'GET',
      url: `/v2/ontology/term-mapping/rule/search?registry_id=${registryId}&q=%E8%8A%B1&term_type=shape_feature&limit=10`
    });
    expect(ruleSearch.statusCode).toBe(200);
    expect(
      (ruleSearch.json().rules as Array<{ rule_id: string }>).some((item) => item.rule_id === ruleId)
    ).toBe(true);

    const artifactRes = await app.inject({
      method: 'POST',
      url: '/v2/artifact/create',
      payload: { artifact_type: 'catalog_page', name: `catalog-${randomUUID()}` }
    });
    expect(artifactRes.statusCode).toBe(201);
    const artifactId = artifactRes.json().artifact_id as string;

    const evidenceUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/term-mapping/rule-evidence/upsert',
      payload: {
        rule_id: ruleId,
        artifact_id: artifactId,
        source_span: '器作花口',
        note: 'Museum catalog wording uses 花口 for this vessel rim.',
        confidence: 0.81,
        evidence: {
          page: 12
        }
      }
    });
    expect(evidenceUpsert.statusCode).toBe(201);

    const evidenceList = await app.inject({
      method: 'GET',
      url: `/v2/ontology/term-mapping/rule-evidence/list?rule_id=${ruleId}&limit=10`
    });
    expect(evidenceList.statusCode).toBe(200);
    expect(evidenceList.json().evidence).toHaveLength(1);
    expect(evidenceList.json().evidence[0].artifact_id).toBe(artifactId);

    const interpret = await app.inject({
      method: 'GET',
      url: `/v2/ontology/term-mapping/interpret?registry_id=${registryId}&raw_term=%E8%8A%B1%E5%8F%A3&language=zh`
    });
    expect(interpret.statusCode).toBe(200);
    expect(interpret.json().interpretation?.raw_term).toBe('花口');
    expect(interpret.json().interpretation?.canonical_term).toBe('葵口');
    expect(interpret.json().interpretation?.ambiguity_flag).toBe(true);

    const interpretBatch = await app.inject({
      method: 'POST',
      url: '/v2/ontology/term-mapping/interpret-batch',
      payload: {
        registry_id: registryId,
        raw_terms: ['花口', '未知词'],
        language: 'zh'
      }
    });
    expect(interpretBatch.statusCode).toBe(200);
    expect(interpretBatch.json().interpretations).toHaveLength(2);
    expect(interpretBatch.json().interpretations[0].raw_term).toBe('花口');
    expect(interpretBatch.json().interpretations[0].matched_rule_id).toBe(ruleId);
    expect(interpretBatch.json().interpretations[1].raw_term).toBe('未知词');
    expect(interpretBatch.json().interpretations[1].matched_rule_id).toBeUndefined();
  });

  it('ontology raw term ingestion CRUD works through gateway backend rpc', async () => {
    const conceptId = `concept-${randomUUID()}`;
    const conceptUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/concept/upsert',
      payload: {
        concept_id: conceptId,
        canonical_name: '青釉',
        concept_type: 'entity',
        aliases: ['青瓷釉']
      }
    });
    expect(conceptUpsert.statusCode).toBe(201);

    const evidenceRes = await app.inject({
      method: 'POST',
      url: '/v2/ledger/evidence/upsert',
      payload: {
        source_kind: 'external_report',
        source_id: 'collection/95.json',
        evidence_type: 'text_span',
        evidence_role: 'primary',
        created_by_type: 'import_pipeline',
        created_by_id: 'acceptance-test',
        is_derived: false,
        status: 'active'
      }
    });
    expect(evidenceRes.statusCode).toBe(201);
    const evidenceId = evidenceRes.json().evidence_id as string;

    const rawTermUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/raw-term/upsert',
      payload: {
        domain: 'ceramics',
        raw_term: '青釉',
        language: 'zh',
        normalized_hint: '青釉',
        term_type_hint: 'glaze',
        source_kind: 'dossier_term_candidate',
        source_ref: 'collection/95.json#term_candidates[0]',
        evidence_id: evidenceId,
        context_text: '条目中把青釉作为候选术语写入 dossier。',
        context_locator: {
          field: 'term_candidates',
          index: 0
        },
        extracted_by_type: 'import_pipeline',
        extracted_by_id: 'acceptance-test',
        status: 'new',
        metadata: {
          source: 'acceptance-test'
        }
      }
    });
    expect(rawTermUpsert.statusCode).toBe(201);
    const rawTermId = rawTermUpsert.json().raw_term_id as string;
    expect(rawTermUpsert.json().evidence_id).toBe(evidenceId);
    expect(rawTermUpsert.json().artifact_version_id).toBeUndefined();

    const rawTermGet = await app.inject({
      method: 'GET',
      url: `/v2/ontology/raw-term/get?raw_term_id=${rawTermId}`
    });
    expect(rawTermGet.statusCode).toBe(200);
    expect(rawTermGet.json().raw_term?.raw_term).toBe('青釉');
    expect(rawTermGet.json().raw_term?.context_locator.field).toBe('term_candidates');

    const rawTermSearch = await app.inject({
      method: 'GET',
      url: '/v2/ontology/raw-term/search?domain=ceramics&q=%E9%9D%92%E9%87%89&term_type_hint=glaze&limit=10'
    });
    expect(rawTermSearch.statusCode).toBe(200);
    expect(
      (rawTermSearch.json().raw_terms as Array<{ raw_term_id: string }>).some(
        (item) => item.raw_term_id === rawTermId
      )
    ).toBe(true);

    const candidateUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/raw-term/candidate/upsert',
      payload: {
        raw_term_id: rawTermId,
        candidate_label: '青釉',
        candidate_concept_id: conceptId,
        candidate_object_type: 'glaze',
        candidate_relation_type: 'same_as',
        confidence: 0.92,
        candidate_status: 'accepted',
        review_note: 'Matches existing glaze concept.',
        metadata: {
          source: 'acceptance-test'
        }
      }
    });
    expect(candidateUpsert.statusCode).toBe(201);

    const candidateList = await app.inject({
      method: 'GET',
      url: `/v2/ontology/raw-term/candidate/list?raw_term_id=${rawTermId}&candidate_status=accepted&limit=10`
    });
    expect(candidateList.statusCode).toBe(200);
    expect(candidateList.json().candidates).toHaveLength(1);
    expect(candidateList.json().candidates[0].candidate_concept_id).toBe(conceptId);
  });

  it('ontology normalized term and clustering CRUD works through gateway backend rpc', async () => {
    const clusterUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/normalized-term/cluster/upsert',
      payload: {
        domain: 'ceramics',
        cluster_type: 'same_family',
        proposed_canonical: '天目',
        proposed_type: 'vessel_form',
        cluster_status: 'auto',
        member_count: 0,
        source_support_count: 2,
        confidence: 0.72,
        metadata: { source: 'acceptance-test' }
      }
    });
    expect(clusterUpsert.statusCode).toBe(201);
    const clusterId = clusterUpsert.json().cluster_id as string;

    const normalizedUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/normalized-term/upsert',
      payload: {
        domain: 'ceramics',
        normalized_surface: '曜变天目',
        normalized_type: 'vessel_form',
        merge_key: '天目|曜变',
        type_confidence: 0.83,
        head_term: '天目',
        modifier_terms: ['曜变'],
        canonical_candidate_label: '天目',
        primary_cluster_id: clusterId,
        source_support_count: 2,
        is_promotable: false,
        normalization_status: 'ambiguous',
        metadata: { source: 'acceptance-test' }
      }
    });
    expect(normalizedUpsert.statusCode).toBe(201);
    const normalizedTermId = normalizedUpsert.json().normalized_term_id as string;

    const clusterMemberUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/normalized-term/cluster-member/upsert',
      payload: {
        cluster_id: clusterId,
        normalized_term_id: normalizedTermId,
        member_role: 'candidate_canonical',
        membership_confidence: 0.9,
        added_by: 'acceptance-test',
        note: 'Seeded by acceptance test.'
      }
    });
    expect(clusterMemberUpsert.statusCode).toBe(201);

    const rawTermUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/raw-term/upsert',
      payload: {
        domain: 'ceramics',
        raw_term: '曜变天目',
        language: 'zh',
        normalized_hint: '曜变天目',
        term_type_hint: 'vessel_form',
        source_kind: 'baseline_txt',
        source_ref: 'wiki_china.txt#line=88',
        context_text: '曜变天目作为特殊茶碗样式出现。',
        context_locator: { line: 88 },
        extracted_by_type: 'import_pipeline',
        extracted_by_id: 'acceptance-test',
        status: 'new',
        metadata: { source: 'acceptance-test' }
      }
    });
    expect(rawTermUpsert.statusCode).toBe(201);
    const rawTermId = rawTermUpsert.json().raw_term_id as string;

    const mappingUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/normalized-term/raw-term-mapping/upsert',
      payload: {
        raw_term_id: rawTermId,
        normalized_term_id: normalizedTermId,
        mapping_confidence: 0.88,
        mapping_type: 'surface_normalized',
        mapping_status: 'auto',
        component_role: '',
        normalization_rule: 'surface-normalize-v1',
        note: 'Direct surface normalization.',
        metadata: { source: 'acceptance-test' }
      }
    });
    expect(mappingUpsert.statusCode).toBe(201);

    const normalizedGet = await app.inject({
      method: 'GET',
      url: `/v2/ontology/normalized-term/get?normalized_term_id=${normalizedTermId}`
    });
    expect(normalizedGet.statusCode).toBe(200);
    expect(normalizedGet.json().normalized_term?.head_term).toBe('天目');

    const normalizedSearch = await app.inject({
      method: 'GET',
      url: '/v2/ontology/normalized-term/search?domain=ceramics&q=%E5%A4%A9%E7%9B%AE&normalization_status=ambiguous&limit=10'
    });
    expect(normalizedSearch.statusCode).toBe(200);
    expect(
      (normalizedSearch.json().normalized_terms as Array<{ normalized_term_id: string }>).some(
        (item) => item.normalized_term_id === normalizedTermId
      )
    ).toBe(true);

    const normalizedNaturalKeyUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/normalized-term/upsert',
      payload: {
        normalized_term_id: randomUUID(),
        domain: 'ceramics',
        normalized_surface: '曜变天目',
        normalized_type: 'vessel_form',
        merge_key: '天目|曜变',
        type_confidence: 0.91,
        head_term: '天目',
        modifier_terms: ['曜变'],
        canonical_candidate_label: '曜变天目',
        primary_cluster_id: clusterId,
        source_support_count: 3,
        is_promotable: false,
        normalization_status: 'reviewed',
        metadata: { source: 'acceptance-test-natural-key' }
      }
    });
    expect(normalizedNaturalKeyUpsert.statusCode).toBe(201);
    expect(normalizedNaturalKeyUpsert.json().normalized_term_id).toBe(normalizedTermId);
    expect(normalizedNaturalKeyUpsert.json().normalization_status).toBe('reviewed');

    const clusterGet = await app.inject({
      method: 'GET',
      url: `/v2/ontology/normalized-term/cluster/get?cluster_id=${clusterId}`
    });
    expect(clusterGet.statusCode).toBe(200);
    expect(clusterGet.json().cluster?.proposed_canonical).toBe('天目');

    const clusterMemberList = await app.inject({
      method: 'GET',
      url: `/v2/ontology/normalized-term/cluster-member/list?cluster_id=${clusterId}&limit=10`
    });
    expect(clusterMemberList.statusCode).toBe(200);
    expect(clusterMemberList.json().members).toHaveLength(1);
    expect(clusterMemberList.json().members[0].normalized_term_id).toBe(normalizedTermId);

    const mappingList = await app.inject({
      method: 'GET',
      url: `/v2/ontology/normalized-term/raw-term-mapping/list?raw_term_id=${rawTermId}&limit=10`
    });
    expect(mappingList.statusCode).toBe(200);
    expect(mappingList.json().mappings).toHaveLength(1);
    expect(mappingList.json().mappings[0].normalized_term_id).toBe(normalizedTermId);

    const mappingNaturalKeyUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/normalized-term/raw-term-mapping/upsert',
      payload: {
        mapping_id: randomUUID(),
        raw_term_id: rawTermId,
        normalized_term_id: normalizedTermId,
        mapping_confidence: 0.92,
        mapping_type: 'surface_normalized',
        mapping_status: 'reviewed',
        component_role: '',
        normalization_rule: 'surface-normalize-v2',
        note: 'Natural-key idempotent update.',
        metadata: { source: 'acceptance-test-natural-key' }
      }
    });
    expect(mappingNaturalKeyUpsert.statusCode).toBe(201);
    expect(mappingNaturalKeyUpsert.json().mapping_id).toBe(mappingList.json().mappings[0].mapping_id);
    expect(mappingNaturalKeyUpsert.json().mapping_status).toBe('reviewed');
  });

  it('ontology relation candidate CRUD works through gateway backend rpc', async () => {
    const subject = await app.inject({
      method: 'POST',
      url: '/v2/ontology/concept/upsert',
      payload: {
        concept_id: `concept-${randomUUID()}`,
        canonical_name: '青花瓷',
        concept_type: 'entity',
        aliases: []
      }
    });
    expect(subject.statusCode).toBe(201);

    const object = await app.inject({
      method: 'POST',
      url: '/v2/ontology/concept/upsert',
      payload: {
        concept_id: `concept-${randomUUID()}`,
        canonical_name: '青花',
        concept_type: 'entity',
        aliases: []
      }
    });
    expect(object.statusCode).toBe(201);

    const relationUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/relation-candidate/upsert',
      payload: {
        domain: 'ceramics',
        subject_label: '青花瓷',
        relation_type: 'has_decoration',
        object_label: '青花',
        subject_concept_id: subject.json().concept_id,
        object_concept_id: object.json().concept_id,
        candidate_status: 'auto',
        source_kind: 'concept_surface_rule',
        confidence: 0.95,
        metadata: { source: 'acceptance-test' }
      }
    });
    expect(relationUpsert.statusCode).toBe(201);
    const relationCandidateId = relationUpsert.json().relation_candidate_id as string;
    expect(relationUpsert.json().subject_concept_id).toBe(subject.json().concept_id);

    const relationNaturalKeyUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/relation-candidate/upsert',
      payload: {
        relation_candidate_id: randomUUID(),
        domain: 'ceramics',
        subject_label: '青花瓷',
        relation_type: 'has_decoration',
        object_label: '青花',
        subject_concept_id: subject.json().concept_id,
        object_concept_id: object.json().concept_id,
        candidate_status: 'accepted',
        source_kind: 'concept_surface_rule',
        confidence: 0.97,
        metadata: { source: 'acceptance-test-natural-key' }
      }
    });
    expect(relationNaturalKeyUpsert.statusCode).toBe(201);
    expect(relationNaturalKeyUpsert.json().relation_candidate_id).toBe(relationCandidateId);
    expect(relationNaturalKeyUpsert.json().candidate_status).toBe('accepted');

    const relationList = await app.inject({
      method: 'GET',
      url: '/v2/ontology/relation-candidate/list?domain=ceramics&relation_type=has_decoration&subject_label=%E9%9D%92%E8%8A%B1%E7%93%B7&object_label=%E9%9D%92%E8%8A%B1&limit=10'
    });
    expect(relationList.statusCode).toBe(200);
    expect(relationList.json().relation_candidates).toHaveLength(1);
    expect(relationList.json().relation_candidates[0].relation_candidate_id).toBe(relationCandidateId);
    expect(relationList.json().relation_candidates[0].candidate_status).toBe('accepted');

    const relationListLargeOffset = await app.inject({
      method: 'GET',
      url: '/v2/ontology/relation-candidate/list?domain=ceramics&limit=10&offset=10200'
    });
    expect(relationListLargeOffset.statusCode).toBe(200);
    expect(relationListLargeOffset.json().relation_candidates).toEqual([]);
  });

  it('methodology layer CRUD and bundle work through gateway backend rpc', async () => {
    const frameworkUpsert = await app.inject({
      method: 'POST',
      url: '/v2/governance/methodology/framework/upsert',
      payload: {
        domain: 'antique',
        framework_name: 'archaeology_v1',
        version_label: 'v1',
        status: 'active',
        description: 'Archaeology methodology baseline',
        owner: 'antique_expert',
        question_types: ['classification', 'chronology', 'comparison'],
        metadata: { locale: 'zh-CN' }
      }
    });
    expect(frameworkUpsert.statusCode).toBe(201);
    const frameworkId = frameworkUpsert.json().framework_id as string;

    const frameworkGet = await app.inject({
      method: 'GET',
      url: `/v2/governance/methodology/framework/get?framework_id=${frameworkId}`
    });
    expect(frameworkGet.statusCode).toBe(200);
    expect(frameworkGet.json().framework?.framework_name).toBe('archaeology_v1');

    const schemeUpsert = await app.inject({
      method: 'POST',
      url: '/v2/governance/methodology/taxonomy-scheme/upsert',
      payload: {
        framework_id: frameworkId,
        scheme_name: 'ceramics_shape_features',
        scheme_type: 'controlled_vocabulary',
        status: 'active',
        canonical_source: 'museum_catalog',
        scheme: { top_level: ['葵口', '花口'] },
        metadata: { phase: 'bootstrap' }
      }
    });
    expect(schemeUpsert.statusCode).toBe(201);

    const evidencePolicyUpsert = await app.inject({
      method: 'POST',
      url: '/v2/governance/methodology/evidence-policy/upsert',
      payload: {
        framework_id: frameworkId,
        rule_key: 'museum_catalog_primary',
        question_type: 'classification',
        evidence_kind: 'museum_catalog',
        source_tier: 'tier1',
        status: 'active',
        priority: 10,
        review_required: false,
        applicability: { object_scope: 'ceramics' },
        effect: { weight: 'high' },
        description: 'Museum catalog evidence counts as primary classification support.'
      }
    });
    expect(evidencePolicyUpsert.statusCode).toBe(201);

    const assertionPolicyUpsert = await app.inject({
      method: 'POST',
      url: '/v2/governance/methodology/assertion-policy/upsert',
      payload: {
        framework_id: frameworkId,
        rule_key: 'comparison_only_guardrail',
        assertion_type: 'classification_assertion',
        question_type: 'comparison',
        status: 'active',
        priority: 20,
        review_required: true,
        required_evidence: { minimum_core_sources: 1 },
        outcome: { strongest_allowed_status: 'comparison_only' },
        description: 'Comparison evidence alone cannot be promoted to accepted fact.'
      }
    });
    expect(assertionPolicyUpsert.statusCode).toBe(201);

    const reviewPolicyUpsert = await app.inject({
      method: 'POST',
      url: '/v2/governance/methodology/review-policy/upsert',
      payload: {
        framework_id: frameworkId,
        policy_key: 'high_ambiguity_requires_human',
        question_type: 'classification',
        trigger_kind: 'ambiguity_threshold',
        action: 'human_review',
        status: 'active',
        priority: 5,
        trigger: { ambiguity_flag: true, min_confidence: 0.8 },
        description: 'Ambiguous mappings must be reviewed by a human.'
      }
    });
    expect(reviewPolicyUpsert.statusCode).toBe(201);

    const bundle = await app.inject({
      method: 'GET',
      url: `/v2/governance/methodology/framework/bundle?framework_id=${frameworkId}`
    });
    expect(bundle.statusCode).toBe(200);
    expect(bundle.json().framework?.framework_id).toBe(frameworkId);
    expect(bundle.json().taxonomy_schemes).toHaveLength(1);
    expect(bundle.json().evidence_policy_rules).toHaveLength(1);
    expect(bundle.json().assertion_policy_rules).toHaveLength(1);
    expect(bundle.json().review_policies).toHaveLength(1);
  });

  it('assertion layer CRUD works through gateway backend rpc', async () => {
    const frameworkUpsert = await app.inject({
      method: 'POST',
      url: '/v2/governance/methodology/framework/upsert',
      payload: {
        domain: 'antique',
        framework_name: `assertion-test-${randomUUID()}`,
        version_label: 'v1',
        status: 'active',
        question_types: ['classification']
      }
    });
    expect(frameworkUpsert.statusCode).toBe(201);
    const frameworkId = frameworkUpsert.json().framework_id as string;

    const memoryDecisionRes = await app.inject({
      method: 'POST',
      url: '/v2/memory/decision/record',
      payload: {
        topic_id: `assertion-topic-${randomUUID()}`,
        run_id: `run-${randomUUID()}`,
        decision: 'Use museum catalog as supporting evidence.',
        rationale: 'This decision anchors the evidence path for the assertion test.',
        source_evidence: [{ source_type: 'artifact', source_id: randomUUID() }],
        entity_ids: [],
        confidence: 0.9,
        author: { type: 'agent', id: 'gateway-test' },
        timestamp: '2026-01-01T00:00:00Z',
        metadata: {},
        idempotency_key: `idem-${randomUUID()}`
      }
    });
    expect(memoryDecisionRes.statusCode).toBe(201);
    const memoryDecisionId = memoryDecisionRes.json().decision_id as string;

    const assertionUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ledger/assertion/upsert',
      payload: {
        subject_type: 'artifact',
        subject_id: randomUUID(),
        predicate: 'has_shape_feature',
        object_type: 'vocabulary_term',
        object_literal: { term: '葵口' },
        assertion_type: 'classification',
        asserted_by_type: 'model',
        asserted_by_id: 'antique_expert',
        confidence: 0.72,
        status: 'active',
        methodology_framework_id: frameworkId,
        metadata: { source: 'acceptance-test' }
      }
    });
    expect(assertionUpsert.statusCode).toBe(201);
    const assertionId = assertionUpsert.json().assertion_id as string;

    const assertionGet = await app.inject({
      method: 'GET',
      url: `/v2/ledger/assertion/get?assertion_id=${assertionId}`
    });
    expect(assertionGet.statusCode).toBe(200);
    expect(assertionGet.json().assertion?.predicate).toBe('has_shape_feature');

    const assertionSearch = await app.inject({
      method: 'GET',
      url: '/v2/ledger/assertion/search?assertion_type=classification&status=active&limit=10'
    });
    expect(assertionSearch.statusCode).toBe(200);
    expect(
      (assertionSearch.json().assertions as Array<{ assertion_id: string }>).some(
        (item) => item.assertion_id === assertionId
      )
    ).toBe(true);

    const evidenceId = execFileSync(
      'psql',
      [
        TEST_DB_URL!,
        '-Atqc',
        `
        INSERT INTO evidence_record (
          case_id,
          event_seq,
          source_kind,
          source_id,
          evidence_type,
          evidence_role,
          created_by_type,
          created_by_id,
          evidence_payload
        ) VALUES (
          NULL,
          NULL,
          'model_observation',
          'memory-decision:${memoryDecisionId}',
          'model_observation',
          'derived',
          'system',
          'acceptance-test',
          '${JSON.stringify({ memory_decision_id: memoryDecisionId })}'::jsonb
        )
        RETURNING evidence_id::text;
        `
      ],
      { encoding: 'utf8' }
    ).trim();

    const evidenceUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ledger/assertion/evidence/upsert',
      payload: {
        assertion_id: assertionId,
        evidence_id: evidenceId,
        memory_decision_id: memoryDecisionId,
        support_type: 'supports',
        weight: 0.9,
        note: 'Catalog page supports the feature claim.',
        evidence: { page: 8, span: '葵口碗' }
      }
    });
    expect(evidenceUpsert.statusCode).toBe(201);

    const evidenceList = await app.inject({
      method: 'GET',
      url: `/v2/ledger/assertion/evidence/list?assertion_id=${assertionId}&limit=10`
    });
    expect(evidenceList.statusCode).toBe(200);
    expect(evidenceList.json().evidence_links).toHaveLength(1);
    expect(evidenceList.json().evidence_links[0].evidence_id).toBeTruthy();
    expect(evidenceList.json().evidence_links[0].memory_decision_id).toBe(memoryDecisionId);

    const secondAssertionUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ledger/assertion/upsert',
      payload: {
        subject_type: 'artifact',
        subject_id: randomUUID(),
        predicate: 'has_shape_feature',
        object_type: 'vocabulary_term',
        object_literal: { term: '花口' },
        assertion_type: 'dispute',
        asserted_by_type: 'human',
        asserted_by_id: 'reviewer',
        confidence: 0.5,
        status: 'disputed'
      }
    });
    expect(secondAssertionUpsert.statusCode).toBe(201);
    const secondAssertionId = secondAssertionUpsert.json().assertion_id as string;

    const relationUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ledger/assertion/relation/upsert',
      payload: {
        from_assertion_id: secondAssertionId,
        to_assertion_id: assertionId,
        relation_type: 'contradicts',
        metadata: { note: 'Reviewer disputes the first claim.' }
      }
    });
    expect(relationUpsert.statusCode).toBe(201);

    const relationList = await app.inject({
      method: 'GET',
      url: `/v2/ledger/assertion/relation/list?assertion_id=${assertionId}&direction=both&limit=10`
    });
    expect(relationList.statusCode).toBe(200);
    expect(relationList.json().relations).toHaveLength(1);
    expect(relationList.json().relations[0].relation_type).toBe('contradicts');
  });

  it('evidence layer CRUD works through gateway backend rpc', async () => {
    const evidenceUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ledger/evidence/upsert',
      payload: {
        source_kind: 'external_report',
        source_id: 'report:catalog-111',
        evidence_type: 'text_span',
        evidence_role: 'primary',
        created_by_type: 'human',
        created_by_id: 'cataloger',
        evidence_payload: { quote: '南宋青白釉葵口盘' }
      }
    });
    expect(evidenceUpsert.statusCode).toBe(201);
    const evidenceId = evidenceUpsert.json().evidence_id as string;

    const evidenceGet = await app.inject({
      method: 'GET',
      url: `/v2/ledger/evidence/get?evidence_id=${evidenceId}`
    });
    expect(evidenceGet.statusCode).toBe(200);
    expect(evidenceGet.json().evidence?.source_kind).toBe('external_report');

    const evidenceSearch = await app.inject({
      method: 'GET',
      url: '/v2/ledger/evidence/search?source_kind=external_report&limit=10'
    });
    expect(evidenceSearch.statusCode).toBe(200);
    expect(
      (evidenceSearch.json().evidence as Array<{ evidence_id: string }>).some(
        (item) => item.evidence_id === evidenceId
      )
    ).toBe(true);

    const locatorUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ledger/evidence/locator/upsert',
      payload: {
        evidence_id: evidenceId,
        locator_type: 'page_span',
        page_span: '[8,9)',
        locator_payload: { page_label: '8' },
        preview_text: '南宋青白釉葵口盘'
      }
    });
    expect(locatorUpsert.statusCode).toBe(201);

    const locatorList = await app.inject({
      method: 'GET',
      url: `/v2/ledger/evidence/locator/list?evidence_id=${evidenceId}&limit=10`
    });
    expect(locatorList.statusCode).toBe(200);
    expect(locatorList.json().locators).toHaveLength(1);
    expect(locatorList.json().locators[0].page_span).toBe('[8,9)');

    const parentEvidenceUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ledger/evidence/upsert',
      payload: {
        source_kind: 'artifact_version',
        source_id: 'artifact-version:seed-parent',
        evidence_type: 'expert_note',
        created_by_type: 'system',
        created_by_id: 'acceptance-test',
        evidence_payload: { note: 'parent evidence' }
      }
    });
    expect(parentEvidenceUpsert.statusCode).toBe(201);
    const parentEvidenceId = parentEvidenceUpsert.json().evidence_id as string;

    const derivationUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ledger/evidence/derivation/upsert',
      payload: {
        child_evidence_id: evidenceId,
        parent_evidence_id: parentEvidenceId,
        derivation_type: 'extracted_from',
        method: 'manual_extract',
        run_id: 'acceptance-1',
        derivation_metadata: { reviewer: 'qa' }
      }
    });
    expect(derivationUpsert.statusCode).toBe(201);

    const derivationList = await app.inject({
      method: 'GET',
      url: `/v2/ledger/evidence/derivation/list?evidence_id=${evidenceId}&direction=parents&limit=10`
    });
    expect(derivationList.statusCode).toBe(200);
    expect(derivationList.json().derivations).toHaveLength(1);
    expect(derivationList.json().derivations[0].parent_evidence_id).toBe(parentEvidenceId);

    const classificationUpsert = await app.inject({
      method: 'POST',
      url: '/v2/ledger/evidence/classification/upsert',
      payload: {
        evidence_id: evidenceId,
        source_reliability_tier: 'E2',
        evidence_strength_tier: 'strong',
        evidence_modality: 'text',
        institutional_trust_class: 'museum_catalog',
        is_primary_source: true,
        is_machine_generated: false,
        requires_human_validation: false,
        classification_status: 'accepted',
        metadata: { note: 'catalog transcription' }
      }
    });
    expect(classificationUpsert.statusCode).toBe(201);

    const classificationGet = await app.inject({
      method: 'GET',
      url: `/v2/ledger/evidence/classification/get?evidence_id=${evidenceId}`
    });
    expect(classificationGet.statusCode).toBe(200);
    expect(classificationGet.json().classification?.classification_status).toBe('accepted');
  });

  it('memory decision record persists and deduplicates by idempotency_key', async () => {
    const legacyCaseId = randomUUID();
    const payload = {
      topic_id: `topic-${randomUUID()}`,
      run_id: `run-${randomUUID()}`,
      decision: 'Use wttr.in as the primary weather source.',
      rationale: 'It returned concise weather text and satisfied the task requirements.',
      alternatives_considered: ['weather.com page fetch', 'search then fetch'],
      source_evidence: [{ url: 'https://wttr.in/Boston?lang=zh-cn&format=4' }],
      entity_ids: ['city:boston', 'source:wttr.in'],
      confidence: 0.87,
      author: { type: 'agent', id: 'dac' },
      idempotency_key: `idem-${randomUUID()}`,
      legacy_decision: {
        case_id: legacyCaseId,
        event_seq: 7,
        projection_version: 'weather-v1',
        chosen_action: 'use_wttr_in',
        candidates: [
          { action: 'use_wttr_in' },
          { action: 'use_weather_dot_com' },
        ],
        scores: {
          use_wttr_in: 0.87,
          use_weather_dot_com: 0.31,
        },
        constraints_hit: ['needs_concise_text'],
        detail: {
          source_url: 'https://wttr.in/Boston?lang=zh-cn&format=4',
          rationale_summary: 'Preferred for concise weather text.',
        },
      },
    };

    const first = await app.inject({
      method: 'POST',
      url: '/v2/memory/decision/record',
      payload,
    });
    expect(first.statusCode).toBe(201);
    expect(first.json().status).toBe('recorded');
    expect(first.json().deduplicated).toBe(false);

    const second = await app.inject({
      method: 'POST',
      url: '/v2/memory/decision/record',
      payload,
    });
    expect(second.statusCode).toBe(201);
    expect(second.json().status).toBe('deduplicated');
    expect(second.json().deduplicated).toBe(true);
    expect(second.json().decision_id).toBe(first.json().decision_id);

    const legacyDecision = await db.maybeOne(sql.typeAlias('record')`
      SELECT
        decision_id::text,
        case_id::text,
        event_seq,
        projection_version,
        chosen_action,
        scores
      FROM decision_record
      WHERE case_id = ${legacyCaseId}::uuid
        AND event_seq = 7
        AND projection_version = 'weather-v1'
      LIMIT 1
    `);
    expect(legacyDecision).toBeTruthy();
    expect((legacyDecision as Record<string, unknown>).chosen_action).toBe('use_wttr_in');
    expect((legacyDecision as Record<string, unknown>).projection_version).toBe('weather-v1');
  });

  it('get_entity_state resolves entity_ref and returns durable and inferred state', async () => {
    const entity = await app.inject({
      method: 'POST',
      url: '/v2/entity/upsert',
      payload: {
        entity_type: 'city',
        display_name: 'Boston',
        external_refs: {
          canonical_ref: 'city:boston',
          country: 'United States',
          region: 'Massachusetts',
        },
      },
    });
    expect(entity.statusCode).toBe(201);

    const recordDecision = await app.inject({
      method: 'POST',
      url: '/v2/memory/decision/record',
      payload: {
        topic_id: `topic-${randomUUID()}`,
        run_id: `run-${randomUUID()}`,
        decision: 'Treat wttr.in as the preferred Boston weather source.',
        rationale: 'It returns concise text suitable for downstream reasoning.',
        source_evidence: [{ url: 'https://wttr.in/Boston?lang=zh-cn&format=4' }],
        entity_ids: ['city:boston'],
        confidence: 0.82,
        metadata: {
          inferred_state: {
            preferred_weather_source: {
              value: 'wttr.in',
              confidence: 0.82,
            },
          },
        },
      },
    });
    expect(recordDecision.statusCode).toBe(201);

    const response = await app.inject({
      method: 'POST',
      url: '/v2/memory/entity/state/get',
      payload: {
        entity_ref: {
          type: 'city',
          name: 'Boston',
        },
        include: {
          durable_state: true,
          last_observed_state: true,
          inferred_state: true,
          provenance: true,
        },
        max_supporting_evidence: 5,
      },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().entity.display_name).toBe('Boston');
    expect(response.json().entity.entity_type).toBe('city');
    expect(response.json().entity.canonical_ref).toBe('city:boston');
    expect(response.json().durable_state.country.value).toBe('United States');
    expect(response.json().durable_state.region.value).toBe('Massachusetts');
    expect(response.json().inferred_state.preferred_weather_source.value).toBe('wttr.in');
    expect(response.json().supporting_evidence).toHaveLength(1);
    expect(response.json().supporting_evidence[0].url).toBe('https://wttr.in/Boston?lang=zh-cn&format=4');
  });

  it('upsert_entity_state creates and updates durable state via memory API', async () => {
    const create = await app.inject({
      method: 'POST',
      url: '/v2/memory/entity/state/upsert',
      payload: {
        entity_ref: {
          type: 'city',
          name: 'San Francisco',
        },
        durable_state: {
          canonical_ref: 'city:san-francisco',
          country: 'United States',
          region: 'California',
          preferred_weather_source: 'wttr.in',
        },
      },
    });

    expect(create.statusCode).toBe(201);
    expect(create.json().status).toBe('created');
    expect(create.json().canonical_ref).toBe('city:san-francisco');
    expect(typeof create.json().entity_id).toBe('string');

    const update = await app.inject({
      method: 'POST',
      url: '/v2/memory/entity/state/upsert',
      payload: {
        entity_ref: {
          type: 'city',
          name: 'San Francisco',
        },
        durable_state: {
          canonical_ref: 'city:san-francisco',
          region: 'CA',
          timezone: 'America/Los_Angeles',
        },
      },
    });

    expect(update.statusCode).toBe(201);
    expect(update.json().status).toBe('updated');
    expect(update.json().entity_id).toBe(create.json().entity_id);

    const state = await app.inject({
      method: 'POST',
      url: '/v2/memory/entity/state/get',
      payload: {
        entity_ref: {
          type: 'city',
          name: 'San Francisco',
        },
      },
    });

    expect(state.statusCode).toBe(200);
    expect(state.json().entity.canonical_ref).toBe('city:san-francisco');
    expect(state.json().durable_state.country.value).toBe('United States');
    expect(state.json().durable_state.region.value).toBe('CA');
    expect(state.json().durable_state.timezone.value).toBe('America/Los_Angeles');
    expect(state.json().durable_state.preferred_weather_source.value).toBe('wttr.in');
  });

  it('records, recalls, and validates a system1 answer artifact via memory API', async () => {
    const topicId = `topic-${randomUUID()}`;
    const runId = `run-${randomUUID()}`;

    const decision = await app.inject({
      method: 'POST',
      url: '/v2/memory/decision/record',
      payload: {
        topic_id: topicId,
        run_id: runId,
        decision: 'WO-00071 is currently in progress.',
        rationale: 'This was the latest known work order status at answer time.',
        source_evidence: [{ url: 'tdb://work_order/WO-00071/status' }],
        entity_ids: ['work_order:WO-00071'],
        confidence: 0.93,
      },
    });
    expect(decision.statusCode).toBe(201);

    const episode = await app.inject({
      method: 'POST',
      url: '/v2/memory/episode/summary/record',
      payload: {
        topic_id: topicId,
        run_id: runId,
        summary: 'Answered the latest status of WO-00071.',
        source_evidence: [{ url: 'tdb://work_order/WO-00071/status' }],
        entity_ids: ['work_order:WO-00071'],
        confidence: 0.93,
      },
    });
    expect(episode.statusCode).toBe(201);

    const recordArtifact = await app.inject({
      method: 'POST',
      url: '/v2/memory/answer/artifact/record',
      payload: {
        domain_id: 'production_operations',
        intent: 'status_lookup',
        normalized_question: 'what is the current status of work order wo-00071',
        question_fingerprint: {
          concepts: ['work_order', 'status_lookup'],
          slots: { work_order_no: 'WO-00071' },
          time_semantics: 'current',
        },
        entity_ids: ['work_order:WO-00071'],
        answer_text: 'WO-00071 is currently in progress.',
        answer_payload: {
          work_order_no: 'WO-00071',
          status: 'in_progress',
        },
        source_task_id: topicId,
        source_run_id: runId,
        source_decision_id: decision.json().decision_id,
        source_episode_summary_id: episode.json().episode_summary_id,
        evidence_refs: [{ url: 'tdb://work_order/WO-00071/status' }],
        freshness_policy: {
          ttl_seconds: 300,
          require_revalidation: true,
        },
        validation_contract: {
          check_type: 'sql_probe',
          required_fields: ['status'],
        },
      },
    });
    expect(recordArtifact.statusCode).toBe(201);
    expect(recordArtifact.json().status).toBe('recorded');

    const answerArtifactId = recordArtifact.json().answer_artifact_id as string;

    const recall = await app.inject({
      method: 'POST',
      url: '/v2/memory/answer/artifact/recall',
      payload: {
        domain_id: 'production_operations',
        intent: 'status_lookup',
        question_fingerprint: {
          concepts: ['work_order', 'status_lookup'],
          slots: { work_order_no: 'WO-00071' },
          time_semantics: 'current',
        },
        entity_ids: ['work_order:WO-00071'],
        limit: 5,
      },
    });
    expect(recall.statusCode).toBe(200);
    expect(recall.json().candidates).toHaveLength(1);
    expect(recall.json().candidates[0].answer_artifact_id).toBe(answerArtifactId);
    expect(recall.json().candidates[0].answer_text).toBe('WO-00071 is currently in progress.');

    const validation = await app.inject({
      method: 'POST',
      url: '/v2/memory/answer/validation/record',
      payload: {
        answer_artifact_id: answerArtifactId,
        validator_type: 'runtime',
        check_spec: {
          check_type: 'sql_probe',
          required_fields: ['status'],
        },
        observed_values: {
          status: 'in_progress',
        },
        pass: true,
        latency_ms: 23,
      },
    });
    expect(validation.statusCode).toBe(201);
    expect(validation.json().status).toBe('recorded');
    expect(validation.json().answer_artifact_id).toBe(answerArtifactId);
  });

  it('upsert_entity_state rejects the nil UUID as entity_id', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/v2/memory/entity/state/upsert',
      payload: {
        entity_id: '00000000-0000-0000-0000-000000000000',
        entity_ref: {
          type: 'file',
          name: 'dac.json',
        },
        durable_state: {
          canonical_ref: 'file:dac-json',
          description: 'Configuration file for EIS DAC.',
        },
      },
    });

    expect(response.statusCode).toBe(400);
    expect(response.json().error.code).toBe('INVALID_ARGUMENT');
    expect(response.json().error.message).toMatch(/nil UUID/i);
  });

  it('upsert_entity_state reuses the existing entity for the same canonical ref', async () => {
    const first = await app.inject({
      method: 'POST',
      url: '/v2/memory/entity/state/upsert',
      payload: {
        entity_ref: {
          type: 'file',
          name: 'dac.json',
        },
        durable_state: {
          canonical_ref: 'file:dac-json',
          description: 'Configuration file for EIS DAC.',
        },
      },
    });

    expect(first.statusCode).toBe(201);
    expect(first.json().status).toBe('created');

    const second = await app.inject({
      method: 'POST',
      url: '/v2/memory/entity/state/upsert',
      payload: {
        entity_ref: {
          type: 'file',
          name: 'dac.json',
        },
        durable_state: {
          canonical_ref: 'file:dac-json',
          workspace: 'DAC workspace',
        },
      },
    });

    expect(second.statusCode).toBe(201);
    expect(second.json().status).toBe('updated');
    expect(second.json().entity_id).toBe(first.json().entity_id);
  });

  it('record_relation writes an edge through the memory API', async () => {
    const source = await app.inject({
      method: 'POST',
      url: '/v2/memory/entity/state/upsert',
      payload: {
        entity_ref: {
          type: 'machine',
          name: 'machine-a',
        },
        durable_state: {
          canonical_ref: 'machine:machine-a',
        },
      },
    });
    expect(source.statusCode).toBe(201);

    const target = await app.inject({
      method: 'POST',
      url: '/v2/memory/entity/state/upsert',
      payload: {
        entity_ref: {
          type: 'sensor',
          name: 'sensor-b',
        },
        durable_state: {
          canonical_ref: 'sensor:sensor-b',
        },
      },
    });
    expect(target.statusCode).toBe(201);

    const response = await app.inject({
      method: 'POST',
      url: '/v2/memory/relation/record',
      payload: {
        source_entity_id: source.json().entity_id,
        target_entity_id: target.json().entity_id,
        predicate: 'feeds',
        valid_from: '2026-04-03T00:00:00.000Z',
        confidence: 0.9,
      },
    });

    expect(response.statusCode).toBe(201);
    expect(response.json().predicate).toBe('feeds');
    expect(response.json().source_entity_id).toBe(source.json().entity_id);
    expect(response.json().target_entity_id).toBe(target.json().entity_id);
    expect(response.json().confidence).toBe(0.9);
  });

  it('get_relations reads edges through the memory API', async () => {
    const source = await app.inject({
      method: 'POST',
      url: '/v2/memory/entity/state/upsert',
      payload: {
        entity_ref: {
          type: 'machine',
          name: 'machine-c',
        },
        durable_state: {
          canonical_ref: 'machine:machine-c',
        },
      },
    });
    expect(source.statusCode).toBe(201);

    const target = await app.inject({
      method: 'POST',
      url: '/v2/memory/entity/state/upsert',
      payload: {
        entity_ref: {
          type: 'sensor',
          name: 'sensor-d',
        },
        durable_state: {
          canonical_ref: 'sensor:sensor-d',
        },
      },
    });
    expect(target.statusCode).toBe(201);

    const record = await app.inject({
      method: 'POST',
      url: '/v2/memory/relation/record',
      payload: {
        source_entity_id: source.json().entity_id,
        target_entity_id: target.json().entity_id,
        predicate: 'monitors',
        valid_from: '2026-04-03T00:00:00.000Z',
      },
    });
    expect(record.statusCode).toBe(201);

    const response = await app.inject({
      method: 'POST',
      url: '/v2/memory/relation/get',
      payload: {
        source_entity_id: source.json().entity_id,
        predicate: 'monitors',
        as_of_valid_time: '2026-04-03T00:00:00.000Z',
      },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().relations).toHaveLength(1);
    expect(response.json().relations[0].predicate).toBe('monitors');
    expect(response.json().relations[0].source_entity_id).toBe(source.json().entity_id);
    expect(response.json().relations[0].target_entity_id).toBe(target.json().entity_id);
  });

  it('record_relation rejects the nil UUID as an entity id', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/v2/memory/relation/record',
      payload: {
        source_entity_id: '00000000-0000-0000-0000-000000000000',
        target_entity_ref: {
          type: 'sensor',
          name: 'sensor-z',
        },
        predicate: 'feeds',
        valid_from: '2026-04-03T00:00:00.000Z',
      },
    });

    expect(response.statusCode).toBe(400);
    expect(response.json().error.code).toBe('INVALID_ARGUMENT');
    expect(response.json().error.message).toMatch(/nil UUID/i);
  });

  it('get_task_context returns recent decisions, entities, and supporting evidence for a task', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/v2/memory/task/context/get',
      payload: {
        topic_id: 'task-entity-state-boston',
        run_id: 'run-entity-state-boston',
        include: {
          facts: true,
          entities: true,
          decisions: true,
          episode_summaries: true,
          open_questions: true,
          supporting_evidence: true,
        },
        max_items: {
          facts: 5,
          decisions: 5,
          open_questions: 5,
          supporting_evidence: 5,
        },
      },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().task.topic_id).toBe('task-entity-state-boston');
    expect(response.json().decisions).toHaveLength(1);
    expect(response.json().decisions[0].decision).toContain('wttr.in');
    expect(response.json().entities).toHaveLength(1);
    expect(response.json().entities[0].entity_id).toBe('city:boston');
    expect(response.json().supporting_evidence).toHaveLength(1);
    expect(response.json().supporting_evidence[0].url).toBe('https://wttr.in/Boston?lang=zh-cn&format=4');
  });

  it('get_task_context accepts topic_id as the semantic task key', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/v2/memory/task/context/get',
      payload: {
        topic_id: 'task-entity-state-boston',
        run_id: 'run-entity-state-boston',
      },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().task.topic_id).toBe('task-entity-state-boston');
    expect(response.json().decisions).toHaveLength(1);
  });

  it('get_task_context returns episode summaries and entity state overviews for the same topic', async () => {
    const topicId = `topic-${randomUUID()}`;
    const runId = `run-${randomUUID()}`;

    const entity = await app.inject({
      method: 'POST',
      url: '/v2/memory/entity/state/upsert',
      payload: {
        entity_ref: {
          type: 'file',
          name: 'dac.json',
        },
        durable_state: {
          canonical_ref: 'file:dac-json',
          workspace: 'DAC workspace',
          description: 'dac.json is the DAC configuration file.',
        },
      },
    });
    expect(entity.statusCode).toBe(201);

    const decision = await app.inject({
      method: 'POST',
      url: '/v2/memory/decision/record',
      payload: {
        topic_id: topicId,
        run_id: runId,
        decision: 'Read dac.json locally before using web fetch.',
        rationale: 'The target is a local workspace file.',
        source_evidence: [{ resource_id: 'resource:dac-json-local' }],
        entity_ids: ['file:dac-json'],
        confidence: 0.92,
        author: { type: 'agent', id: 'dac' },
        metadata: {
          inferred_state: {
            preferred_access_path: {
              value: 'local_file',
              confidence: 0.92,
            },
          },
        },
      },
    });
    expect(decision.statusCode).toBe(201);

    const episode = await app.inject({
      method: 'POST',
      url: '/v2/memory/episode/summary/record',
      payload: {
        episode_label: 'dac-json-local-inspection',
        topic_id: topicId,
        run_id: runId,
        session_id: 'session-dac-json',
        summary: 'Read dac.json locally and identified it as the DAC configuration file.',
        outcomes: ['Confirmed dac.json exists locally.'],
        key_facts: [{ text: 'dac.json is stored in the DAC workspace.', confidence: 0.95 }],
        decisions: ['Prefer local file reads for dac.json.'],
        unresolved_questions: ['Which allowedLocalPaths are configured?'],
        source_evidence: [{ resource_id: 'resource:dac-json-local' }],
        entity_ids: ['file:dac-json'],
        confidence: 0.94,
        author: { type: 'agent', id: 'dac' },
        metadata: {
          answered_questions: ['What is dac.json?'],
        },
        idempotency_key: `episode-${randomUUID()}`,
      },
    });
    expect(episode.statusCode).toBe(201);

    const response = await app.inject({
      method: 'POST',
      url: '/v2/memory/task/context/get',
      payload: {
        topic_id: topicId,
        run_id: runId,
        include: {
          facts: true,
          entities: true,
          decisions: true,
          episode_summaries: true,
          open_questions: true,
          supporting_evidence: true,
        },
        max_items: {
          facts: 5,
          decisions: 5,
          open_questions: 5,
          supporting_evidence: 5,
        },
      },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().task.topic_id).toBe(topicId);
    expect(response.json().decisions).toHaveLength(1);
    expect(response.json().episode_summaries).toHaveLength(1);
    expect(response.json().episode_summaries[0].summary).toContain('dac.json');
    expect(response.json().episode_summaries[0].metadata).toEqual(
      expect.objectContaining({
        answered_questions: ['What is dac.json?'],
      }),
    );
    expect(response.json().open_questions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ text: 'Which allowedLocalPaths are configured?' }),
      ]),
    );
    expect(response.json().entities).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          entity_id: 'file:dac-json',
          entity_type: 'file',
          display_name: 'dac.json',
          canonical_ref: 'file:dac-json',
          durable_state: expect.objectContaining({
            workspace: expect.objectContaining({ value: 'DAC workspace' }),
            description: expect.objectContaining({ value: 'dac.json is the DAC configuration file.' }),
          }),
          inferred_state: expect.objectContaining({
            preferred_access_path: expect.objectContaining({ value: 'local_file' }),
          }),
        }),
      ]),
    );
  });

  it('record_episode_summary persists and deduplicates by idempotency_key', async () => {
    const payload = {
      episode_label: 'boston-weather-fetch-and-summary',
      topic_id: 'task-entity-state-boston',
      run_id: 'run-entity-state-boston',
      session_id: 'session-weather-01',
      summary: 'Retrieved Boston weather from wttr.in and produced a concise reasoning checkpoint.',
      outcomes: [
        'Weather fetched successfully from wttr.in.',
        'Preferred source decision persisted.',
      ],
      key_facts: [
        {
          text: 'Boston weather source is wttr.in for the current run.',
          confidence: 0.91,
        },
      ],
      decisions: ['Use wttr.in as the preferred weather source.'],
      unresolved_questions: [],
      source_evidence: [{ url: 'https://wttr.in/Boston?lang=zh-cn&format=4' }],
      entity_ids: ['city:boston', 'source:wttr.in'],
      confidence: 0.9,
      author: { type: 'agent', id: 'dac' },
      idempotency_key: `episode-${randomUUID()}`,
      metadata: { status: 'complete' },
    };

    const first = await app.inject({
      method: 'POST',
      url: '/v2/memory/episode/summary/record',
      payload,
    });
    expect(first.statusCode).toBe(201);
    expect(first.json().status).toBe('recorded');
    expect(first.json().deduplicated).toBe(false);

    const second = await app.inject({
      method: 'POST',
      url: '/v2/memory/episode/summary/record',
      payload,
    });
    expect(second.statusCode).toBe(201);
    expect(second.json().status).toBe('deduplicated');
    expect(second.json().deduplicated).toBe(true);
    expect(second.json().episode_summary_id).toBe(first.json().episode_summary_id);
  });

  it('record_episode_summary accepts topic_id and stores it as the semantic task key', async () => {
    const payload = {
      episode_label: 'boston-weather-topic-summary',
      topic_id: 'task-entity-state-boston',
      run_id: 'run-entity-state-boston',
      session_id: 'session-weather-01',
      summary: 'Retrieved Boston weather from wttr.in and wrote a topic-scoped checkpoint.',
      outcomes: ['Weather fetched successfully from wttr.in.'],
      key_facts: [{ text: 'Boston weather source is wttr.in for the current run.', confidence: 0.91 }],
      decisions: ['Use wttr.in as the preferred weather source.'],
      unresolved_questions: [],
      source_evidence: [{ url: 'https://wttr.in/Boston?lang=zh-cn&format=4' }],
      entity_ids: ['city:boston'],
      confidence: 0.9,
      author: { type: 'agent', id: 'dac' },
      idempotency_key: `episode-topic-${randomUUID()}`,
      metadata: { status: 'complete' },
    };

    const response = await app.inject({
      method: 'POST',
      url: '/v2/memory/episode/summary/record',
      payload,
    });

    expect(response.statusCode).toBe(201);
    expect(response.json().topic_id).toBe('task-entity-state-boston');
  });

  it('event_seq is monotonic and unique under concurrent appends', async () => {
    const caseId = randomUUID();
    const payloads = Array.from({ length: 10 }).map((_v, i) =>
      app.inject({
        method: 'POST',
        url: '/v2/event/append',
        payload: {
          case_id: caseId,
          event_type: 'fact_observed',
          valid_time: `2026-02-21T00:00:${String(i).padStart(2, '0')}Z`
        }
      })
    );

    const results = await Promise.all(payloads);
    results.forEach((r) => expect(r.statusCode).toBe(201));

    const seqs = results.map((r) => r.json().event_seq as number).sort((a, b) => a - b);
    expect(seqs).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  });

  it('can append event with stream_id only (auto derived case_id)', async () => {
    const streamId = `xiyou-${randomUUID()}`;
    const append = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        stream_id: streamId,
        event_type: 'fact_observed',
        event_text: 'Sun Wukong arrived at Renshenguo temple',
        valid_time: '2026-02-21T00:00:00Z'
      }
    });
    expect(append.statusCode).toBe(201);

    const derivedCaseId = await db.one(sql.typeAlias('record')`
      SELECT uuid_generate_v5(
        '6ba7b811-9dad-11d1-80b4-00c04fd430c8'::uuid,
        ${streamId}::text
      )::text AS case_id
    `);
    const caseId = String((derivedCaseId as Record<string, unknown>).case_id);

    const read = await app.inject({
      method: 'GET',
      url: `/v2/event/read?case_id=${caseId}`
    });
    expect(read.statusCode).toBe(200);
    expect(read.json().events.length).toBeGreaterThan(0);

    const search = await app.inject({
      method: 'POST',
      url: '/v2/search/query',
      payload: {
        query: 'Renshenguo',
        stream_id: streamId,
        limit: 5
      }
    });
    expect(search.statusCode).toBe(200);
    expect(Array.isArray(search.json().hits)).toBe(true);
  });

  it('search/query can search across multiple stream_ids', async () => {
    const streamA = `multi-a-${randomUUID()}`;
    const streamB = `multi-b-${randomUUID()}`;
    const phraseA = `shared-memory-${randomUUID()}-a`;
    const phraseB = `shared-memory-${randomUUID()}-b`;

    const appendA = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        stream_id: streamA,
        event_type: 'fact_observed',
        event_text: `Agent A wrote ${phraseA}`,
        valid_time: '2026-02-21T00:00:00Z'
      }
    });
    expect(appendA.statusCode).toBe(201);

    const appendB = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        stream_id: streamB,
        event_type: 'fact_observed',
        event_text: `Agent B wrote ${phraseB}`,
        valid_time: '2026-02-21T00:00:01Z'
      }
    });
    expect(appendB.statusCode).toBe(201);

    const searchSingle = await app.inject({
      method: 'POST',
      url: '/v2/search/query',
      payload: {
        query: 'Agent',
        stream_id: streamA,
        limit: 10
      }
    });
    expect(searchSingle.statusCode).toBe(200);
    expect(searchSingle.json().hits.every((hit: { stream_id?: string }) => hit.stream_id === streamA)).toBe(true);

    const searchMulti = await app.inject({
      method: 'POST',
      url: '/v2/search/query',
      payload: {
        query: 'Agent',
        stream_ids: [streamA, streamB],
        limit: 10
      }
    });
    expect(searchMulti.statusCode).toBe(200);

    const hitStreams = new Set(
      searchMulti.json().hits.map((hit: { stream_id?: string }) => hit.stream_id)
    );
    expect(hitStreams.has(streamA)).toBe(true);
    expect(hitStreams.has(streamB)).toBe(true);
  });

  it('search/query can resolve stream_ids from domain bindings', async () => {
    const domain = `archeology-${randomUUID()}`;
    const streamId = `domain-stream-${randomUUID()}`;
    const phrase = `buto-site-${randomUUID()}`;

    const append = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        stream_id: streamId,
        event_type: 'fact_observed',
        event_text: `Buto evidence ${phrase}`,
        valid_time: '2026-02-21T00:00:00Z'
      }
    });
    expect(append.statusCode).toBe(201);

    const bind = await app.inject({
      method: 'POST',
      url: '/v2/search/domain-stream/bind',
      payload: {
        domain,
        stream_id: streamId,
        binding_kind: 'primary',
        source: 'test'
      }
    });
    expect(bind.statusCode).toBe(201);
    expect(bind.json()).toMatchObject({
      domain,
      stream_id: streamId,
      binding_kind: 'primary',
      status: 'active'
    });

    const search = await app.inject({
      method: 'POST',
      url: '/v2/search/query',
      payload: {
        query: phrase,
        domain,
        limit: 5
      }
    });
    expect(search.statusCode).toBe(200);
    expect(search.json().resolved_stream_ids).toEqual([streamId]);
    expect(search.json().hits.some((hit: { stream_id?: string; content?: string }) => (
      hit.stream_id === streamId && String(hit.content || '').includes(phrase)
    ))).toBe(true);
  });

  it('snapshot latest returns the nearest anchor <= target_seq', async () => {
    const caseId = randomUUID();

    const s10 = await app.inject({
      method: 'POST',
      url: '/v2/snapshot/write',
      payload: {
        case_id: caseId,
        event_seq: 10,
        projection_version: 'v1',
        state_blob: { hp: 100 }
      }
    });
    expect(s10.statusCode).toBe(201);

    const s20 = await app.inject({
      method: 'POST',
      url: '/v2/snapshot/write',
      payload: {
        case_id: caseId,
        event_seq: 20,
        projection_version: 'v1',
        state_blob: { hp: 80 }
      }
    });
    expect(s20.statusCode).toBe(201);

    const latest = await app.inject({
      method: 'GET',
      url: `/v2/snapshot/latest?case_id=${caseId}&projection_version=v1&target_seq=12`
    });
    expect(latest.statusCode).toBe(200);
    expect(latest.json().snapshot.event_seq).toBe(10);
  });

  it('rejects overlapping property intervals in the same bitemporal window', async () => {
    const objectId = randomUUID();
    await db.query(sql.typeAlias('void')`
      INSERT INTO property_state (
        object_id, prop_key, prop_value, valid_from, valid_to, system_from, system_to
      ) VALUES (
        ${objectId}::uuid, 'status', '{"v":"a"}'::jsonb,
        '2026-03-01T00:00:00Z'::timestamptz, '2026-03-03T00:00:00Z'::timestamptz,
        '2026-03-01T00:00:00Z'::timestamptz, '2026-03-05T00:00:00Z'::timestamptz
      )
    `);

    await expect(
      db.query(sql.typeAlias('void')`
        INSERT INTO property_state (
          object_id, prop_key, prop_value, valid_from, valid_to, system_from, system_to
        ) VALUES (
          ${objectId}::uuid, 'status', '{"v":"b"}'::jsonb,
          '2026-03-02T00:00:00Z'::timestamptz, '2026-03-04T00:00:00Z'::timestamptz,
          '2026-03-02T00:00:00Z'::timestamptz, '2026-03-06T00:00:00Z'::timestamptz
        )
      `)
    ).rejects.toThrow();
  });

  it('rejects overlapping edge intervals in the same bitemporal window', async () => {
    const srcId = randomUUID();
    const dstId = randomUUID();
    await db.query(sql.typeAlias('void')`
      INSERT INTO edge_state (
        src_id, predicate, dst_id, valid_from, valid_to, system_from, system_to
      ) VALUES (
        ${srcId}::uuid, 'related_to', ${dstId}::uuid,
        '2026-03-01T00:00:00Z'::timestamptz, '2026-03-03T00:00:00Z'::timestamptz,
        '2026-03-01T00:00:00Z'::timestamptz, '2026-03-05T00:00:00Z'::timestamptz
      )
    `);

    await expect(
      db.query(sql.typeAlias('void')`
        INSERT INTO edge_state (
          src_id, predicate, dst_id, valid_from, valid_to, system_from, system_to
        ) VALUES (
          ${srcId}::uuid, 'related_to', ${dstId}::uuid,
          '2026-03-02T00:00:00Z'::timestamptz, '2026-03-04T00:00:00Z'::timestamptz,
          '2026-03-02T00:00:00Z'::timestamptz, '2026-03-06T00:00:00Z'::timestamptz
        )
      `)
    ).rejects.toThrow();
  });

  it('rejects update and delete on append-only event ledger', async () => {
    const caseId = randomUUID();
    const append = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        case_id: caseId,
        event_type: 'fact_observed',
        valid_time: '2026-03-01T00:00:00Z'
      }
    });
    expect(append.statusCode).toBe(201);
    const eventId = append.json().event_id as string;

    await expect(
      db.query(sql.typeAlias('void')`
        UPDATE case_event_ledger
        SET event_type = 'state_updated'
        WHERE event_id = ${eventId}::uuid
      `)
    ).rejects.toThrow();

    await expect(
      db.query(sql.typeAlias('void')`
        DELETE FROM case_event_ledger
        WHERE event_id = ${eventId}::uuid
      `)
    ).rejects.toThrow();
  });

  it('authority check supports scope subset matching', async () => {
    const granteeId = randomUUID();
    const grant = await app.inject({
      method: 'POST',
      url: '/v2/authority/grant',
      payload: {
        grantee_id: granteeId,
        action_type: 'deploy',
        scope: { region: 'cn', env: 'prod' },
        valid_from: '2026-04-01T00:00:00Z',
        system_from: '2026-04-01T00:00:00Z'
      }
    });
    expect(grant.statusCode).toBe(201);

    const allowed = await app.inject({
      method: 'GET',
      url: `/v2/authority/check?grantee_id=${granteeId}&action_type=deploy&as_of_valid_time=2026-04-02T00:00:00Z&as_of_system_time=2026-04-02T00:00:00Z&scope=${encodeURIComponent(JSON.stringify({ region: 'cn' }))}`
    });
    expect(allowed.statusCode).toBe(200);
    expect(allowed.json().allowed).toBe(true);

    const denied = await app.inject({
      method: 'GET',
      url: `/v2/authority/check?grantee_id=${granteeId}&action_type=deploy&as_of_valid_time=2026-04-02T00:00:00Z&as_of_system_time=2026-04-02T00:00:00Z&scope=${encodeURIComponent(JSON.stringify({ region: 'us' }))}`
    });
    expect(denied.statusCode).toBe(200);
    expect(denied.json().allowed).toBe(false);
  });

  it('supports ontology fact review and case alert workflows via gateway', async () => {
    const streamId = `ontology-${randomUUID()}`;
    const append = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        stream_id: streamId,
        event_type: 'fact_observed',
        payload: {
          session_id: 'sess-1',
          text: 'Sun Wukong is linked to Flower Fruit Mountain.'
        },
        event_text: 'Sun Wukong is linked to Flower Fruit Mountain.',
        valid_time: '2026-04-10T00:00:00Z'
      }
    });
    expect(append.statusCode).toBe(201);
    const eventId = append.json().event_id as string;

    await db.query(sql.typeAlias('void')`
      INSERT INTO ontology_concept (concept_id, canonical_name, concept_type)
      VALUES
        ('entity:sun-wukong', 'Sun Wukong', 'entity'),
        ('location:flower-fruit-mountain', 'Flower Fruit Mountain', 'location')
      ON CONFLICT (concept_id) DO NOTHING
    `);

    const factRow = await db.one(sql.typeAlias('record')`
      INSERT INTO ontology_fact (
        src_concept_id,
        predicate,
        dst_concept_id,
        qualifier_json,
        confidence,
        extractor,
        status
      ) VALUES (
        'entity:sun-wukong',
        'has_home_country',
        'location:flower-fruit-mountain',
        '{}'::jsonb,
        0.82,
        'llm_v2',
        'candidate'
      )
      RETURNING fact_id::text
    `);
    const factId = Number((factRow as Record<string, unknown>).fact_id);

    await db.query(sql.typeAlias('void')`
      INSERT INTO ontology_fact_evidence (
        fact_id,
        stream_id,
        event_id,
        source_span,
        evidence_json,
        confidence
      ) VALUES (
        ${factId},
        ${streamId},
        ${eventId},
        '0:42',
        ${JSON.stringify({ sent_index: 0, text_hash: 'hash-1', seg_version: 'v1' })}::jsonb,
        0.91
      )
    `);

    const review = await app.inject({
      method: 'POST',
      url: '/v2/ontology/fact/review',
      payload: {
        fact_id: factId,
        decision: 'accept',
        reviewer: 'qa-reviewer',
        note: 'evidence looks good'
      }
    });
    expect(review.statusCode).toBe(200);
    expect(review.json().updated_rows).toBe(1);

    const history = await app.inject({
      method: 'GET',
      url: `/v2/ontology/fact/history?fact_id=${factId}&stream_id=${streamId}`
    });
    expect(history.statusCode).toBe(200);
    expect(history.json().fact.status).toBe('accepted');
    expect(history.json().reviews).toHaveLength(1);
    expect(history.json().evidence_count).toBe(1);

    const dryRunBulk = await app.inject({
      method: 'POST',
      url: '/v2/ontology/fact/review/bulk',
      payload: {
        decision: 'needs_work',
        status: 'accepted',
        stream_id: streamId,
        dry_run: true
      }
    });
    expect(dryRunBulk.statusCode).toBe(200);
    expect(dryRunBulk.json().selected_count).toBe(1);
    expect(dryRunBulk.json().updated_rows).toBe(0);

    const bulk = await app.inject({
      method: 'POST',
      url: '/v2/ontology/fact/review/bulk',
      payload: {
        decision: 'needs_work',
        status: 'accepted',
        stream_id: streamId,
        reviewer: 'bulk-reviewer',
        note: 'needs more corroboration'
      }
    });
    expect(bulk.statusCode).toBe(200);
    expect(bulk.json().updated_rows).toBe(1);

    const openCase = await app.inject({
      method: 'POST',
      url: '/v2/ontology/case/open',
      payload: {
        stream_id: streamId,
        title: 'Review home country fact',
        priority: 'p1',
        fact_ids: [factId],
        actor: 'triage-bot',
        note: 'opening triage case'
      }
    });
    expect(openCase.statusCode).toBe(201);
    const caseId = openCase.json().case_id as number;
    expect(openCase.json().linked_fact_ids).toEqual([factId]);

    const caseList = await app.inject({
      method: 'GET',
      url: `/v2/ontology/case/list?stream_id=${streamId}&status=all`
    });
    expect(caseList.statusCode).toBe(200);
    expect(caseList.json().cases).toHaveLength(1);
    expect(caseList.json().cases[0].fact_count).toBe(1);

    const detailBeforeAlert = await app.inject({
      method: 'GET',
      url: `/v2/ontology/case/detail?case_id=${caseId}`
    });
    expect(detailBeforeAlert.statusCode).toBe(200);
    expect(detailBeforeAlert.json().facts[0].fact_id).toBe(factId);
    expect(detailBeforeAlert.json().alerts).toHaveLength(0);

    const openAlert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/alert/open',
      payload: {
        case_id: caseId,
        message: 'Contradiction risk detected',
        severity: 'high',
        actor: 'triage-bot'
      }
    });
    expect(openAlert.statusCode).toBe(201);
    const alertId = openAlert.json().alert_id as number;

    const alertList = await app.inject({
      method: 'GET',
      url: `/v2/ontology/alert/list?stream_id=${streamId}&status=all`
    });
    expect(alertList.statusCode).toBe(200);
    expect(alertList.json().alerts).toHaveLength(1);
    expect(alertList.json().alerts[0].case_id).toBe(caseId);
    expect(alertList.json().alerts[0].linked_fact_count).toBe(0);

    const updateAlert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/alert/update',
      payload: {
        alert_id: alertId,
        status: 'acked',
        actor: 'oncall-user',
        note: 'acknowledged'
      }
    });
    expect(updateAlert.statusCode).toBe(200);
    expect(updateAlert.json().status).toBe('acked');
    expect(updateAlert.json().acked_by).toBe('oncall-user');

    const updateCase = await app.inject({
      method: 'POST',
      url: '/v2/ontology/case/update',
      payload: {
        case_id: caseId,
        status: 'resolved',
        owner: 'ops-owner',
        actor: 'triage-bot',
        note: 'resolved after review'
      }
    });
    expect(updateCase.statusCode).toBe(200);
    expect(updateCase.json().status).toBe('resolved');
    expect(updateCase.json().owner).toBe('ops-owner');

    const detailAfterAlert = await app.inject({
      method: 'GET',
      url: `/v2/ontology/case/detail?case_id=${caseId}`
    });
    expect(detailAfterAlert.statusCode).toBe(200);
    expect(detailAfterAlert.json().alerts).toHaveLength(1);
    expect(detailAfterAlert.json().alerts[0].alert_id).toBe(alertId);
    expect(detailAfterAlert.json().events.some((item: { action: string }) => item.action === 'status_change')).toBe(true);

    const caseExplain = await app.inject({
      method: 'GET',
      url: `/v2/ontology/case/explain?case_id=${caseId}`
    });
    expect(caseExplain.statusCode).toBe(200);
    expect(caseExplain.json().case.case_id).toBe(caseId);
    expect(caseExplain.json().explanation.fact_count).toBe(1);
    expect(caseExplain.json().explanation.flags).toContain('case_closed');
    expect(caseExplain.json().explanation.reasoning_steps.length).toBeGreaterThanOrEqual(2);

    const alertExplain = await app.inject({
      method: 'GET',
      url: `/v2/ontology/alert/explain?alert_id=${alertId}`
    });
    expect(alertExplain.statusCode).toBe(200);
    expect(alertExplain.json().alert.alert_id).toBe(alertId);
    expect(alertExplain.json().case.case_id).toBe(caseId);
    expect(alertExplain.json().explanation.case_bound).toBe(true);
    expect(alertExplain.json().explanation.source).toBe('manual');

    const explainPlan = await app.inject({
      method: 'POST',
      url: '/v2/plan/execute',
      payload: {
        version: 'tdb.queryplan.v2',
        steps: [
          {
            id: 'case_explain',
            op: 'ontology.case.explain',
            args: {
              case_id: caseId
            },
            save_as: 'case_explain'
          },
          {
            id: 'alert_explain',
            op: 'ontology.alert.explain',
            args: {
              alert_id: alertId
            },
            save_as: 'alert_explain'
          }
        ]
      }
    });
    expect(explainPlan.statusCode).toBe(200);
    expect(explainPlan.json().success).toBe(true);
    expect(explainPlan.json().vars.case_explain.explanation.alert_count).toBe(1);
    expect(explainPlan.json().vars.alert_explain.explanation.case_bound).toBe(true);
  });

  it('supports ontology ops config/run and plan execution via gateway', async () => {
    const streamId = `ops-${randomUUID()}`;
    const append = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        stream_id: streamId,
        event_type: 'fact_observed',
        payload: {
          session_id: 'ops-sess',
          text: 'Ontology ops candidates seeded for rule execution.'
        },
        event_text: 'Ontology ops candidates seeded for rule execution.',
        valid_time: '2026-04-12T00:00:00Z'
      }
    });
    expect(append.statusCode).toBe(201);
    const eventId = append.json().event_id as string;

    await db.query(sql.typeAlias('void')`
      INSERT INTO ontology_concept (concept_id, canonical_name, concept_type)
      VALUES
        ('entity:ops-user', 'Ops User', 'entity'),
        ('location:mount-huaguo', 'Mount Huaguo', 'location'),
        ('location:ao-lai', 'Ao Lai', 'location')
      ON CONFLICT (concept_id) DO NOTHING
    `);

    const staleFactRow = await db.one(sql.typeAlias('record')`
      INSERT INTO ontology_fact (
        src_concept_id,
        predicate,
        dst_concept_id,
        qualifier_json,
        confidence,
        extractor,
        status,
        updated_at
      ) VALUES (
        'entity:ops-user',
        'has_home_country',
        'location:mount-huaguo',
        '{}'::jsonb,
        0.61,
        'llm_v2',
        'candidate',
        '2026-03-01T00:00:00Z'::timestamptz
      )
      RETURNING fact_id::text
    `);
    const staleFactId = Number((staleFactRow as Record<string, unknown>).fact_id);

    const conflictFact1Row = await db.one(sql.typeAlias('record')`
      INSERT INTO ontology_fact (
        src_concept_id,
        predicate,
        dst_concept_id,
        qualifier_json,
        confidence,
        extractor,
        status
      ) VALUES (
        'entity:ops-user',
        'has_home_country',
        'location:mount-huaguo',
        '{}'::jsonb,
        0.83,
        'rule_v2',
        'accepted'
      )
      RETURNING fact_id::text
    `);
    const conflictFact1Id = Number((conflictFact1Row as Record<string, unknown>).fact_id);

    const conflictFact2Row = await db.one(sql.typeAlias('record')`
      INSERT INTO ontology_fact (
        src_concept_id,
        predicate,
        dst_concept_id,
        qualifier_json,
        confidence,
        extractor,
        status
      ) VALUES (
        'entity:ops-user',
        'has_home_country',
        'location:ao-lai',
        '{}'::jsonb,
        0.79,
        'rule_v2',
        'accepted'
      )
      RETURNING fact_id::text
    `);
    const conflictFact2Id = Number((conflictFact2Row as Record<string, unknown>).fact_id);

    for (const factId of [staleFactId, conflictFact1Id, conflictFact2Id]) {
      await db.query(sql.typeAlias('void')`
        INSERT INTO ontology_fact_evidence (
          fact_id,
          stream_id,
          event_id,
          source_span,
          evidence_json,
          confidence
        ) VALUES (
          ${factId},
          ${streamId},
          ${eventId},
          '0:64',
          ${JSON.stringify({ sent_index: 0, text_hash: `ops-${factId}`, seg_version: 'v1' })}::jsonb,
          0.9
        )
      `);
    }

    const upsertDefault = await app.inject({
      method: 'POST',
      url: '/v2/ontology/ops/config/upsert',
      payload: {
        rule_name: 'default',
        enabled: true,
        stale_days: 3,
        conflict_predicate: 'has_home_country',
        severity: 'medium',
        updated_by: 'ops-admin'
      }
    });
    expect(upsertDefault.statusCode).toBe(200);

    const upsertConflict = await app.inject({
      method: 'POST',
      url: '/v2/ontology/ops/config/upsert',
      payload: {
        rule_name: 'conflict_predicate',
        stream_id: streamId,
        severity: 'critical',
        updated_by: 'ops-admin'
      }
    });
    expect(upsertConflict.statusCode).toBe(200);
    expect(upsertConflict.json().severity).toBe('critical');

    const configList = await app.inject({
      method: 'GET',
      url: `/v2/ontology/ops/config?stream_id=${streamId}`
    });
    expect(configList.statusCode).toBe(200);
    expect(configList.json().count).toBeGreaterThanOrEqual(2);

    const dryRun = await app.inject({
      method: 'POST',
      url: '/v2/ontology/ops/rules/run',
      payload: {
        stream_id: streamId,
        dry_run: true
      }
    });
    expect(dryRun.statusCode).toBe(200);
    expect(dryRun.json().candidate_count).toBe(2);
    expect(dryRun.json().created_cases).toHaveLength(0);

    const executeRun = await app.inject({
      method: 'POST',
      url: '/v2/ontology/ops/rules/run',
      payload: {
        stream_id: streamId,
        actor: 'ops-bot'
      }
    });
    expect(executeRun.statusCode).toBe(200);
    expect(executeRun.json().created_cases).toHaveLength(2);
    expect(executeRun.json().created_alerts).toHaveLength(2);

    const rerun = await app.inject({
      method: 'POST',
      url: '/v2/ontology/ops/rules/run',
      payload: {
        stream_id: streamId,
        actor: 'ops-bot'
      }
    });
    expect(rerun.statusCode).toBe(200);
    expect(rerun.json().existing_cases).toHaveLength(2);
    expect(rerun.json().existing_alerts).toHaveLength(2);

    const runs = await app.inject({
      method: 'GET',
      url: `/v2/ontology/ops/runs?stream_id=${streamId}&limit=10`
    });
    expect(runs.statusCode).toBe(200);
    expect(runs.json().count).toBeGreaterThanOrEqual(3);
    const latestRunId = runs.json().runs[0].run_id as number;

    const runExplain = await app.inject({
      method: 'GET',
      url: `/v2/ontology/ops/run/explain?run_id=${latestRunId}`
    });
    expect(runExplain.statusCode).toBe(200);
    expect(runExplain.json().run.run_id).toBe(latestRunId);
    expect(runExplain.json().payload.candidate_count).toBeGreaterThanOrEqual(2);
    expect(runExplain.json().explanation.triggered_rules.length).toBeGreaterThan(0);

    const plan = await app.inject({
      method: 'POST',
      url: '/v2/plan/execute',
      payload: {
        version: 'tdb.queryplan.v2',
        execution_mode: 'best_effort',
        goal: 'exercise ontology ops plan bindings',
        steps: [
          {
            id: 's1',
            op: 'ontology.ops.config.upsert',
            args: {
              rule_name: 'stale_pending',
              stream_id: streamId,
              severity: 'high',
              updated_by: 'plan-bot'
            }
          },
          {
            id: 's2',
            op: 'ontology.ops.rules.run',
            args: {
              stream_id: streamId,
              dry_run: true,
              actor: 'plan-bot'
            },
            save_as: 'ops_run'
          },
          {
            id: 's3',
            op: 'ontology.ops.runs.list',
            args: {
              stream_id: streamId,
              limit: 5
            },
            save_as: 'ops_runs'
          },
          {
            id: 's4',
            op: 'ontology.ops.run.explain',
            args: {
              run_id: latestRunId
            },
            save_as: 'ops_run_explain'
          },
          {
            id: 's5',
            op: 'ontology.case.list',
            args: {
              stream_id: streamId,
              status: 'all',
              limit: 10
            }
          }
        ]
      }
    });
    expect(plan.statusCode).toBe(200);
    expect(plan.json().success).toBe(true);
    expect(plan.json().vars.ops_run.candidate_count).toBe(2);
    expect(plan.json().vars.ops_runs.count).toBeGreaterThanOrEqual(4);
    expect(plan.json().vars.ops_run_explain.run.run_id).toBe(latestRunId);
    expect(plan.json().vars.ops_run_explain.explanation.triggered_rules.length).toBeGreaterThan(0);
  });

  it('creates a conflict draft decision for an ontology case in dry-run mode', async () => {
    const { streamId, srcConceptId } = await seedConflictDraftFixture();

    const openResponse = await app.inject({
      method: 'POST',
      url: '/v2/ontology/case/open',
      payload: {
        stream_id: streamId,
        title: `Capability conflict supports_consistency_group_snapshot for ${srcConceptId}`,
        description: 'Existing case reused by draft flow',
        priority: 'p1',
        owner: 'storage_expert',
        actor: 'acceptance_test'
      }
    });
    expect(openResponse.statusCode).toBe(201);

    const response = await app.inject({
      method: 'POST',
      url: '/v2/ontology/case/decision/draft/conflict',
      payload: {
        case_id: openResponse.json().case_id,
        stream_id: streamId,
        predicate: 'supports_consistency_group_snapshot',
        src_concept_id: srcConceptId,
        actor: 'acceptance_test',
        dry_run: true
      }
    });

    expect(response.statusCode).toBe(200);
    const payload = response.json();
    expect(payload.case).toBeUndefined();
    expect(payload.decision).toBeUndefined();
    expect(payload.created_case).toBe(false);
    expect(payload.deduped).toBe(false);
    expect(payload.candidate.predicate).toBe('supports_consistency_group_snapshot');
  });

  it('creates and dedupes a persisted conflict draft decision', async () => {
    const { streamId, srcConceptId } = await seedConflictDraftFixture();

    const firstResponse = await app.inject({
      method: 'POST',
      url: '/v2/ontology/case/decision/draft/conflict',
      payload: {
        stream_id: streamId,
        predicate: 'supports_consistency_group_snapshot',
        src_concept_id: srcConceptId,
        actor: 'acceptance_test'
      }
    });

    expect(firstResponse.statusCode).toBe(200);
    const firstPayload = firstResponse.json();
    expect(firstPayload.created_case).toBe(true);
    expect(firstPayload.deduped).toBe(false);
    expect(firstPayload.case.stream_id).toBe(streamId);
    expect(firstPayload.decision.decision_kind).toBe('capability_resolution_draft');
    expect(firstPayload.decision.verdict).toBe('needs_review');

    const secondResponse = await app.inject({
      method: 'POST',
      url: '/v2/ontology/case/decision/draft/conflict',
      payload: {
        stream_id: streamId,
        predicate: 'supports_consistency_group_snapshot',
        src_concept_id: srcConceptId,
        actor: 'acceptance_test'
      }
    });

    expect(secondResponse.statusCode).toBe(200);
    const secondPayload = secondResponse.json();
    expect(secondPayload.created_case).toBe(false);
    expect(secondPayload.deduped).toBe(true);
    expect(secondPayload.case.case_id).toBe(firstPayload.case.case_id);
    expect(secondPayload.decision.case_decision_id).toBe(firstPayload.decision.case_decision_id);
  });

  it('supports temporal diff, why-state, decision explain, provenance, and read-only plan ops', async () => {
    const objectId = randomUUID();
    const firstDstId = randomUUID();
    const secondDstId = randomUUID();

    const firstProperty = await app.inject({
      method: 'POST',
      url: '/v2/state/property/upsert',
      payload: {
        object_id: objectId,
        key: 'status',
        value: { value: 'draft' },
        valid_from: '2026-05-01T00:00:00Z',
        system_from: '2026-05-01T00:00:01Z'
      }
    });
    expect(firstProperty.statusCode).toBe(201);

    const secondProperty = await app.inject({
      method: 'POST',
      url: '/v2/state/property/upsert',
      payload: {
        object_id: objectId,
        key: 'status',
        value: { value: 'approved' },
        valid_from: '2026-05-02T00:00:00Z',
        system_from: '2026-05-02T00:00:01Z'
      }
    });
    expect(secondProperty.statusCode).toBe(201);

    const propertyDiff = await app.inject({
      method: 'GET',
      url: `/v2/state/property/diff?object_id=${objectId}&key=status&from_valid_time=2026-05-01T00:00:00Z&to_valid_time=2026-05-02T00:00:00Z&from_system_time=2026-05-02T00:00:00Z&to_system_time=2026-05-03T00:00:00Z`
    });
    expect(propertyDiff.statusCode).toBe(200);
    expect(propertyDiff.json().changed).toBe(true);
    expect(propertyDiff.json().change_type).toBe('updated');
    expect(propertyDiff.json().from.property.value.value).toBe('draft');
    expect(propertyDiff.json().to.property.value.value).toBe('approved');

    const propertyWhy = await app.inject({
      method: 'GET',
      url: `/v2/state/property/why?object_id=${objectId}&key=status&as_of_valid_time=2026-05-02T00:00:00Z&as_of_system_time=2026-05-03T00:00:00Z&candidate_limit=5`
    });
    expect(propertyWhy.statusCode).toBe(200);
    expect(propertyWhy.json().selected.value.value).toBe('approved');
    expect(propertyWhy.json().explanation.outcome).toBe('selected');
    expect(propertyWhy.json().explanation.selected_reason_codes).toContain('selected_highest_precedence');
    expect(propertyWhy.json().candidates.some((item: { reason_codes: string[] }) => item.reason_codes.includes('outside_valid_window'))).toBe(true);

    const firstEdge = await app.inject({
      method: 'POST',
      url: '/v2/state/edge/upsert',
      payload: {
        src_id: objectId,
        predicate: 'travels_with',
        dst_id: firstDstId,
        valid_from: '2026-05-01T00:00:00Z',
        system_from: '2026-05-01T00:00:01Z'
      }
    });
    expect(firstEdge.statusCode).toBe(201);

    const secondEdge = await app.inject({
      method: 'POST',
      url: '/v2/state/edge/upsert',
      payload: {
        src_id: objectId,
        predicate: 'travels_with',
        dst_id: secondDstId,
        valid_from: '2026-05-02T00:00:00Z',
        system_from: '2026-05-02T00:00:01Z'
      }
    });
    expect(secondEdge.statusCode).toBe(201);

    const edgeDiff = await app.inject({
      method: 'GET',
      url: `/v2/state/edge/diff?src_id=${objectId}&predicate=travels_with&from_valid_time=2026-05-01T00:00:00Z&to_valid_time=2026-05-02T00:00:00Z&from_system_time=2026-05-02T00:00:00Z&to_system_time=2026-05-03T00:00:00Z`
    });
    expect(edgeDiff.statusCode).toBe(200);
    expect(edgeDiff.json().changed).toBe(true);
    expect(edgeDiff.json().added).toHaveLength(1);
    expect(edgeDiff.json().added[0].dst_id).toBe(secondDstId);
    expect(edgeDiff.json().removed).toHaveLength(0);

    const caseId = randomUUID();
    const firstEvent = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        case_id: caseId,
        event_type: 'fact_observed',
        valid_time: '2026-05-03T00:00:00Z'
      }
    });
    expect(firstEvent.statusCode).toBe(201);

    const secondEvent = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        case_id: caseId,
        event_type: 'decision_made',
        valid_time: '2026-05-03T00:01:00Z'
      }
    });
    expect(secondEvent.statusCode).toBe(201);

    const artifact = await app.inject({
      method: 'POST',
      url: '/v2/artifact/create',
      payload: {
        artifact_type: 'policy',
        name: `trace-artifact-${randomUUID()}`
      }
    });
    expect(artifact.statusCode).toBe(201);

    const version = await app.inject({
      method: 'POST',
      url: '/v2/artifact/version/create',
      payload: {
        artifact_id: artifact.json().artifact_id,
        version_number: 1,
        status: 'approved',
        valid_from: '2026-05-01T00:00:00Z',
        content_ref: 's3://bucket/trace-policy-v1'
      }
    });
    expect(version.statusCode).toBe(201);

    const snapshot = await app.inject({
      method: 'POST',
      url: '/v2/snapshot/write',
      payload: {
        case_id: caseId,
        event_seq: 1,
        projection_version: 'trace.v1',
        state_blob: {
          object_id: objectId,
          status: 'draft'
        }
      }
    });
    expect(snapshot.statusCode).toBe(201);

    const decision = await app.inject({
      method: 'POST',
      url: '/v2/decision/create',
      payload: {
        case_id: caseId,
        event_seq: 2,
        projection_version: 'trace.v1',
        chosen_action: 'approve'
      }
    });
    expect(decision.statusCode).toBe(201);

    const evidence = await app.inject({
      method: 'POST',
      url: '/v2/decision/evidence/attach',
      payload: {
        decision_id: decision.json().decision_id,
        artifact_version_id: version.json().artifact_version_id,
        citation: {
          section: '2.1'
        }
      }
    });
    expect(evidence.statusCode).toBe(201);

    const trace = await app.inject({
      method: 'GET',
      url: `/v2/decision/trace?case_id=${caseId}&event_seq=2&projection_version=trace.v1`
    });
    expect(trace.statusCode).toBe(200);
    expect(trace.json().decision.decision_id).toBe(decision.json().decision_id);
    expect(trace.json().event.event_id).toBe(secondEvent.json().event_id);
    expect(trace.json().snapshot_anchor.event_seq).toBe(1);
    expect(trace.json().artifact_versions).toHaveLength(1);
    expect(trace.json().artifact_versions[0].artifact_version_id).toBe(version.json().artifact_version_id);
    expect(trace.json().explanation.status).toBe('resolved');

    const explain = await app.inject({
      method: 'GET',
      url: `/v2/decision/explain?case_id=${caseId}&event_seq=2&projection_version=trace.v1`
    });
    expect(explain.statusCode).toBe(200);
    expect(explain.json().explanation.status).toBe('resolved');
    expect(explain.json().explanation.decision_found).toBe(true);
    expect(explain.json().explanation.reasoning_steps.length).toBeGreaterThanOrEqual(4);

    const streamId = `prov-${randomUUID()}`;
    const provenanceEvent = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        stream_id: streamId,
        event_type: 'fact_observed',
        event_text: 'Pigsy belongs to Gao Village.',
        valid_time: '2026-05-04T00:00:00Z'
      }
    });
    expect(provenanceEvent.statusCode).toBe(201);

    await db.query(sql.typeAlias('void')`
      INSERT INTO ontology_concept (concept_id, canonical_name, concept_type)
      VALUES
        ('entity:pigsy', 'Pigsy', 'entity'),
        ('location:gao-village', 'Gao Village', 'location')
      ON CONFLICT (concept_id) DO NOTHING
    `);

    const factRow = await db.one(sql.typeAlias('record')`
      INSERT INTO ontology_fact (
        src_concept_id,
        predicate,
        dst_concept_id,
        qualifier_json,
        confidence,
        extractor,
        status
      ) VALUES (
        'entity:pigsy',
        'has_home_country',
        'location:gao-village',
        '{}'::jsonb,
        0.87,
        'llm_v3',
        'candidate'
      )
      RETURNING fact_id::text
    `);
    const factId = Number((factRow as Record<string, unknown>).fact_id);

    await db.query(sql.typeAlias('void')`
      INSERT INTO ontology_fact_evidence (
        fact_id,
        stream_id,
        event_id,
        source_span,
        evidence_json,
        confidence
      ) VALUES (
        ${factId},
        ${streamId},
        ${provenanceEvent.json().event_id},
        '0:26',
        ${JSON.stringify({ sent_index: 0, text_hash: 'prov-1', seg_version: 'v1' })}::jsonb,
        0.95
      )
    `);

    const ontologyCase = await app.inject({
      method: 'POST',
      url: '/v2/ontology/case/open',
      payload: {
        stream_id: streamId,
        title: 'Review Pigsy home country',
        fact_ids: [factId],
        actor: 'prov-bot'
      }
    });
    expect(ontologyCase.statusCode).toBe(201);

    const ontologyAlert = await app.inject({
      method: 'POST',
      url: '/v2/ontology/alert/open',
      payload: {
        case_id: ontologyCase.json().case_id,
        message: 'Pigsy provenance needs confirmation',
        severity: 'medium',
        actor: 'prov-bot'
      }
    });
    expect(ontologyAlert.statusCode).toBe(201);

    await db.query(sql.typeAlias('void')`
      INSERT INTO ontology_alert_fact (alert_id, fact_id, linked_by, linked_note)
      VALUES (
        ${ontologyAlert.json().alert_id},
        ${factId},
        'prov-bot',
        'manual provenance link'
      )
    `);

    const provenance = await app.inject({
      method: 'GET',
      url: `/v2/ontology/fact/provenance?fact_id=${factId}&stream_id=${streamId}`
    });
    expect(provenance.statusCode).toBe(200);
    expect(provenance.json().fact.fact_id).toBe(factId);
    expect(provenance.json().evidence).toHaveLength(1);
    expect(provenance.json().evidence[0].sentence).toMatchObject({
      sent_index: 0,
      sentence_text: 'Pigsy belongs to Gao Village.'
    });
    expect(provenance.json().linked_cases).toHaveLength(1);
    expect(provenance.json().linked_cases[0].case_id).toBe(ontologyCase.json().case_id);
    expect(provenance.json().linked_alerts).toHaveLength(1);
    expect(provenance.json().linked_alerts[0].alert_id).toBe(ontologyAlert.json().alert_id);

    const plan = await app.inject({
      method: 'POST',
      url: '/v2/plan/execute',
      payload: {
        version: 'tdb.queryplan.v2',
        steps: [
          {
            id: 'property_diff',
            op: 'state.property.diff',
            args: {
              object_id: objectId,
              key: 'status',
              from_valid_time: '2026-05-01T00:00:00Z',
              to_valid_time: '2026-05-02T00:00:00Z',
              from_system_time: '2026-05-02T00:00:00Z',
              to_system_time: '2026-05-03T00:00:00Z'
            },
            save_as: 'property_diff'
          },
          {
            id: 'property_why',
            op: 'state.property.why',
            args: {
              object_id: objectId,
              key: 'status',
              as_of_valid_time: '2026-05-02T00:00:00Z',
              as_of_system_time: '2026-05-03T00:00:00Z',
              candidate_limit: 5
            },
            save_as: 'property_why'
          },
          {
            id: 'edge_diff',
            op: 'state.edge.diff',
            args: {
              src_id: objectId,
              predicate: 'travels_with',
              from_valid_time: '2026-05-01T00:00:00Z',
              to_valid_time: '2026-05-02T00:00:00Z',
              from_system_time: '2026-05-02T00:00:00Z',
              to_system_time: '2026-05-03T00:00:00Z'
            },
            save_as: 'edge_diff'
          },
          {
            id: 'decision_trace',
            op: 'decision.trace',
            args: {
              case_id: caseId,
              event_seq: 2,
              projection_version: 'trace.v1'
            },
            save_as: 'decision_trace'
          },
          {
            id: 'decision_explain',
            op: 'decision.explain',
            args: {
              case_id: caseId,
              event_seq: 2,
              projection_version: 'trace.v1'
            },
            save_as: 'decision_explain'
          },
          {
            id: 'fact_provenance',
            op: 'ontology.fact.provenance',
            args: {
              fact_id: factId,
              stream_id: streamId
            },
            save_as: 'fact_provenance'
          }
        ]
      }
    });
    expect(plan.statusCode).toBe(200);
    expect(plan.json().success).toBe(true);
    expect(plan.json().vars.property_diff.change_type).toBe('updated');
    expect(plan.json().vars.property_why.selected.value.value).toBe('approved');
    expect(plan.json().vars.edge_diff.added).toHaveLength(1);
    expect(plan.json().vars.decision_trace.decision.decision_id).toBe(decision.json().decision_id);
    expect(plan.json().vars.decision_explain.explanation.status).toBe('resolved');
    expect(plan.json().vars.fact_provenance.linked_alerts[0].alert_id).toBe(ontologyAlert.json().alert_id);
  });

  it('entity catalog supports upsert/get/list', async () => {
    const upsert = await app.inject({
      method: 'POST',
      url: '/v2/entity/upsert',
      payload: {
        entity_type: 'Person',
        display_name: 'Sun Wukong',
        external_refs: { employee_id: 'emp-001' },
        status: 'active'
      }
    });
    expect(upsert.statusCode).toBe(201);
    const entityId = upsert.json().entity_id as string;

    const get = await app.inject({
      method: 'GET',
      url: `/v2/entity/get?entity_id=${entityId}`
    });
    expect(get.statusCode).toBe(200);
    expect(get.json().entity.display_name).toBe('Sun Wukong');

    const update = await app.inject({
      method: 'POST',
      url: '/v2/entity/upsert',
      payload: {
        entity_id: entityId,
        entity_type: 'Person',
        display_name: 'Sun Wukong (齐天大圣)',
        status: 'inactive'
      }
    });
    expect(update.statusCode).toBe(201);
    expect(update.json().status).toBe('inactive');

    const list = await app.inject({
      method: 'GET',
      url: '/v2/entity/list?entity_type=Person&status=inactive&q=Sun'
    });
    expect(list.statusCode).toBe(200);
    expect(Array.isArray(list.json().entities)).toBe(true);
    expect(list.json().entities.some((row: { entity_id: string }) => row.entity_id === entityId)).toBe(true);
  });

  it('ingest endpoints support phased import with per-item errors', async () => {
    const streamId = `xiyou-${randomUUID()}`;
    const caseId = randomUUID();

    const ingestEntities = await app.inject({
      method: 'POST',
      url: '/v2/ingest/entities',
      payload: {
        stream_id: streamId,
        items: [
          {
            entity_ref: 'ent.sun',
            entity_type: 'Person',
            display_name: 'Sun Wukong'
          },
          {
            entity_ref: 'ent.tangsan',
            entity_type: 'Person',
            display_name: 'Tang Sanzang'
          }
        ]
      }
    });
    expect(ingestEntities.statusCode).toBe(200);
    expect(ingestEntities.json().accepted).toBe(2);
    expect(ingestEntities.json().rejected).toBe(0);

    const ingestArtifacts = await app.inject({
      method: 'POST',
      url: '/v2/ingest/artifacts',
      payload: {
        stream_id: streamId,
        ref_state: ingestEntities.json().ref_state_delta,
        items: [
          {
            artifact_ref: 'artifact.chapter1',
            artifact: {
              artifact_type: 'document',
              name: 'Journey to the West Ch.1'
            },
            versions: [
              {
                version_number: 1,
                status: 'approved',
                valid_from: '2026-01-01T00:00:00Z',
                content_ref: 's3://bucket/xiyou/ch1.txt',
                author_ref: 'ent.sun'
              }
            ]
          }
        ]
      }
    });
    expect(ingestArtifacts.statusCode).toBe(200);
    expect(ingestArtifacts.json().accepted).toBe(1);
    expect(ingestArtifacts.json().rejected).toBe(0);

    const ingestEvents = await app.inject({
      method: 'POST',
      url: '/v2/ingest/events',
      payload: {
        stream_id: streamId,
        ref_state: {
          entity_ref_to_id: ingestEntities.json().ref_state_delta.entity_ref_to_id,
          artifact_ref_to_id: ingestArtifacts.json().ref_state_delta.artifact_ref_to_id
        },
        items: [
          {
            event_ref: 'event.1',
            case_ref: 'case.journey',
            event_type: 'fact_observed',
            subject_ref: 'ent.sun',
            object_ref: 'artifact.chapter1',
            valid_time: '2026-01-01T00:00:00Z',
            payload: {
              text: 'Sun Wukong was born from a stone.'
            }
          },
          {
            event_ref: 'event.bad',
            case_id: caseId,
            event_type: 'bad_type',
            valid_time: '2026-01-01T00:00:01Z'
          }
        ]
      }
    });
    expect(ingestEvents.statusCode).toBe(200);
    expect(ingestEvents.json().accepted).toBe(1);
    expect(ingestEvents.json().rejected).toBe(1);
    expect(ingestEvents.json().errors.length).toBe(1);
    expect(ingestEvents.json().event_ids.length).toBe(1);

    const read = await app.inject({
      method: 'GET',
      url: `/v2/event/read?case_id=${
        String((await db.one(sql.typeAlias('record')`
          SELECT case_id::text
          FROM case_event_ledger
          WHERE event_id = ${ingestEvents.json().event_ids[0]}::uuid
          LIMIT 1
        `) as Record<string, unknown>).case_id)
      }`
    });
    expect(read.statusCode).toBe(200);
    expect(read.json().events.length).toBe(1);
    expect(read.json().events[0].subject_id).toBe(ingestEntities.json().results[0].entity_id);
    expect(read.json().events[0].object_id).toBe(ingestArtifacts.json().results[0].artifact_id);

    const sunId = ingestEntities.json().results[0].entity_id as string;
    const tangId = ingestEntities.json().results[1].entity_id as string;
    const sourceEventId = ingestEvents.json().event_ids[0] as string;

    const artifactAuthorId = String((await db.one(sql.typeAlias('record')`
      SELECT author_id::text
      FROM artifact_version
      WHERE artifact_version_id = ${ingestArtifacts.json().results[0].artifact_version_ids[0]}::uuid
    `) as Record<string, unknown>).author_id);
    expect(artifactAuthorId).toBe(sunId);

    const ingestProperty = await app.inject({
      method: 'POST',
      url: '/v2/ingest/property',
      payload: {
        stream_id: streamId,
        ref_state: {
          entity_ref_to_id: ingestEntities.json().ref_state_delta.entity_ref_to_id,
          event_ref_to_id: ingestEvents.json().ref_state_delta.event_ref_to_id
        },
        items: [
          {
            object_ref: 'ent.sun',
            key: 'title',
            value: { value: 'Great Sage Equaling Heaven' },
            valid_from: '2026-01-01T00:00:00Z',
            source_event_ref: 'event.1'
          }
        ]
      }
    });
    expect(ingestProperty.statusCode).toBe(200);
    expect(ingestProperty.json().accepted).toBe(1);
    expect(ingestProperty.json().rejected).toBe(0);

    const ingestEdge = await app.inject({
      method: 'POST',
      url: '/v2/ingest/edge',
      payload: {
        stream_id: streamId,
        ref_state: {
          entity_ref_to_id: ingestEntities.json().ref_state_delta.entity_ref_to_id,
          event_ref_to_id: ingestEvents.json().ref_state_delta.event_ref_to_id
        },
        items: [
          {
            src_ref: 'ent.sun',
            predicate: 'travels_with',
            dst_ref: 'ent.tangsan',
            valid_from: '2026-01-01T00:00:00Z',
            source_event_ref: 'event.1'
          }
        ]
      }
    });
    expect(ingestEdge.statusCode).toBe(200);
    expect(ingestEdge.json().accepted).toBe(1);
    expect(ingestEdge.json().rejected).toBe(0);
    expect(sourceEventId).toBeTruthy();
    expect(tangId).toBeTruthy();

    const ingestText = await app.inject({
      method: 'POST',
      url: '/v2/ingest/text',
      payload: {
        stream_id: streamId,
        items: [
          {
            event_ref: 'event.2',
            text: 'Tang Sanzang started the journey.'
          }
        ]
      }
    });
    expect(ingestText.statusCode).toBe(200);
    expect(ingestText.json().accepted).toBe(1);
    expect(ingestText.json().rejected).toBe(0);
    expect(ingestText.json().event_ids.length).toBe(1);
  });

  it('ingest bundle sequences phases server-side with defaults and ref resolution', async () => {
    const streamId = `bundle-${randomUUID()}`;

    const bundle = await app.inject({
      method: 'POST',
      url: '/v2/ingest/bundle',
      payload: {
        stream_id: streamId,
        defaults: {
          event_type: 'fact_observed',
          valid_time: '2026-02-23T15:00:00Z',
          system_time: '2026-02-23T15:00:01Z'
        },
        entities: [
          {
            entity_ref: 'entity.sun',
            entity_type: 'character',
            display_name: 'Sun Wukong'
          },
          {
            entity_ref: 'entity.tang',
            entity_type: 'character',
            display_name: 'Tang Sanzang'
          }
        ],
        artifacts: [
          {
            artifact_ref: 'artifact.chapter1',
            artifact: {
              artifact_type: 'text',
              name: 'xiyou.txt'
            },
            versions: [
              {
                version_number: 1,
                status: 'approved',
                valid_from: '2026-01-01T00:00:00Z',
                content_ref: 's3://bucket/xiyou.txt',
                author_ref: 'entity.sun'
              }
            ]
          }
        ],
        events: [
          {
            event_ref: 'event.1',
            case_ref: 'case.bundle.1',
            subject_ref: 'entity.sun',
            object_ref: 'artifact.chapter1',
            payload: {
              text: 'Sun Wukong meets Tang Sanzang.'
            }
          }
        ],
        properties: [
          {
            object_ref: 'entity.sun',
            key: 'title',
            value: { value: 'Great Sage Equaling Heaven' },
            source_event_ref: 'event.1'
          }
        ],
        edges: [
          {
            src_ref: 'entity.sun',
            predicate: 'travels_with',
            dst_ref: 'entity.tang',
            source_event_ref: 'event.1'
          }
        ]
      }
    });

    expect(bundle.statusCode).toBe(200);
    expect(bundle.json().totals.accepted).toBe(6);
    expect(bundle.json().totals.rejected).toBe(0);
    expect(bundle.json().phases.entities.accepted).toBe(2);
    expect(bundle.json().phases.artifacts.accepted).toBe(1);
    expect(bundle.json().phases.events.accepted).toBe(1);
    expect(bundle.json().phases.properties.accepted).toBe(1);
    expect(bundle.json().phases.edges.accepted).toBe(1);
    expect(bundle.json().ref_state.entity_ref_to_id['entity.sun']).toBeTruthy();
    expect(bundle.json().ref_state.event_ref_to_id['event.1']).toBeTruthy();

    const caseId = String((await db.one(sql.typeAlias('record')`
      SELECT case_id::text
      FROM case_event_ledger
      WHERE event_id = ${bundle.json().phases.events.event_ids[0]}::uuid
      LIMIT 1
    `) as Record<string, unknown>).case_id);

    const read = await app.inject({
      method: 'GET',
      url: `/v2/event/read?case_id=${caseId}`
    });
    expect(read.statusCode).toBe(200);
    expect(read.json().events[0].valid_time).toBe('2026-02-23T15:00:00.000Z');

    const property = await app.inject({
      method: 'GET',
      url: `/v2/state/property/asof?object_id=${bundle.json().ref_state.entity_ref_to_id['entity.sun']}&key=title&as_of_valid_time=2026-02-23T15:00:00Z&as_of_system_time=2026-02-23T15:00:05Z`
    });
    expect(property.statusCode).toBe(200);
    expect(property.json().property.value.value).toBe('Great Sage Equaling Heaven');
  });

  it('ingest/text does not require gateway embedding config when generate_embedding is requested', async () => {
    const appWithoutGatewayEmbedding = await buildApp({
      logLevel: 'silent',
      backend: {
        address: GATEWAY_BACKEND_ADDR,
        timeoutMs: 3000
      }
    });

    try {
      const streamId = `text-no-gateway-embed-${randomUUID()}`;
      const res = await appWithoutGatewayEmbedding.inject({
        method: 'POST',
        url: '/v2/ingest/text',
        payload: {
          stream_id: streamId,
          generate_embedding: true,
          items: [
            {
              event_ref: 'event.1',
              text: 'Amun became central in New Kingdom royal ideology.'
            }
          ]
        }
      });

      expect(res.statusCode).toBe(200);
      expect(res.json().accepted).toBe(1);
      expect(res.json().rejected).toBe(0);
      expect(res.json().event_ids.length).toBe(1);
    } finally {
      await appWithoutGatewayEmbedding.close();
    }
  });

  it('executes plan steps with template wiring and continue policy', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/plan/execute',
      payload: {
        version: 'tdb.queryplan.v2',
        context: {
          name: `plan-entity-${randomUUID()}`
        },
        steps: [
          {
            id: 's1',
            op: 'entity.upsert',
            args: {
              entity_type: 'character',
              display_name: '${context.name}'
            },
            save_as: 'entity'
          },
          {
            id: 's2',
            op: 'entity.get',
            args: {
              entity_id: '${vars.entity.entity_id}'
            },
            save_as: 'fetched'
          },
          {
            id: 's3',
            op: 'event.read',
            args: {
              case_id: 'not-a-uuid'
            },
            on_error: 'continue'
          }
        ]
      }
    });

    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.execution_mode).toBe('safe');
    expect(body.results).toHaveLength(3);
    expect(body.results[0].ok).toBe(true);
    expect(body.results[1].ok).toBe(true);
    expect(body.results[2].ok).toBe(false);
    expect(body.vars.entity.entity_id).toBeDefined();
    expect(body.vars.fetched.entity.entity_id).toBe(body.vars.entity.entity_id);
  });

  it('replays plan with step-level execution trace', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/plan/replay',
      payload: {
        version: 'tdb.queryplan.v2',
        goal: 'replay trace acceptance',
        context: {
          display_name: `replay-entity-${randomUUID()}`,
          enabled: true
        },
        execution_mode: 'best_effort',
        steps: [
          {
            id: 's1',
            op: 'entity.upsert',
            args: {
              entity_type: 'character',
              display_name: '${context.display_name}'
            },
            save_as: 'entity'
          },
          {
            id: 's2',
            op: 'entity.get',
            args: {
              entity_id: '${vars.entity.entity_id}'
            },
            save_as: 'fetched'
          },
          {
            id: 's3',
            op: 'health.get',
            when: '!${context.enabled}',
            save_as: 'skipped_health'
          },
          {
            id: 's4',
            op: 'event.read',
            args: {
              case_id: 'not-a-uuid'
            },
            on_error: 'continue'
          }
        ]
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json().replay).toBe(true);
    expect(res.json().success).toBe(false);
    expect(res.json().trace).toHaveLength(4);
    expect(res.json().trace[0].status).toBe('executed');
    expect(res.json().trace[0].saved_value_preview.entity_id).toBe(res.json().vars.entity.entity_id);
    expect(res.json().trace[1].vars_before.entity.entity_id).toBe(res.json().vars.entity.entity_id);
    expect(res.json().trace[1].status).toBe('executed');
    expect(res.json().trace[2].status).toBe('skipped');
    expect(res.json().trace[2].when_result).toBe(false);
    expect(res.json().trace[3].status).toBe('failed');
    expect(res.json().trace[3].error.code).toBeDefined();

    const persisted = await app.inject({
      method: 'GET',
      url: `/v2/plan/run/get?plan_id=${res.json().plan_id}`
    });
    expect(persisted.statusCode).toBe(200);
    expect(persisted.json().run.plan_id).toBe(res.json().plan_id);
    expect(persisted.json().run.execution_kind).toBe('replay');
    expect(persisted.json().trace).toHaveLength(4);
    expect(persisted.json().request.steps).toHaveLength(4);

    const replayById = await app.inject({
      method: 'POST',
      url: '/v2/plan/replay/by-id',
      payload: {
        plan_id: res.json().plan_id
      }
    });
    expect(replayById.statusCode).toBe(200);
    expect(replayById.json().replay).toBe(true);
    expect(replayById.json().replay_of_plan_id).toBe(res.json().plan_id);
    expect(replayById.json().trace).toHaveLength(4);

    const replayedPersisted = await app.inject({
      method: 'GET',
      url: `/v2/plan/run/get?plan_id=${replayById.json().plan_id}`
    });
    expect(replayedPersisted.statusCode).toBe(200);
    expect(replayedPersisted.json().run.replay_of_plan_id).toBe(res.json().plan_id);

    const listedAll = await app.inject({
      method: 'GET',
      url: '/v2/plan/run/list?execution_kind=replay&limit=10'
    });
    expect(listedAll.statusCode).toBe(200);
    expect(listedAll.json().count).toBeGreaterThanOrEqual(2);
    expect(listedAll.json().runs.some((item: { plan_id: string }) => item.plan_id === res.json().plan_id)).toBe(true);
    expect(listedAll.json().runs.some((item: { plan_id: string }) => item.plan_id === replayById.json().plan_id)).toBe(true);

    const listedByReplayParent = await app.inject({
      method: 'GET',
      url: `/v2/plan/run/list?execution_kind=replay&replay_of_plan_id=${res.json().plan_id}&limit=10`
    });
    expect(listedByReplayParent.statusCode).toBe(200);
    expect(listedByReplayParent.json().count).toBe(1);
    expect(listedByReplayParent.json().runs[0].plan_id).toBe(replayById.json().plan_id);

    const listedByGoal = await app.inject({
      method: 'GET',
      url: '/v2/plan/run/list?execution_kind=replay&goal_q=replay&limit=10'
    });
    expect(listedByGoal.statusCode).toBe(200);
    expect(listedByGoal.json().count).toBeGreaterThanOrEqual(2);

    const listedBySuccess = await app.inject({
      method: 'GET',
      url: '/v2/plan/run/list?execution_kind=replay&success=false&limit=10'
    });
    expect(listedBySuccess.statusCode).toBe(200);
    expect(listedBySuccess.json().count).toBeGreaterThanOrEqual(2);
  });

  it('rejects multi-step write plans in safe mode', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/plan/execute',
      payload: {
        version: 'tdb.queryplan.v2',
        steps: [
          {
            id: 's1',
            op: 'entity.upsert',
            args: {
              entity_type: 'character',
              display_name: `unsafe-1-${randomUUID()}`
            }
          },
          {
            id: 's2',
            op: 'entity.upsert',
            args: {
              entity_type: 'character',
              display_name: `unsafe-2-${randomUUID()}`
            }
          }
        ]
      }
    });

    expect(res.statusCode).toBe(400);
    expect(res.json().error.code).toBe('PLAN_MUTATION_UNSAFE');
  });

  it('allows multi-step write plans only in best_effort mode', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/plan/execute',
      payload: {
        version: 'tdb.queryplan.v2',
        execution_mode: 'best_effort',
        steps: [
          {
            id: 's1',
            op: 'entity.upsert',
            args: {
              entity_type: 'character',
              display_name: `best-effort-1-${randomUUID()}`
            }
          },
          {
            id: 's2',
            op: 'entity.upsert',
            args: {
              entity_type: 'character',
              display_name: `best-effort-2-${randomUUID()}`
            }
          }
        ]
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json().execution_mode).toBe('best_effort');
    expect(res.json().success).toBe(true);
    expect(res.json().results).toHaveLength(2);
  });

  it('covers the bundle -> search -> decision/evidence -> snapshot -> replay loop', async () => {
    const streamId = `loop-${randomUUID()}`;
    const uniquePhrase = `renshenguo-signal-${randomUUID()}`;

    const bundle = await app.inject({
      method: 'POST',
      url: '/v2/ingest/bundle',
      payload: {
        stream_id: streamId,
        defaults: {
          event_type: 'fact_observed',
          valid_time: '2026-02-23T15:00:00Z',
          system_time: '2026-02-23T15:00:01Z'
        },
        entities: [
          {
            entity_ref: 'entity.sun',
            entity_type: 'character',
            display_name: 'Sun Wukong'
          },
          {
            entity_ref: 'entity.tang',
            entity_type: 'character',
            display_name: 'Tang Sanzang'
          }
        ],
        artifacts: [
          {
            artifact_ref: 'artifact.chapter25',
            artifact: {
              artifact_type: 'text',
              name: 'renshenguo-ch25.txt'
            },
            versions: [
              {
                version_number: 1,
                status: 'approved',
                valid_from: '2026-01-01T00:00:00Z',
                content_ref: 's3://bucket/renshenguo-ch25.txt',
                author_ref: 'entity.tang'
              }
            ]
          }
        ],
        events: [
          {
            event_ref: 'event.1',
            case_ref: 'case.loop.1',
            subject_ref: 'entity.sun',
            object_ref: 'artifact.chapter25',
            payload: {
              chapter: 25,
              text: 'Sun Wukong reaches Wuzhuang Temple.'
            }
          },
          {
            event_ref: 'event.2',
            case_ref: 'case.loop.1',
            subject_ref: 'entity.sun',
            object_ref: 'artifact.chapter25',
            payload: {
              chapter: 25,
              text: `${uniquePhrase} Sun Wukong finds the ginseng fruit tree.`
            }
          }
        ],
        properties: [
          {
            object_ref: 'entity.sun',
            key: 'title',
            value: { value: 'Great Sage Equaling Heaven' },
            source_event_ref: 'event.1'
          }
        ],
        edges: [
          {
            src_ref: 'entity.sun',
            predicate: 'travels_with',
            dst_ref: 'entity.tang',
            source_event_ref: 'event.1'
          }
        ]
      }
    });

    expect(bundle.statusCode).toBe(200);
    expect(bundle.json().totals.accepted).toBe(7);
    expect(bundle.json().totals.rejected).toBe(0);
    expect(bundle.json().phases.events.accepted).toBe(2);

    const sunId = bundle.json().ref_state.entity_ref_to_id['entity.sun'] as string;
    const tangId = bundle.json().ref_state.entity_ref_to_id['entity.tang'] as string;
    const firstEventId = bundle.json().ref_state.event_ref_to_id['event.1'] as string;
    const secondEventId = bundle.json().ref_state.event_ref_to_id['event.2'] as string;
    const artifactVersionId = bundle.json().phases.artifacts.results[0].artifact_version_ids[0] as string;

    const caseId = String((await db.one(sql.typeAlias('record')`
      SELECT case_id::text
      FROM case_event_ledger
      WHERE event_id = ${secondEventId}::uuid
      LIMIT 1
    `) as Record<string, unknown>).case_id);

    const search = await app.inject({
      method: 'POST',
      url: '/v2/search/query',
      payload: {
        query: uniquePhrase,
        stream_id: streamId,
        limit: 5
      }
    });
    expect(search.statusCode).toBe(200);
    expect(search.json().hits.length).toBeGreaterThan(0);
    expect(search.json().hits[0].event_id).toBe(secondEventId);
    expect(search.json().hits[0].content).toContain(uniquePhrase);

    const decision = await app.inject({
      method: 'POST',
      url: '/v2/decision/create',
      payload: {
        case_id: caseId,
        event_seq: 2,
        projection_version: 'risk.v2',
        chosen_action: 'inspect_artifact',
        detail: {
          matched_doc_id: search.json().hits[0].doc_id,
          matched_query: uniquePhrase
        }
      }
    });
    expect(decision.statusCode).toBe(201);

    const attach = await app.inject({
      method: 'POST',
      url: '/v2/decision/evidence/attach',
      payload: {
        decision_id: decision.json().decision_id,
        artifact_version_id: artifactVersionId,
        citation: {
          chapter: 25,
          quote: uniquePhrase
        }
      }
    });
    expect(attach.statusCode).toBe(201);

    const snapshot = await app.inject({
      method: 'POST',
      url: '/v2/snapshot/write',
      payload: {
        case_id: caseId,
        event_seq: 1,
        projection_version: 'risk.v2',
        state_blob: {
          tracked_entity_id: sunId,
          summary: 'anchor after temple arrival'
        }
      }
    });
    expect(snapshot.statusCode).toBe(201);

    const replayPlan = JSON.parse(readFileSync(BUSINESS_LOOP_PLAN_SAMPLE_PATH, 'utf8')) as {
      context?: Record<string, unknown>;
    };
    replayPlan.context = {
      ...replayPlan.context,
      case_id: caseId,
      projection_version: 'risk.v2',
      target_seq: 2,
      as_of_valid_time: '2026-02-23T15:00:00Z',
      as_of_system_time: '2026-02-23T15:00:05Z',
      tracked_entity_id: sunId,
      tracked_property_key: 'title',
      tracked_predicate: 'travels_with'
    };

    const replay = await app.inject({
      method: 'POST',
      url: '/v2/plan/execute',
      payload: replayPlan
    });
    expect(replay.statusCode).toBe(200);
    expect(replay.json().success).toBe(true);
    expect(replay.json().results).toHaveLength(5);
    expect(replay.json().vars.snapshot_anchor.snapshot.event_seq).toBe(1);
    expect(replay.json().vars.snapshot_anchor.snapshot.state_blob.tracked_entity_id).toBe(sunId);
    expect(replay.json().vars.delta_events.events.map((event: { event_seq: number }) => event.event_seq)).toEqual([
      1,
      2
    ]);
    expect(replay.json().vars.delta_events.events[0].event_id).toBe(firstEventId);
    expect(replay.json().vars.delta_events.events[1].event_id).toBe(secondEventId);
    expect(replay.json().vars.tracked_property.property.value.value).toBe('Great Sage Equaling Heaven');
    expect(replay.json().vars.tracked_edges.edges).toHaveLength(1);
    expect(replay.json().vars.tracked_edges.edges[0].dst_id).toBe(tangId);
    expect(replay.json().vars.decision_at_target.decision.event_seq).toBe(2);
    expect(replay.json().vars.decision_at_target.evidence).toHaveLength(1);
    expect(replay.json().vars.decision_at_target.evidence[0].artifact_version_id).toBe(artifactVersionId);
  });

  it('docs phased ingest sample stays executable against live migrations', async () => {
    const plan = JSON.parse(readFileSync(PHASED_PLAN_SAMPLE_PATH, 'utf8')) as {
      context?: Record<string, unknown>;
      execution_mode?: string;
    };
    plan.context = {
      ...plan.context,
      stream_id: `sample-${randomUUID()}`
    };

    const res = await app.inject({
      method: 'POST',
      url: '/v2/plan/execute',
      payload: plan
    });

    expect(plan.execution_mode).toBe('best_effort');
    expect(res.statusCode).toBe(200);
    expect(res.json().execution_mode).toBe('best_effort');
    expect(res.json().success).toBe(true);
    expect(res.json().results).toHaveLength(5);
    expect(res.json().vars.entities.accepted).toBe(2);
    expect(res.json().vars.events.accepted).toBe(1);
  });

  it('wiki page upsert/get/search/list round-trips knowledge_level and authority_kind', async () => {
    const domain = 'antique_expert';
    const slug = `longquan-celadon-${randomUUID()}`;
    const searchToken = `knowledge-level-token-${randomUUID()}`;

    const upsert = await app.inject({
      method: 'POST',
      url: '/v2/wiki/page',
      payload: {
        domain,
        slug,
        title: '龙泉青瓷',
        content: `这是一个足够长的概念页面，用来验证 wiki knowledge level round-trip。 ${searchToken}`,
        page_type: 'concept',
        knowledge_level: 'concept_like',
        authority_kind: 'accepted_ontology',
        tags: ['ceramics', 'celadon'],
        confidence: 0.82
      }
    });
    expect(upsert.statusCode).toBe(200);

    const get = await app.inject({
      method: 'GET',
      url: `/v2/wiki/page?domain=${encodeURIComponent(domain)}&slug=${encodeURIComponent(slug)}`
    });
    expect(get.statusCode).toBe(200);
    expect(get.json().page.knowledge_level).toBe('concept_like');
    expect(get.json().page.authority_kind).toBe('accepted_ontology');

    const search = await app.inject({
      method: 'GET',
      url: `/v2/wiki/search?domain=${encodeURIComponent(domain)}&q=${encodeURIComponent(searchToken)}&page_type=concept&knowledge_level=concept_like&authority_kind=accepted_ontology&limit=10`
    });
    expect(search.statusCode).toBe(200);
    expect(
      (search.json().results as Array<{ slug: string }>).some((item) => item.slug === slug)
    ).toBe(true);

    const list = await app.inject({
      method: 'GET',
      url: `/v2/wiki/pages?domain=${encodeURIComponent(domain)}&page_type=concept&knowledge_level=concept_like&authority_kind=accepted_ontology`
    });
    expect(list.statusCode).toBe(200);
    const listPayload = list.json() as {
      pages: Array<{ slug: string; knowledge_level?: string; authority_kind?: string; content?: string }>;
      total: number;
      limit: number;
      offset: number;
    };
    const listedPages = listPayload.pages;
    expect(
      listedPages.some((item) => item.slug === slug && item.knowledge_level === 'concept_like' && item.authority_kind === 'accepted_ontology')
    ).toBe(true);
    expect(listedPages.find((item) => item.slug === slug)?.content ?? '').toBe('');
    expect(listPayload.total).toBeGreaterThanOrEqual(1);
  });

  it('wiki lint reports semantic knowledge_level and authority_kind mismatches', async () => {
    const domain = `wiki-lint-${randomUUID()}`;
    const pages = [
      {
        slug: 'unsupported-fact-like',
        title: '无支撑事实页',
        page_type: 'entity',
        knowledge_level: 'fact_like',
        authority_kind: 'compiled_summary',
        content: '这是一段足够长的事实型内容，但当前没有 link support，也不是 accepted ontology。'
      },
      {
        slug: 'candidate-concept-page',
        title: '候选概念页',
        page_type: 'concept',
        knowledge_level: 'concept_like',
        authority_kind: 'candidate_derived',
        content: '这是一段足够长的概念页内容，但 authority 仍停留在 candidate derived。'
      },
      {
        slug: 'accepted-summary-page',
        title: '被错误标记的来源摘要页',
        page_type: 'source_summary',
        knowledge_level: 'topic_like',
        authority_kind: 'accepted_ontology',
        content: '这是一段足够长的来源摘要内容，但 authority 被错误设置成 accepted ontology。'
      },
      {
        slug: 'candidate-principle',
        title: '候选原则页',
        page_type: 'comparison',
        knowledge_level: 'principle_like',
        authority_kind: 'candidate_derived',
        content: '这是一段足够长的原则性内容，用来触发 weak principle authority 检查。'
      },
      {
        slug: 'accepted-concept-fact-like',
        title: '被错误标记的概念页',
        page_type: 'concept',
        knowledge_level: 'fact_like',
        authority_kind: 'accepted_ontology',
        content: '这是一段足够长的概念页内容，用来触发 accepted concept level mismatch 检查。'
      },
      {
        slug: 'unsupported-generalization',
        title: '缺少支撑链接的归纳页',
        page_type: 'comparison',
        knowledge_level: 'generalization_like',
        authority_kind: 'compiled_summary',
        content: '这是一段足够长的归纳内容，但没有 concept 或 comparison 的链接支撑。'
      },
      {
        slug: 'single-support-generalization',
        title: '只有单点支撑的归纳页',
        page_type: 'comparison',
        knowledge_level: 'generalization_like',
        authority_kind: 'compiled_summary',
        content: '这是一段足够长的归纳内容，用来触发 multi-support 不足检查。'
      }
    ];

    for (const page of pages) {
      const res = await app.inject({
        method: 'POST',
        url: '/v2/wiki/page',
        payload: {
          domain,
          ...page,
          tags: [],
          confidence: 0.9
        }
      });
      expect(res.statusCode).toBe(200);
    }

    const lint = await app.inject({
      method: 'GET',
      url: `/v2/wiki/lint?domain=${encodeURIComponent(domain)}`
    });
    expect(lint.statusCode).toBe(200);
    const issueTypes = (lint.json().issues as Array<{ type: string }>).map((issue) => issue.type);
    expect(issueTypes).toContain('fact_like_without_support');
    expect(issueTypes).toContain('candidate_derived_concept_page');
    expect(issueTypes).toContain('accepted_ontology_summary_mismatch');
    expect(issueTypes).toContain('weak_principle_authority');
    expect(issueTypes).toContain('principle_without_method_authority');
    expect(issueTypes).toContain('accepted_concept_level_mismatch');
    expect(issueTypes).toContain('unsupported_generalization');
    expect(issueTypes).toContain('generalization_without_multi_support');
  });

  it('wiki search prefers accepted ontology concept pages when text rank ties', async () => {
    const domain = `wiki-rank-${randomUUID()}`;
    const sharedToken = `shared-rank-token-${randomUUID()}`;
    const pages = [
      {
        slug: 'candidate-concept',
        title: '候选概念页',
        content: `ranking tie ${sharedToken}`,
        page_type: 'concept',
        knowledge_level: 'fact_like',
        authority_kind: 'candidate_derived'
      },
      {
        slug: 'accepted-concept',
        title: '接受概念页',
        content: `ranking tie ${sharedToken}`,
        page_type: 'concept',
        knowledge_level: 'concept_like',
        authority_kind: 'accepted_ontology'
      }
    ];

    for (const page of pages) {
      const res = await app.inject({
        method: 'POST',
        url: '/v2/wiki/page',
        payload: {
          domain,
          ...page,
          tags: [],
          confidence: 0.8
        }
      });
      expect(res.statusCode).toBe(200);
    }

    const search = await app.inject({
      method: 'GET',
      url: `/v2/wiki/search?domain=${encodeURIComponent(domain)}&q=${encodeURIComponent(sharedToken)}&page_type=concept&limit=10`
    });
    expect(search.statusCode).toBe(200);
    const results = search.json().results as Array<{ slug: string }>;
    expect(results[0].slug).toBe('accepted-concept');
  });

  it('wiki search falls back to Chinese substring matches when full-text search misses', async () => {
    const domain = `wiki-cjk-fallback-${randomUUID()}`;
    const slug = `longquan-cjk-${randomUUID()}`;

    const upsert = await app.inject({
      method: 'POST',
      url: '/v2/wiki/page',
      payload: {
        domain,
        slug,
        title: '龙泉窑青瓷',
        content: '龙泉窑青瓷以温润青釉和窑口传统为核心知识点。',
        page_type: 'concept',
        knowledge_level: 'concept_like',
        authority_kind: 'accepted_ontology',
        tags: ['ceramics'],
        confidence: 0.86
      }
    });
    expect(upsert.statusCode).toBe(200);

    const search = await app.inject({
      method: 'GET',
      url: `/v2/wiki/search?domain=${encodeURIComponent(domain)}&q=${encodeURIComponent('龙泉')}&limit=10`
    });

    expect(search.statusCode).toBe(200);
    const results = search.json().results as Array<{ slug: string; title: string }>;
    expect(results.some((item) => item.slug === slug && item.title === '龙泉窑青瓷')).toBe(true);
  });

  it('wiki pages list supports limit and offset with summary payloads', async () => {
    const domain = `wiki-pages-pagination-${randomUUID()}`;
    for (const [slug, title] of [
      ['page-a', 'Page A'],
      ['page-b', 'Page B'],
      ['page-c', 'Page C'],
    ]) {
      const res = await app.inject({
        method: 'POST',
        url: '/v2/wiki/page',
        payload: {
          domain,
          slug,
          title,
          content: `${title} full content`,
          page_type: 'concept',
          knowledge_level: 'concept_like',
          authority_kind: 'accepted_ontology',
          tags: [],
          confidence: 0.8,
        }
      });
      expect(res.statusCode).toBe(200);
    }

    const list = await app.inject({
      method: 'GET',
      url: `/v2/wiki/pages?domain=${encodeURIComponent(domain)}&page_type=concept&limit=1&offset=1`
    });
    expect(list.statusCode).toBe(200);
    const payload = list.json() as {
      pages: Array<{ slug: string; content?: string }>;
      total: number;
      limit: number;
      offset: number;
    };
    const pages = payload.pages;
    expect(pages).toHaveLength(1);
    expect(pages[0].content ?? '').toBe('');
    expect(payload.total).toBe(3);
    expect(payload.limit).toBe(1);
    expect(payload.offset).toBe(1);
  });

  it('wiki search does not fallback to substring matching for non-CJK misses', async () => {
    const domain = `wiki-noncjk-fallback-${randomUUID()}`;
    const slug = `latin-substring-${randomUUID()}`;

    const upsert = await app.inject({
      method: 'POST',
      url: '/v2/wiki/page',
      payload: {
        domain,
        slug,
        title: 'Alphabeta ceramic note',
        content: 'The token alphabeta is intentionally stored as one word.',
        page_type: 'concept',
        knowledge_level: 'concept_like',
        authority_kind: 'accepted_ontology',
        tags: ['ceramics'],
        confidence: 0.8
      }
    });
    expect(upsert.statusCode).toBe(200);

    const search = await app.inject({
      method: 'GET',
      url: `/v2/wiki/search?domain=${encodeURIComponent(domain)}&q=${encodeURIComponent('beta')}&limit=10`
    });

    expect(search.statusCode).toBe(200);
    const results = search.json().results as Array<{ slug: string }>;
    expect(results.some((item) => item.slug === slug)).toBe(false);
  });

  it('wiki search does not use Latin chunks from mixed CJK queries as fallback terms', async () => {
    const domain = `wiki-mixed-cjk-fallback-${randomUUID()}`;
    const slug = `latin-mixed-substring-${randomUUID()}`;

    const upsert = await app.inject({
      method: 'POST',
      url: '/v2/wiki/page',
      payload: {
        domain,
        slug,
        title: 'Beta ceramic note',
        content: 'The token beta is intentionally present in this English page.',
        page_type: 'concept',
        knowledge_level: 'concept_like',
        authority_kind: 'accepted_ontology',
        tags: ['ceramics'],
        confidence: 0.8
      }
    });
    expect(upsert.statusCode).toBe(200);

    const search = await app.inject({
      method: 'GET',
      url: `/v2/wiki/search?domain=${encodeURIComponent(domain)}&q=${encodeURIComponent('龙 beta')}&limit=10`
    });

    expect(search.statusCode).toBe(200);
    const results = search.json().results as Array<{ slug: string }>;
    expect(results.some((item) => item.slug === slug)).toBe(false);
  });

  it('wiki link upsert resolves current pages by slug and writes wiki_page_link', async () => {
    const domain = `wiki-link-${randomUUID()}`;

    for (const page of [
      {
        slug: 'source-summary',
        title: '来源摘要页',
        content: '这是一个足够长的来源摘要页，用来测试 wiki link upsert。',
        page_type: 'source_summary',
        knowledge_level: 'topic_like',
        authority_kind: 'compiled_summary'
      },
      {
        slug: 'longquan-celadon',
        title: '龙泉青瓷',
        content: '这是一个足够长的概念页，用来测试 wiki link upsert。',
        page_type: 'concept',
        knowledge_level: 'concept_like',
        authority_kind: 'accepted_ontology'
      }
    ]) {
      const res = await app.inject({
        method: 'POST',
        url: '/v2/wiki/page',
        payload: {
          domain,
          ...page,
          tags: [],
          confidence: 0.8
        }
      });
      expect(res.statusCode).toBe(200);
    }

    const upsertLink = await app.inject({
      method: 'POST',
      url: '/v2/wiki/link',
      payload: {
        domain,
        from_slug: 'source-summary',
        to_slug: 'longquan-celadon',
        link_text: 'mentions'
      }
    });
    expect(upsertLink.statusCode).toBe(201);
    expect(upsertLink.json().status).toBe('created');

    const lint = await app.inject({
      method: 'GET',
      url: `/v2/wiki/lint?domain=${encodeURIComponent(domain)}`
    });
    expect(lint.statusCode).toBe(200);
    const issues = lint.json().issues as Array<{ issue_type: string; slug: string }>;
    const orphanSlugs = issues
      .filter((issue) => issue.issue_type === 'orphan_page')
      .map((issue) => issue.slug);
    expect(orphanSlugs).not.toContain('longquan-celadon');
  });
});

async function waitForPort(host: string, port: number): Promise<void> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const ready = await new Promise<boolean>((resolve) => {
      const socket = net.createConnection({ host, port });
      socket.once('connect', () => {
        socket.end();
        resolve(true);
      });
      socket.once('error', () => {
        resolve(false);
      });
    });

    if (ready) {
      return;
    }

    await new Promise((resolve) => setTimeout(resolve, 250));
  }

  throw new Error(`gateway backend did not become ready on ${host}:${port}`);
}

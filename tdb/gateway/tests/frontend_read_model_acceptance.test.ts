import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { createDbPool } from '../src/db/pool.js';
import {
  getBusinessObjectById,
  getLatestPageContextSnapshot,
  insertPageContextSnapshot,
  listBusinessExceptions,
  listBusinessObjectLinks,
  listBusinessRecommendations,
  upsertBusinessException,
  upsertBusinessObject,
  upsertBusinessObjectLink,
  upsertBusinessRecommendation
} from '../src/db/queries/frontend.queries.js';

const TEST_DB_URL = process.env.TEST_DATABASE_URL ?? process.env.DATABASE_URL;
const describeDb = TEST_DB_URL ? describe : describe.skip;
const MIGRATE_SCRIPT_PATH = fileURLToPath(new URL('../../scripts/db_migrate.sh', import.meta.url));
const TEST_SCHEMA = 'frontend_read_model_acceptance';
const PREVIOUS_PGOPTIONS = process.env.PGOPTIONS;

describeDb('enterprise frontend semantic read model', () => {
  let db: Awaited<ReturnType<typeof createDbPool>>;

  beforeAll(async () => {
    process.env.PGOPTIONS = `-c search_path=${TEST_SCHEMA},public`;
    execFileSync(
      'psql',
      [
        TEST_DB_URL!,
        '-v',
        'ON_ERROR_STOP=1',
        '-c',
        `DROP SCHEMA IF EXISTS ${TEST_SCHEMA} CASCADE; CREATE SCHEMA ${TEST_SCHEMA};`
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

    db = await createDbPool(TEST_DB_URL!);
  });

  afterAll(async () => {
    if (db) {
      await db.end();
    }

    if (PREVIOUS_PGOPTIONS === undefined) {
      delete process.env.PGOPTIONS;
    } else {
      process.env.PGOPTIONS = PREVIOUS_PGOPTIONS;
    }
  });

  it('stores and reads a business object semantic view', async () => {
    const contractId = `contract-${randomUUID()}`;
    const accountId = `account-${randomUUID()}`;

    await upsertBusinessObject(db, {
      objectId: accountId,
      objectType: 'account',
      displayName: 'ACME Corp',
      status: 'active',
      health: 'healthy',
      owner: 'amanda.cho',
      summary: 'Strategic enterprise account'
    });

    await upsertBusinessObject(db, {
      objectId: contractId,
      objectType: 'contract',
      displayName: 'ACME Renewal FY26',
      sourceSystem: 'clm',
      status: 'blocked',
      health: 'blocked',
      stage: 'legal_review',
      owner: 'jane.lee',
      summary: 'Renewal blocked by pending legal approval',
      currentState: {
        stage: 'legal_review',
        sla_due_at: '2026-03-12T09:00:00Z'
      },
      keyFacts: [
        { key: 'counterparty', label: 'Counterparty', value: 'ACME Corp' }
      ],
      metrics: [
        { key: 'sla', label: 'SLA', value: '18h remaining', severity: 'high' }
      ]
    });

    await upsertBusinessObjectLink(db, {
      srcObjectId: contractId,
      relation: 'account',
      dstObjectId: accountId,
      status: 'active',
      detailJson: { linked_from: 'crm_contract_sync' }
    });

    await upsertBusinessException(db, {
      exceptionId: `exc-${randomUUID()}`,
      objectId: contractId,
      queueContext: 'revops_contracts',
      code: 'LEGAL_APPROVAL_MISSING',
      title: 'Legal approval missing',
      severity: 'high',
      status: 'open',
      summary: 'Signature is blocked until legal approval is attached.',
      dueAt: '2026-03-12T09:00:00Z',
      owner: 'jane.lee'
    });

    await upsertBusinessRecommendation(db, {
      recommendationId: `rec-${randomUUID()}`,
      objectId: contractId,
      pageType: 'object_360',
      queueContext: 'revops_contracts',
      actionKey: 'request_legal_approval',
      label: 'Request legal approval',
      style: 'primary',
      reason: 'This is the only open blocker before signature.',
      confidence: 0.9,
      priority: 95,
      status: 'active'
    });

    await upsertBusinessRecommendation(db, {
      recommendationId: `rec-${randomUUID()}`,
      objectId: contractId,
      pageType: 'object_360',
      queueContext: 'revops_contracts',
      actionKey: 'escalate_deadline_risk',
      label: 'Escalate deadline risk',
      style: 'secondary',
      reason: 'Escalate if legal review cannot be completed today.',
      confidence: 0.7,
      priority: 60,
      status: 'active'
    });

    const object = await getBusinessObjectById(db, contractId);
    expect(object?.display_name).toBe('ACME Renewal FY26');
    expect(object?.health).toBe('blocked');
    expect(object?.current_state.stage).toBe('legal_review');

    const links = await listBusinessObjectLinks(db, contractId);
    expect(links).toHaveLength(1);
    expect(links[0].dst_object_id).toBe(accountId);

    const exceptions = await listBusinessExceptions(db, {
      objectId: contractId,
      status: 'open',
      limit: 10
    });
    expect(exceptions).toHaveLength(1);
    expect(exceptions[0].code).toBe('LEGAL_APPROVAL_MISSING');

    const recommendations = await listBusinessRecommendations(db, {
      objectId: contractId,
      status: 'active',
      limit: 10
    });
    expect(recommendations).toHaveLength(2);
    expect(recommendations[0].action_key).toBe('request_legal_approval');
    expect(recommendations[1].action_key).toBe('escalate_deadline_risk');
  });

  it('orders exception feed by severity then due time', async () => {
    const queueContext = `queue-${randomUUID()}`;

    await upsertBusinessException(db, {
      exceptionId: `exc-${randomUUID()}`,
      queueContext,
      code: 'LOW_SIGNAL',
      title: 'Low signal issue',
      severity: 'medium',
      status: 'open',
      dueAt: '2026-03-13T10:00:00Z'
    });

    await upsertBusinessException(db, {
      exceptionId: `exc-${randomUUID()}`,
      queueContext,
      code: 'CRITICAL_BLOCKER',
      title: 'Critical blocker',
      severity: 'critical',
      status: 'open',
      dueAt: '2026-03-14T10:00:00Z'
    });

    await upsertBusinessException(db, {
      exceptionId: `exc-${randomUUID()}`,
      queueContext,
      code: 'HIGH_SOON',
      title: 'High severity soon due',
      severity: 'high',
      status: 'open',
      dueAt: '2026-03-12T08:00:00Z'
    });

    const feed = await listBusinessExceptions(db, {
      queueContext,
      status: 'open',
      limit: 10
    });

    expect(feed[0].code).toBe('CRITICAL_BLOCKER');
    expect(feed[1].code).toBe('HIGH_SOON');
    expect(feed[2].code).toBe('LOW_SIGNAL');
  });

  it('stores and retrieves the latest page context snapshot', async () => {
    const objectId = `ticket-${randomUUID()}`;

    await upsertBusinessObject(db, {
      objectId,
      objectType: 'ticket',
      displayName: 'Payment failure incident',
      status: 'investigating',
      health: 'at_risk'
    });

    await insertPageContextSnapshot(db, {
      userId: 'user-1',
      role: 'operator',
      pageType: 'object_360',
      objectId,
      goal: 'Understand the current incident state',
      summaryJson: {
        title: 'Initial summary',
        health: 'watch'
      },
      currentStateJson: {
        stage: 'triage'
      }
    });

    await new Promise((resolve) => setTimeout(resolve, 5));

    await insertPageContextSnapshot(db, {
      userId: 'user-1',
      role: 'operator',
      pageType: 'object_360',
      objectId,
      goal: 'Understand the current incident state',
      summaryJson: {
        title: 'Updated summary',
        health: 'at_risk'
      },
      currentStateJson: {
        stage: 'tier_2_review'
      },
      recommendedActionsJson: [
        {
          action_key: 'contact_gateway_vendor',
          label: 'Contact gateway vendor'
        }
      ]
    });

    const latest = await getLatestPageContextSnapshot(db, {
      userId: 'user-1',
      role: 'operator',
      pageType: 'object_360',
      objectId
    });

    expect(latest?.summary_json.title).toBe('Updated summary');
    expect(latest?.current_state_json.stage).toBe('tier_2_review');
    expect(latest?.recommended_actions_json).toHaveLength(1);
  });
});

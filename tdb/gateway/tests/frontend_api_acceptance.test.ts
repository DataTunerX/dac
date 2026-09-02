import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { DatabasePool } from 'slonik';
import { createDbPool } from '../src/db/pool.js';

import {
  insertPageContextSnapshot,
  upsertBusinessException,
  upsertBusinessObject,
  upsertBusinessObjectLink,
  upsertBusinessRecommendation
} from '../src/db/queries/frontend.queries.js';
import { buildApp } from '../src/app.js';

const TEST_DB_URL = process.env.TEST_DATABASE_URL ?? process.env.DATABASE_URL;
const describeDb = TEST_DB_URL ? describe : describe.skip;
const MIGRATE_SCRIPT_PATH = fileURLToPath(new URL('../../scripts/db_migrate.sh', import.meta.url));
const TEST_SCHEMA = 'frontend_api_acceptance';
const PREVIOUS_PGOPTIONS = process.env.PGOPTIONS;

describeDb('enterprise frontend API behaviors', () => {
  let app: Awaited<ReturnType<typeof buildApp>>;
  let db: DatabasePool;

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
    app = await buildApp({
      logLevel: 'silent'
    });
  });

  afterAll(async () => {
    if (db) {
      await db.end();
    }
    if (app) {
      await app.close();
    }

    if (PREVIOUS_PGOPTIONS === undefined) {
      delete process.env.PGOPTIONS;
    } else {
      process.env.PGOPTIONS = PREVIOUS_PGOPTIONS;
    }
  });

  it('builds a live context pack from the semantic read model', async () => {
    const objectId = `contract-${randomUUID()}`;

    await upsertBusinessObject(db, {
      objectId,
      objectType: 'contract',
      displayName: 'ACME Renewal FY26',
      sourceSystem: 'clm',
      status: 'blocked',
      health: 'blocked',
      stage: 'legal_review',
      owner: 'jane.lee',
      summary: 'Renewal blocked by pending legal approval',
      currentState: {
        stage: 'legal_review'
      },
      keyFacts: [
        {
          key: 'counterparty',
          label: 'Counterparty',
          value: 'ACME Corp'
        }
      ],
      metrics: [
        {
          key: 'sla',
          label: 'SLA',
          value: '18h remaining',
          severity: 'high'
        }
      ]
    });

    await upsertBusinessException(db, {
      objectId,
      queueContext: 'revops_contracts',
      code: 'LEGAL_APPROVAL_MISSING',
      title: 'Legal approval missing',
      severity: 'high',
      status: 'open',
      summary: 'Signature is blocked until legal approval is attached.',
      owner: 'jane.lee',
      recommendedActionJson: {
        action_key: 'request_legal_approval',
        label: 'Request legal approval',
        style: 'primary'
      },
      evidenceJson: [
        {
          evidence_id: 'policy-1',
          kind: 'policy',
          label: 'Contract approval policy'
        }
      ]
    });

    await upsertBusinessRecommendation(db, {
      objectId,
      pageType: 'object_360',
      queueContext: 'revops_contracts',
      actionKey: 'request_legal_approval',
      label: 'Request legal approval',
      style: 'primary',
      reason: 'This is the only blocker before signature.',
      confidence: 0.9,
      priority: 95
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v2/context/pack',
      payload: {
        user_id: 'user-1',
        role: 'approver',
        page_type: 'object_360',
        object_ref: {
          object_id: objectId,
          object_type: 'contract',
          display_name: 'ACME Renewal FY26'
        }
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json().contract_version).toBe('business_frontend_v1');
    expect(res.json().summary.title).toBe('Renewal blocked by pending legal approval');
    expect(res.json().current_state.stage).toBe('legal_review');
    expect(res.json().exceptions).toHaveLength(1);
    expect(res.json().recommended_actions[0].action_key).toBe('request_legal_approval');
    expect(res.json().ui_blocks.some((block: { type: string }) => block.type === 'recommendation_block')).toBe(true);
  });

  it('prefers the latest context snapshot when one exists', async () => {
    const objectId = `ticket-${randomUUID()}`;

    await upsertBusinessObject(db, {
      objectId,
      objectType: 'ticket',
      displayName: 'Payment failure incident',
      status: 'investigating',
      health: 'at_risk',
      summary: 'Incident under review'
    });

    await insertPageContextSnapshot(db, {
      userId: 'user-2',
      role: 'operator',
      pageType: 'object_360',
      objectId,
      goal: 'Understand the latest payment failure',
      summaryJson: {
        title: 'Snapshot summary wins',
        status: 'investigating',
        health: 'at_risk'
      },
      currentStateJson: {
        stage: 'tier_2_review'
      },
      recentChangesJson: [
        {
          item_id: 'tl-1',
          timestamp: '2026-03-11T15:00:00Z',
          kind: 'state_change',
          title: 'Escalated to Tier 2'
        }
      ],
      recommendedActionsJson: [
        {
          action_key: 'contact_gateway_vendor',
          label: 'Contact gateway vendor'
        }
      ],
      uiBlocksJson: [
        {
          block_id: 'summary-1',
          type: 'summary_block',
          title: 'Snapshot Summary',
          summary: 'Snapshot summary wins'
        }
      ]
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v2/context/pack',
      payload: {
        user_id: 'user-2',
        role: 'operator',
        page_type: 'object_360',
        object_ref: {
          object_id: objectId,
          object_type: 'ticket',
          display_name: 'Payment failure incident'
        }
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json().summary.title).toBe('Snapshot summary wins');
    expect(res.json().recent_changes).toHaveLength(1);
    expect(res.json().recommended_actions[0].action_key).toBe('contact_gateway_vendor');
    expect(res.json().ui_blocks[0].title).toBe('Snapshot Summary');
  });

  it('returns object 360 with links, exceptions, recommendations, and snapshot timeline', async () => {
    const contractId = `contract-${randomUUID()}`;
    const accountId = `account-${randomUUID()}`;

    await upsertBusinessObject(db, {
      objectId: accountId,
      objectType: 'account',
      displayName: 'ACME Corp',
      status: 'active',
      health: 'healthy',
      summary: 'Strategic account'
    });

    await upsertBusinessObject(db, {
      objectId: contractId,
      objectType: 'contract',
      displayName: 'ACME Renewal FY26',
      status: 'blocked',
      health: 'blocked',
      stage: 'legal_review',
      owner: 'jane.lee',
      summary: 'Renewal blocked by pending legal approval',
      currentState: {
        artifacts: [
          {
            artifact_id: 'artifact-1',
            artifact_type: 'policy',
            name: 'Contract approval policy'
          }
        ],
        decisions: [
          {
            decision_id: 'decision-1',
            title: 'Escalate legal review',
            chosen_action: 'escalate_legal_review',
            created_at: '2026-03-11T12:00:00Z'
          }
        ]
      },
      metrics: [
        {
          key: 'sla',
          label: 'SLA',
          value: '18h remaining',
          severity: 'high'
        }
      ]
    });

    await upsertBusinessObjectLink(db, {
      srcObjectId: contractId,
      relation: 'account',
      dstObjectId: accountId,
      status: 'active'
    });

    await upsertBusinessException(db, {
      objectId: contractId,
      code: 'LEGAL_APPROVAL_MISSING',
      title: 'Legal approval missing',
      severity: 'high',
      status: 'open',
      summary: 'Signature is blocked until legal approval is attached.'
    });

    await upsertBusinessRecommendation(db, {
      objectId: contractId,
      pageType: 'object_360',
      actionKey: 'request_legal_approval',
      label: 'Request legal approval',
      style: 'primary',
      reason: 'This is the only blocker before signature.',
      confidence: 0.9,
      priority: 95
    });

    await insertPageContextSnapshot(db, {
      userId: 'user-3',
      role: 'approver',
      pageType: 'object_360',
      objectId: contractId,
      recentChangesJson: [
        {
          item_id: 'tl-1',
          timestamp: '2026-03-11T14:20:00Z',
          kind: 'approval',
          title: 'Finance approval completed'
        }
      ],
      summaryJson: {
        title: 'Role-aware summary',
        status: 'blocked',
        health: 'blocked'
      }
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v2/object/360',
      payload: {
        user_id: 'user-3',
        role: 'approver',
        object_ref: {
          object_id: contractId,
          object_type: 'contract',
          display_name: 'ACME Renewal FY26'
        }
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json().object.ref.object_id).toBe(contractId);
    expect(res.json().summary.title).toBe('Role-aware summary');
    expect(res.json().linked_objects).toHaveLength(1);
    expect(res.json().linked_objects[0].object.object_id).toBe(accountId);
    expect(res.json().timeline).toHaveLength(1);
    expect(res.json().artifacts).toHaveLength(1);
    expect(res.json().decisions).toHaveLength(1);
    expect(res.json().exceptions).toHaveLength(1);
    expect(res.json().recommended_actions).toHaveLength(1);
  });

  it('returns an exception feed ordered by severity and ranked actions', async () => {
    const queueContext = `workbench-${randomUUID()}`;

    await upsertBusinessException(db, {
      queueContext,
      code: 'LOW_SIGNAL',
      title: 'Low signal issue',
      severity: 'medium',
      status: 'open',
      dueAt: '2026-03-13T10:00:00Z',
      recommendedActionJson: {
        action_key: 'investigate_low_signal',
        label: 'Investigate low-signal issue',
        style: 'secondary',
        reason: 'This issue still needs triage.'
      }
    });

    await upsertBusinessException(db, {
      queueContext,
      code: 'CRITICAL_BLOCKER',
      title: 'Critical blocker',
      severity: 'critical',
      status: 'open',
      dueAt: '2026-03-14T10:00:00Z',
      recommendedActionJson: {
        action_key: 'escalate_immediately',
        label: 'Escalate immediately',
        style: 'primary',
        reason: 'Critical issue requires immediate escalation.'
      }
    });

    await upsertBusinessRecommendation(db, {
      queueContext,
      actionKey: 'triage_priority_queue',
      label: 'Triage priority queue',
      style: 'primary',
      reason: 'Critical and high-risk issues require immediate triage.',
      confidence: 0.88,
      priority: 97
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v2/exception/feed',
      payload: {
        user_id: 'user-queue',
        role: 'operator',
        queue_context: queueContext,
        limit: 10
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json().total_open).toBe(2);
    expect(res.json().items[0].code).toBe('CRITICAL_BLOCKER');
    expect(res.json().items[1].code).toBe('LOW_SIGNAL');
    expect(res.json().recommended_actions[0].action_key).toBe('triage_priority_queue');
    expect(
      res.json().recommended_actions.some(
        (item: { action_key: string }) => item.action_key === 'escalate_immediately'
      )
    ).toBe(true);
  });

  it('returns a decision brief for approval review flows', async () => {
    const supplierId = `supplier-${randomUUID()}`;

    await upsertBusinessObject(db, {
      objectId: supplierId,
      objectType: 'supplier',
      displayName: 'Northwind Logistics',
      status: 'pending_review',
      health: 'watch',
      owner: 'maya.chen',
      summary: 'Vendor onboarding review is ready for final approval.',
      currentState: {
        missing_prerequisites: [
          {
            key: 'tax_profile_normalized',
            label: 'Normalized tax profile',
            reason: 'The vendor tax profile is present but still flagged for formatting cleanup.',
            required_for: 'post-approval monitoring'
          }
        ],
        impact_preview: [
          {
            object: {
              object_id: supplierId,
              object_type: 'supplier',
              display_name: 'Northwind Logistics'
            },
            field: 'vendor_status',
            before: 'pending_review',
            after: 'approved',
            summary: 'Vendor becomes eligible for purchase order creation.'
          }
        ],
        evidence: [
          {
            evidence_id: 'artifact-w9-v2',
            kind: 'artifact_version',
            label: 'W-9 document v2',
            summary: 'Validated tax form received from supplier.',
            freshness: '2026-03-10T11:00:00Z'
          },
          {
            evidence_id: 'policy-vendor-onboarding',
            kind: 'policy',
            label: 'Vendor onboarding policy',
            summary: 'Lists required due diligence documents and approval conditions.',
            freshness: '2026-02-15T00:00:00Z'
          }
        ]
      }
    });

    await upsertBusinessException(db, {
      objectId: supplierId,
      code: 'TAX_PROFILE_CLEANUP',
      title: 'Tax profile cleanup pending',
      severity: 'low',
      status: 'open',
      summary: 'Finance monitoring should be added after approval until normalization is complete.'
    });

    await upsertBusinessRecommendation(db, {
      objectId: supplierId,
      pageType: 'approval_review',
      actionKey: 'approve_vendor_onboarding',
      label: 'Approve vendor onboarding',
      style: 'primary',
      reason: 'Required onboarding evidence is present and no blocking policy violation is active.',
      confidence: 0.83,
      priority: 96
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v2/decision/brief',
      payload: {
        user_id: 'approver-1',
        role: 'approver',
        approval_ref: 'approval-1001',
        object_ref: {
          object_id: supplierId,
          object_type: 'supplier',
          display_name: 'Northwind Logistics'
        }
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json().recommendation.disposition).toBe('approve');
    expect(res.json().recommendation.confidence).toBe(0.83);
    expect(res.json().missing_prerequisites).toHaveLength(1);
    expect(res.json().impact_preview).toHaveLength(1);
    expect(res.json().evidence).toHaveLength(2);
    expect(res.json().summary.title).toContain('Northwind Logistics');
    expect(
      res.json().ui_blocks.some((block: { type: string }) => block.type === 'approval_brief_block')
    ).toBe(true);
    expect(
      res.json().ui_blocks.some((block: { type: string }) => block.type === 'impact_preview_block')
    ).toBe(true);
  });

  it('returns proposed actions for an investigation workflow', async () => {
    const shipmentId = `shipment-${randomUUID()}`;

    await upsertBusinessObject(db, {
      objectId: shipmentId,
      objectType: 'order',
      displayName: 'Shipment 610',
      status: 'blocked',
      health: 'watch',
      owner: 'nina.patel',
      summary: 'Shipment is blocked at customs and needs remediation.',
      currentState: {
        missing_inputs_by_action: {
          request_customs_document: [
            {
              key: 'recipient_email',
              label: 'Recipient email',
              reason: 'The requester contact is missing from the shipment case.',
              required_for: 'request_customs_document'
            }
          ]
        },
        action_constraints: [
          'Escalation should only be used after one failed contact attempt.',
          'Document request requires outbound communication permission.'
        ],
        evidence: [
          {
            evidence_id: 'event-shipment-blocked',
            kind: 'event',
            label: 'Shipment blocked at customs',
            summary: 'Status changed to customs hold due to missing declaration form.',
            freshness: '2026-03-11T12:05:00Z'
          }
        ]
      }
    });

    await upsertBusinessRecommendation(db, {
      objectId: shipmentId,
      pageType: 'investigation_workspace',
      actionKey: 'request_customs_document',
      label: 'Request customs document',
      style: 'primary',
      reason: 'Missing customs documentation is the direct blocker.',
      confidence: 0.87,
      priority: 95
    });

    await upsertBusinessRecommendation(db, {
      objectId: shipmentId,
      pageType: 'investigation_workspace',
      actionKey: 'escalate_logistics_manager',
      label: 'Escalate logistics manager',
      style: 'secondary',
      reason: 'Escalation may be needed if the document cannot be obtained within SLA.',
      confidence: 0.65,
      priority: 72,
      requiresConfirmation: true
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v2/action/propose',
      payload: {
        user_id: 'operator-1',
        role: 'operator',
        page_type: 'investigation_workspace',
        intent: 'What should I do next to unblock this shipment?',
        object_ref: {
          object_id: shipmentId,
          object_type: 'order',
          display_name: 'Shipment 610'
        }
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json().proposed_actions).toHaveLength(2);
    expect(res.json().proposed_actions[0].action_key).toBe('request_customs_document');
    expect(res.json().missing_inputs).toHaveLength(1);
    expect(res.json().constraints).toHaveLength(2);
    expect(res.json().evidence).toHaveLength(1);
    expect(
      res.json().ui_blocks.some((block: { type: string }) => block.type === 'recommendation_block')
    ).toBe(true);
  });

  it('simulates an action with changes, blockers, and follow-ups', async () => {
    const shipmentId = `shipment-${randomUUID()}`;
    const caseId = `case-${randomUUID()}`;

    await upsertBusinessObject(db, {
      objectId: shipmentId,
      objectType: 'order',
      displayName: 'Shipment 610',
      status: 'customs_hold',
      health: 'watch',
      owner: 'nina.patel',
      summary: 'Shipment remains blocked after first contact attempt.'
    });

    await upsertBusinessObject(db, {
      objectId: caseId,
      objectType: 'case',
      displayName: 'Customs Hold Case',
      status: 'investigating',
      health: 'watch',
      owner: 'nina.patel',
      summary: 'Case is awaiting escalation review.',
      currentState: {
        action_simulations: {
          escalate_logistics_manager: {
            changes: [
              {
                object: {
                  object_id: caseId,
                  object_type: 'case',
                  display_name: 'Customs Hold Case'
                },
                field: 'owner',
                before: 'nina.patel',
                after: 'leo.garcia',
                summary: 'Ownership moves to the logistics manager.'
              },
              {
                object: {
                  object_id: shipmentId,
                  object_type: 'order',
                  display_name: 'Shipment 610'
                },
                field: 'priority',
                before: 'normal',
                after: 'high',
                summary: 'Escalated shipments are reprioritized for same-day handling.'
              }
            ],
            follow_up_actions: [
              {
                action_key: 'notify_customer_success',
                label: 'Notify customer after reassignment',
                style: 'secondary',
                reason: 'The customer should be updated once an escalation path is active.',
                confidence: 0.66,
                requires_confirmation: false
              }
            ],
            evidence: [
              {
                evidence_id: 'policy-escalation',
                kind: 'policy',
                label: 'Escalation policy',
                summary: 'Escalation is allowed after one unresolved contact attempt.',
                freshness: '2026-01-05T00:00:00Z'
              }
            ]
          }
        }
      }
    });

    await upsertBusinessObjectLink(db, {
      srcObjectId: caseId,
      relation: 'subject',
      dstObjectId: shipmentId,
      status: 'active'
    });

    await upsertBusinessRecommendation(db, {
      objectId: caseId,
      pageType: 'investigation_workspace',
      actionKey: 'escalate_logistics_manager',
      label: 'Escalate logistics manager',
      style: 'primary',
      reason: 'Escalation will shorten expected resolution time by routing the issue to the owning manager.',
      confidence: 0.78,
      priority: 91,
      requiresConfirmation: true
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v2/action/simulate',
      payload: {
        user_id: 'manager-1',
        role: 'manager',
        page_type: 'investigation_workspace',
        action_key: 'escalate_logistics_manager',
        object_ref: {
          object_id: caseId,
          object_type: 'case',
          display_name: 'Customs Hold Case'
        }
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json().simulation_status).toBe('needs_confirmation');
    expect(res.json().selected_action.action_key).toBe('escalate_logistics_manager');
    expect(res.json().affected_objects).toHaveLength(2);
    expect(res.json().changes).toHaveLength(2);
    expect(res.json().follow_up_actions).toHaveLength(1);
    expect(res.json().blockers).toHaveLength(0);
    expect(res.json().evidence).toHaveLength(1);
    expect(
      res.json().ui_blocks.some((block: { type: string }) => block.type === 'impact_preview_block')
    ).toBe(true);
  });

  it('returns 404 for unknown business object', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/object/360',
      payload: {
        object_ref: {
          object_id: 'missing-object',
          object_type: 'contract'
        }
      }
    });

    expect(res.statusCode).toBe(404);
    expect(res.json()).toMatchObject({
      error: {
        code: 'BUSINESS_OBJECT_NOT_FOUND'
      }
    });
  });
});

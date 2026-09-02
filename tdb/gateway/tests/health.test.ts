import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { buildApp } from '../src/app.js';

describe('gateway health endpoints', () => {
  let app: Awaited<ReturnType<typeof buildApp>>;

  beforeAll(async () => {
    app = await buildApp({
      logLevel: 'silent',
      databaseUrl: 'postgres://tdb:tdb@localhost:5432/tdb',
      enableDb: false
    });
  });

  afterAll(async () => {
    await app.close();
  });

  it('returns health for root endpoint', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/health'
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({
      status: 'ok',
      service: 'tdb-gateway',
      version: 'v2'
    });
  });

  it('returns health for v2 endpoint', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/health'
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({
      status: 'ok',
      service: 'tdb-gateway',
      version: 'v2'
    });
  });

  it('returns error envelope for db health when db is disabled', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/health/db'
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('does not expose cutover compatibility health metadata', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/health/cutover'
    });

    expect(res.statusCode).toBe(404);
  });

  it('returns db-not-configured for event append when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        case_id: '8f7cb2d7-38bc-4404-9adc-d4f95331b349',
        event_type: 'fact_observed',
        valid_time: '2026-02-21T00:00:00Z'
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns 400 for invalid event append payload', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/event/append',
      payload: {
        case_id: 'not-a-uuid',
        event_type: 'unknown',
        valid_time: 'bad-time'
      }
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns 413 with a body-too-large error envelope', async () => {
    const isolatedApp = await buildApp({
      logLevel: 'silent',
      databaseUrl: 'postgres://tdb:tdb@localhost:5432/tdb',
      enableDb: false,
      bodyLimit: 256
    });

    try {
      const res = await isolatedApp.inject({
        method: 'POST',
        url: '/v2/event/append',
        payload: {
          case_id: '8f7cb2d7-38bc-4404-9adc-d4f95331b349',
          event_type: 'fact_observed',
          valid_time: '2026-02-21T00:00:00Z',
          payload: {
            notes: 'x'.repeat(2048)
          }
        }
      });

      expect(res.statusCode).toBe(413);
      expect(res.json()).toMatchObject({
        error: {
          code: 'BODY_TOO_LARGE'
        }
      });
    } finally {
      await isolatedApp.close();
    }
  });

  it('returns db-not-configured for event read when db is disabled', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/event/read?case_id=8f7cb2d7-38bc-4404-9adc-d4f95331b349'
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns db-not-configured for state property upsert when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/state/property/upsert',
      payload: {
        object_id: '8f7cb2d7-38bc-4404-9adc-d4f95331b349',
        key: 'status',
        value: { label: 'active' },
        valid_from: '2026-02-21T00:00:00Z'
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns 400 for invalid state property asof payload', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/state/property/asof?object_id=not-a-uuid&key=k&as_of_valid_time=bad-time'
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns 400 for invalid state property why payload', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/state/property/why?object_id=not-a-uuid&key=k&as_of_valid_time=bad-time'
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns db-not-configured for state edge asof when db is disabled', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/state/edge/asof?src_id=8f7cb2d7-38bc-4404-9adc-d4f95331b349&as_of_valid_time=2026-02-21T00:00:00Z'
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns db-not-configured for artifact create when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/artifact/create',
      payload: {
        artifact_type: 'policy',
        name: 'Policy A'
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns db-not-configured for entity upsert when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/entity/upsert',
      payload: {
        entity_type: 'Person',
        display_name: 'Sun Wukong'
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns db-not-configured for context pack when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/context/pack',
      payload: {
        user_id: 'user-1',
        role: 'approver',
        page_type: 'object_360'
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns db-not-configured for exception feed when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/exception/feed',
      payload: {
        user_id: 'user-1',
        role: 'operator'
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns db-not-configured for decision brief when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/decision/brief',
      payload: {
        user_id: 'user-1',
        role: 'approver',
        approval_ref: 'approval-1'
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns db-not-configured for action propose when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/action/propose',
      payload: {
        user_id: 'user-1',
        role: 'operator',
        page_type: 'investigation_workspace',
        intent: 'What should I do next?'
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns db-not-configured for action simulate when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/action/simulate',
      payload: {
        user_id: 'user-1',
        role: 'manager',
        action_key: 'escalate_issue'
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns 400 for invalid object 360 payload', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/object/360',
      payload: {
        object_ref: {
          object_id: '',
          object_type: 'ticket'
        }
      }
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns 400 for invalid exception feed payload', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/exception/feed',
      payload: {
        user_id: '',
        role: 'not-a-role'
      }
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns 400 for invalid decision brief payload', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/decision/brief',
      payload: {
        user_id: '',
        role: 'approver',
        approval_ref: ''
      }
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns 400 for invalid action propose payload', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/action/propose',
      payload: {
        user_id: '',
        role: 'operator',
        page_type: 'investigation_workspace',
        intent: ''
      }
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns 400 for invalid action simulate payload', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/action/simulate',
      payload: {
        user_id: '',
        role: 'manager',
        action_key: ''
      }
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns 400 for invalid artifact version asof query', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/artifact/version/asof?artifact_id=bad-id&as_of_valid_time=bad-time'
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns db-not-configured for authority check when db is disabled', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/authority/check?grantee_id=8f7cb2d7-38bc-4404-9adc-d4f95331b349&action_type=approve&as_of_valid_time=2026-02-21T00:00:00Z'
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: { code: 'DB_NOT_CONFIGURED' }
    });
  });

  it('returns 400 for invalid ontology case explain payload', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/ontology/case/explain?case_id=bad-id'
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns db-not-configured for ontology alert explain when db is disabled', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/ontology/alert/explain?alert_id=1'
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: { code: 'DB_NOT_CONFIGURED' }
    });
  });

  it('returns 400 for invalid ontology ops run explain payload', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/ontology/ops/run/explain?run_id=bad-id'
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns 400 for invalid ontology concept get payload', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/ontology/concept/get?concept_id='
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns 400 for invalid ontology fact upsert-with-evidence payload', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/ontology/fact/upsert-with-evidence',
      payload: {
        src_concept_id: '',
        predicate: '',
        dst_concept_id: '',
        evidence: []
      }
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns 400 for invalid ontology concept neighbors payload', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/ontology/concept/neighbors?concept_id=&direction=sideways'
    });

    expect(res.statusCode).toBe(400);
  });

  it('returns db-not-configured for decision get when db is disabled', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/decision/get?case_id=8f7cb2d7-38bc-4404-9adc-d4f95331b349&event_seq=1&projection_version=v1'
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: { code: 'DB_NOT_CONFIGURED' }
    });
  });

  it('returns db-not-configured for decision explain when db is disabled', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/decision/explain?case_id=8f7cb2d7-38bc-4404-9adc-d4f95331b349&event_seq=1&projection_version=v1'
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: { code: 'DB_NOT_CONFIGURED' }
    });
  });

  it('returns db-not-configured for snapshot latest when db is disabled', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/snapshot/latest?case_id=8f7cb2d7-38bc-4404-9adc-d4f95331b349&projection_version=v1&target_seq=1'
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: { code: 'DB_NOT_CONFIGURED' }
    });
  });

  it('returns db-not-configured for search query when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/search/query',
      payload: {
        query: 'renshenguo'
      }
    });

    expect(res.statusCode).toBe(503);
    expect(res.json()).toMatchObject({
      error: { code: 'BACKEND_UNAVAILABLE' }
    });
  });

  it('returns db-not-configured for ingest events when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/ingest/events',
      payload: {
        stream_id: 'xiyou',
        items: [
          {
            event_type: 'fact_observed',
            valid_time: '2026-02-21T00:00:00Z',
            payload: { text: 'hello' }
          }
        ]
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: { code: 'DB_NOT_CONFIGURED' }
    });
  });

  it('returns db-not-configured for ingest property when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/ingest/property',
      payload: {
        stream_id: 'xiyou',
        items: [
          {
            object_id: '8f7cb2d7-38bc-4404-9adc-d4f95331b349',
            key: 'status',
            value: { label: 'active' },
            valid_from: '2026-02-21T00:00:00Z'
          }
        ]
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: { code: 'DB_NOT_CONFIGURED' }
    });
  });

  it('returns db-not-configured for ingest edge when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/ingest/edge',
      payload: {
        stream_id: 'xiyou',
        items: [
          {
            src_id: '8f7cb2d7-38bc-4404-9adc-d4f95331b349',
            predicate: 'knows',
            dst_id: '7012574d-b302-4f4c-8f2a-b1136804dd6a',
            valid_from: '2026-02-21T00:00:00Z'
          }
        ]
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: { code: 'DB_NOT_CONFIGURED' }
    });
  });

  it('executes plan endpoint for health op without db', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/plan/execute',
      payload: {
        version: 'tdb.queryplan.v2',
        steps: [
          {
            id: 's1',
            op: 'health.get',
            save_as: 'h'
          }
        ]
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({
      success: true,
      results: [{ id: 's1', op: 'health.get', ok: true }],
      vars: {
        h: {
          status: 'ok',
          service: 'tdb-gateway',
          version: 'v2'
        }
      }
    });
  });

  it('validates plan statically without db', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/plan/validate',
      payload: {
        version: 'tdb.queryplan.v2',
        context: {
          name: 'validate-name'
        },
        steps: [
          {
            id: 's1',
            op: 'health.get',
            save_as: 'health'
          },
          {
            id: 's2',
            op: 'entity.get',
            args: {
              entity_id: '${context.name}'
            }
          }
        ]
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({
      valid: true,
      execution_mode: 'safe',
      step_count: 2,
      mutating_step_count: 0,
      diagnostics: []
    });
    expect(res.json().steps[1].context_dependencies).toEqual(['context.name']);
  });

  it('explains step dependencies and previews args without db', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/plan/explain',
      payload: {
        version: 'tdb.queryplan.v2',
        context: {
          display_name: 'Tripitaka'
        },
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
            }
          }
        ]
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json().valid).toBe(true);
    expect(res.json().steps[0].args_preview.display_name).toBe('Tripitaka');
    expect(res.json().steps[1].var_dependencies).toEqual(['entity']);
  });

  it('dry-runs plan by executing reads and skipping writes without db', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/plan/dry-run',
      payload: {
        version: 'tdb.queryplan.v2',
        steps: [
          {
            id: 's1',
            op: 'health.get',
            save_as: 'health'
          },
          {
            id: 's2',
            op: 'entity.upsert',
            args: {
              entity_type: 'character',
              display_name: 'dry-run-only'
            },
            save_as: 'entity'
          }
        ]
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({
      dry_run: true,
      success: true,
      results: [
        { id: 's1', ok: true },
        { id: 's2', ok: true, dry_run_skipped: true, would_mutate: true }
      ]
    });
    expect(res.json().vars.entity.skipped_write).toBe(true);
  });

  it('replays plan with execution trace without db', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/plan/replay',
      payload: {
        version: 'tdb.queryplan.v2',
        context: {
          enabled: true
        },
        steps: [
          {
            id: 's1',
            op: 'health.get',
            save_as: 'health'
          },
          {
            id: 's2',
            op: 'health.db',
            when: '${context.enabled}',
            on_error: 'continue'
          }
        ]
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json().replay).toBe(true);
    expect(res.json().trace).toHaveLength(2);
    expect(res.json().trace[0]).toMatchObject({
      id: 's1',
      status: 'executed'
    });
    expect(res.json().trace[1]).toMatchObject({
      id: 's2',
      status: 'failed',
      when_result: true
    });
    expect(res.json().trace[0].vars_after.health.status).toBe('ok');
    expect(res.json().trace[1].error.code).toBe('DB_NOT_CONFIGURED');
  });

  it('returns db-not-configured for persisted plan run lookup when db is disabled', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/plan/run/get?plan_id=8f7cb2d7-38bc-4404-9adc-d4f95331b349'
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns db-not-configured for persisted plan run list when db is disabled', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/plan/run/list?execution_kind=replay&limit=5'
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('returns db-not-configured for replay by id when db is disabled', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/plan/replay/by-id',
      payload: {
        plan_id: '8f7cb2d7-38bc-4404-9adc-d4f95331b349'
      }
    });

    expect(res.statusCode).toBe(500);
    expect(res.json()).toMatchObject({
      error: {
        code: 'DB_NOT_CONFIGURED'
      }
    });
  });

  it('plan search.query returns backend-unavailable when the rust backend is unreachable', async () => {
    const isolatedApp = await buildApp({
      logLevel: 'silent',
      databaseUrl: 'postgres://tdb:tdb@localhost:5432/unused',
      enableDb: false,
      backend: {
        address: '127.0.0.1:65535',
        timeoutMs: 50
      }
    });

    const res = await isolatedApp.inject({
      method: 'POST',
      url: '/v2/plan/execute',
      payload: {
        version: 'tdb.queryplan.v2',
        execution_mode: 'safe',
        goal: 'exercise search query failure mapping',
        steps: [
          {
            id: 'search',
            op: 'search.query',
            args: {
              query: 'renshenguo'
            }
          }
        ]
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json().success).toBe(false);
    expect(res.json().results[0].error.code).toBe('BACKEND_UNAVAILABLE');

    await isolatedApp.close();
  });

  it('plan endpoint returns step error and stops on fail policy', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/v2/plan/execute',
      payload: {
        version: 'tdb.queryplan.v2',
        steps: [
          {
            id: 's1',
            op: 'health.db'
          },
          {
            id: 's2',
            op: 'health.get'
          }
        ]
      }
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({
      success: false,
      results: [
        {
          id: 's1',
          op: 'health.db',
          ok: false,
          error: { code: 'DB_NOT_CONFIGURED' }
        }
      ]
    });
  });
});

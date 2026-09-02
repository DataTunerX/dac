import fs from 'node:fs';

import { FormatRegistry } from '@sinclair/typebox';
import { Value } from '@sinclair/typebox/value';
import { describe, expect, it } from 'vitest';

import {
  ActionProposeRequestSchema,
  ActionProposeResponseSchema,
  ActionSimulateRequestSchema,
  ActionSimulateResponseSchema,
  ContextPackRequestSchema,
  ContextPackResponseSchema,
  DecisionBriefRequestSchema,
  DecisionBriefResponseSchema,
  ExceptionFeedRequestSchema,
  ExceptionFeedResponseSchema,
  Object360RequestSchema,
  Object360ResponseSchema
} from '../src/schema/v2/frontend.js';

FormatRegistry.Set('date-time', () => true);

function readExampleJson(relativePathFromTestFile: string): unknown {
  return JSON.parse(fs.readFileSync(new URL(relativePathFromTestFile, import.meta.url), 'utf-8'));
}

describe('enterprise frontend contract schemas', () => {
  it('validates frozen response examples', () => {
    const fixtures = [
      {
        schema: ContextPackResponseSchema,
        file: '../../docs/business_frontend_contract_examples/context_pack.response.json'
      },
      {
        schema: Object360ResponseSchema,
        file: '../../docs/business_frontend_contract_examples/object_360.response.json'
      },
      {
        schema: ExceptionFeedResponseSchema,
        file: '../../docs/business_frontend_contract_examples/exception_feed.response.json'
      },
      {
        schema: DecisionBriefResponseSchema,
        file: '../../docs/business_frontend_contract_examples/decision_brief.response.json'
      },
      {
        schema: ActionProposeResponseSchema,
        file: '../../docs/business_frontend_contract_examples/action_propose.response.json'
      },
      {
        schema: ActionSimulateResponseSchema,
        file: '../../docs/business_frontend_contract_examples/action_simulate.response.json'
      }
    ] as const;

    for (const fixture of fixtures) {
      const payload = readExampleJson(fixture.file);
      const errors = [...Value.Errors(fixture.schema, payload)].map((error) => ({
        path: error.path,
        message: error.message,
        value: error.value
      }));
      expect(errors, fixture.file).toEqual([]);
    }
  });

  it('accepts representative frontend request payloads', () => {
    const requests = [
      {
        schema: ContextPackRequestSchema,
        payload: {
          user_id: 'user-1',
          role: 'approver',
          page_type: 'approval_review',
          object_ref: {
            object_id: 'contract-1042',
            object_type: 'contract',
            display_name: 'ACME Renewal 2026'
          },
          goal: 'Review whether this renewal can be approved today'
        }
      },
      {
        schema: Object360RequestSchema,
        payload: {
          user_id: 'user-2',
          role: 'manager',
          object_ref: {
            object_id: 'ticket-8821',
            object_type: 'ticket',
            display_name: 'Payment failure for enterprise renewal'
          },
          include_sections: ['timeline', 'exceptions', 'artifacts']
        }
      },
      {
        schema: ExceptionFeedRequestSchema,
        payload: {
          user_id: 'user-3',
          role: 'operator',
          queue_context: 'north_america_ops',
          limit: 25
        }
      },
      {
        schema: DecisionBriefRequestSchema,
        payload: {
          user_id: 'user-4',
          role: 'approver',
          approval_ref: 'approval-1001',
          object_ref: {
            object_id: 'vendor-330',
            object_type: 'supplier',
            display_name: 'Northwind Logistics'
          }
        }
      },
      {
        schema: ActionProposeRequestSchema,
        payload: {
          user_id: 'user-5',
          role: 'operator',
          page_type: 'investigation_workspace',
          intent: 'What should I do next to unblock this shipment?',
          object_ref: {
            object_id: 'shipment-610',
            object_type: 'order',
            display_name: 'Shipment 610'
          }
        }
      },
      {
        schema: ActionSimulateRequestSchema,
        payload: {
          user_id: 'user-6',
          role: 'manager',
          page_type: 'investigation_workspace',
          action_key: 'escalate_logistics_manager',
          object_ref: {
            object_id: 'case-778',
            object_type: 'case',
            display_name: 'Customs Hold Case'
          },
          args: {
            reason: 'Shipment is still blocked after contact attempt'
          }
        }
      }
    ] as const;

    for (const request of requests) {
      expect(Value.Check(request.schema, request.payload)).toBe(true);
    }
  });
});

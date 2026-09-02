import type { Static } from '@sinclair/typebox';

import { MemoryRecordDecisionRequestSchema, MemoryRecordDecisionResponseSchema } from '../../schema/v2/memory.js';

export type RecordDecisionCommand = Static<typeof MemoryRecordDecisionRequestSchema>;
export type RecordDecisionResult = Static<typeof MemoryRecordDecisionResponseSchema>;

export type MemoryDecisionStore = {
  recordDecision(command: RecordDecisionCommand): Promise<RecordDecisionResult>;
};

export function buildRecordDecisionCommand(input: RecordDecisionCommand): RecordDecisionCommand {
  return {
    ...input,
    decision: input.decision.trim(),
    rationale: input.rationale.trim(),
    topic_id: input.topic_id.trim(),
    run_id: input.run_id?.trim(),
    idempotency_key: input.idempotency_key?.trim(),
    alternatives_considered: input.alternatives_considered?.map((value) => value.trim()).filter(Boolean),
    entity_ids: input.entity_ids?.map((value) => value.trim()).filter(Boolean),
    consequences: input.consequences?.map((value) => value.trim()).filter(Boolean),
    legacy_decision: input.legacy_decision
      ? {
          ...input.legacy_decision,
          projection_version: input.legacy_decision.projection_version.trim(),
          chosen_action: input.legacy_decision.chosen_action.trim(),
          constraints_hit: input.legacy_decision.constraints_hit?.map((value) => value.trim()).filter(Boolean),
        }
      : undefined,
  };
}

export async function recordDecision(
  store: MemoryDecisionStore,
  input: RecordDecisionCommand,
): Promise<RecordDecisionResult> {
  const command = buildRecordDecisionCommand(input);
  return store.recordDecision(command);
}

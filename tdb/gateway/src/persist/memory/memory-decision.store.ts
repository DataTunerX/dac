import type { DatabasePool } from 'slonik';

import { upsertDecision } from '../../db/queries/decision.queries.js';
import { findMemoryDecisionByIdempotencyKey, insertMemoryDecision } from '../../db/queries/memory-decision.queries.js';
import type { MemoryDecisionStore, RecordDecisionCommand, RecordDecisionResult } from '../../domain/memory/record-decision.js';

export class GatewayMemoryDecisionStore implements MemoryDecisionStore {
  constructor(private readonly db: DatabasePool) {
  }

  async recordDecision(command: RecordDecisionCommand): Promise<RecordDecisionResult> {
    const existing =
      command.idempotency_key
        ? await findMemoryDecisionByIdempotencyKey(this.db, command.idempotency_key)
        : undefined;

    if (existing) {
      return {
        decision_id: existing.memory_decision_id,
        status: 'deduplicated',
        stored_at: existing.created_at,
        topic_id: existing.task_id,
        run_id: existing.run_id,
        deduplicated: true,
        provenance_summary: {
          evidence_count: existing.source_evidence.length,
          entity_count: existing.entity_ids.length,
        },
      };
    }

    const inserted = await this.db.transaction(async (trx) => {
      const created = await insertMemoryDecision(trx, {
        taskId: command.topic_id,
        runId: command.run_id,
        decisionText: command.decision,
        rationaleText: command.rationale,
        alternativesConsidered: command.alternatives_considered ?? [],
        sourceEvidence: command.source_evidence as Array<Record<string, unknown>>,
        entityIds: command.entity_ids ?? [],
        confidence: command.confidence,
        author: (command.author as Record<string, unknown> | undefined) ?? {},
        decisionTimestamp: command.timestamp,
        consequences: command.consequences ?? [],
        metadata: (command.metadata as Record<string, unknown> | undefined) ?? {},
        idempotencyKey: command.idempotency_key,
      });

      if (command.legacy_decision) {
        await upsertDecision(trx, {
          caseId: command.legacy_decision.case_id,
          eventSeq: command.legacy_decision.event_seq,
          projectionVersion: command.legacy_decision.projection_version,
          chosenAction: command.legacy_decision.chosen_action,
          candidates: command.legacy_decision.candidates ?? [],
          scores: command.legacy_decision.scores ?? {},
          constraintsHit: command.legacy_decision.constraints_hit ?? [],
          detail: {
            memory_decision_id: created.memory_decision_id,
            ...(command.legacy_decision.detail ?? {}),
          },
        });
      }

      return created;
    });

    return {
      decision_id: inserted.memory_decision_id,
      status: 'recorded',
      stored_at: inserted.created_at,
      topic_id: inserted.task_id,
      run_id: inserted.run_id,
      deduplicated: false,
      provenance_summary: {
        evidence_count: inserted.source_evidence.length,
        entity_count: inserted.entity_ids.length,
      },
    };
  }
}

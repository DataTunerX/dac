import type { DatabasePool } from 'slonik';

import {
  findMemoryEpisodeSummaryByIdempotencyKey,
  insertMemoryEpisodeSummary,
} from '../../db/queries/memory-episode-summary.queries.js';
import type {
  MemoryEpisodeSummaryStore,
  RecordEpisodeSummaryCommand,
  RecordEpisodeSummaryResult,
} from '../../domain/memory/record-episode-summary.js';

export class GatewayMemoryEpisodeSummaryStore implements MemoryEpisodeSummaryStore {
  constructor(private readonly db: DatabasePool) {
  }

  async recordEpisodeSummary(command: RecordEpisodeSummaryCommand): Promise<RecordEpisodeSummaryResult> {
    const existing =
      command.idempotency_key
        ? await findMemoryEpisodeSummaryByIdempotencyKey(this.db, command.idempotency_key)
        : undefined;

    if (existing) {
      return {
        episode_summary_id: existing.episode_summary_id,
        status: 'deduplicated',
        stored_at: existing.created_at,
        topic_id: command.topic_id,
        run_id: existing.run_id,
        deduplicated: true,
        provenance_summary: {
          evidence_count: existing.source_evidence.length,
          entity_count: existing.entity_ids.length,
        },
      };
    }

    const inserted = await insertMemoryEpisodeSummary(this.db, {
      episodeLabel: command.episode_label,
      taskId: command.topic_id,
      runId: command.run_id,
      sessionId: command.session_id,
      summaryText: command.summary,
      outcomes: command.outcomes ?? [],
      keyFacts: (command.key_facts as Array<Record<string, unknown>> | undefined) ?? [],
      decisions: command.decisions ?? [],
      unresolvedQuestions: command.unresolved_questions ?? [],
      sourceEvidence: command.source_evidence as Array<Record<string, unknown>>,
      entityIds: command.entity_ids ?? [],
      confidence: command.confidence,
      author: (command.author as Record<string, unknown> | undefined) ?? {},
      summaryTimestamp: command.timestamp,
      metadata: (command.metadata as Record<string, unknown> | undefined) ?? {},
      idempotencyKey: command.idempotency_key,
    });

    return {
      episode_summary_id: inserted.episode_summary_id,
      status: 'recorded',
      stored_at: inserted.created_at,
      topic_id: command.topic_id,
      run_id: inserted.run_id,
      deduplicated: false,
      provenance_summary: {
        evidence_count: inserted.source_evidence.length,
        entity_count: inserted.entity_ids.length,
      },
    };
  }
}

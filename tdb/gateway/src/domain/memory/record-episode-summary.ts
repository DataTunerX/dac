import type { Static } from '@sinclair/typebox';

import {
  MemoryRecordEpisodeSummaryRequestSchema,
  MemoryRecordEpisodeSummaryResponseSchema,
} from '../../schema/v2/memory.js';

export type RecordEpisodeSummaryCommand = Static<typeof MemoryRecordEpisodeSummaryRequestSchema>;
export type RecordEpisodeSummaryResult = Static<typeof MemoryRecordEpisodeSummaryResponseSchema>;

export type MemoryEpisodeSummaryStore = {
  recordEpisodeSummary(command: RecordEpisodeSummaryCommand): Promise<RecordEpisodeSummaryResult>;
};

export function buildRecordEpisodeSummaryCommand(
  input: RecordEpisodeSummaryCommand,
): RecordEpisodeSummaryCommand {
  return {
    ...input,
    episode_label: input.episode_label?.trim(),
    topic_id: input.topic_id.trim(),
    run_id: input.run_id?.trim(),
    session_id: input.session_id?.trim(),
    summary: input.summary.trim(),
    outcomes: input.outcomes?.map((value) => value.trim()).filter(Boolean),
    decisions: input.decisions?.map((value) => value.trim()).filter(Boolean),
    unresolved_questions: input.unresolved_questions?.map((value) => value.trim()).filter(Boolean),
    entity_ids: input.entity_ids?.map((value) => value.trim()).filter(Boolean),
    idempotency_key: input.idempotency_key?.trim(),
  };
}

export async function recordEpisodeSummary(
  store: MemoryEpisodeSummaryStore,
  input: RecordEpisodeSummaryCommand,
): Promise<RecordEpisodeSummaryResult> {
  const command = buildRecordEpisodeSummaryCommand(input);
  return store.recordEpisodeSummary(command);
}

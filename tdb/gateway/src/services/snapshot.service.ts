import type { Static } from '@sinclair/typebox';

import type { GatewayBackendClient, SnapshotRecord } from '../clients/gateway_backend.types.js';
import { SnapshotLatestQuerySchema, SnapshotWriteRequestSchema } from '../schema/v2/snapshot.js';

export type SnapshotWriteRequest = Static<typeof SnapshotWriteRequestSchema>;
export type SnapshotLatestQuery = Static<typeof SnapshotLatestQuerySchema>;

export type SnapshotDto = {
  snapshot_id: string;
  case_id: string;
  event_seq: number;
  projection_version: string;
  state_blob: Record<string, unknown>;
  state_hash?: string;
  created_at: string;
};

export class SnapshotService {
  constructor(private readonly backend: GatewayBackendClient) {}

  async writeSnapshot(request: SnapshotWriteRequest): Promise<SnapshotDto> {
    const record = await this.backend.writeSnapshot({
      case_id: request.case_id,
      event_seq: request.event_seq,
      projection_version: request.projection_version,
      state_blob_json: JSON.stringify(request.state_blob ?? {}),
      state_hash: request.state_hash ?? ''
    });

    return mapSnapshot(record);
  }

  async latestSnapshot(query: SnapshotLatestQuery): Promise<SnapshotDto | undefined> {
    const record = await this.backend.getLatestSnapshot({
      case_id: query.case_id,
      projection_version: query.projection_version,
      target_seq: query.target_seq
    });

    return record ? mapSnapshot(record) : undefined;
  }
}

function mapSnapshot(record: SnapshotRecord): SnapshotDto {
  let state_blob: Record<string, unknown> = {};
  try {
    state_blob = JSON.parse(record.state_blob_json);
  } catch (e) {
    // Ignore
  }

  return {
    snapshot_id: record.snapshot_id,
    case_id: record.case_id,
    event_seq: Number(record.event_seq),
    projection_version: record.projection_version,
    state_blob,
    state_hash: record.state_hash || undefined,
    created_at: record.created_at
  };
}

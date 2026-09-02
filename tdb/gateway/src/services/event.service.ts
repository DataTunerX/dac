import type { Static } from '@sinclair/typebox';

import { TdbError } from '../errors/tdb_error.js';
import type { GatewayBackendClient, EventItem } from '../clients/gateway_backend.types.js';
import { EventAppendRequestSchema, EventReadQuerySchema } from '../schema/v2/event.js';

export type EventAppendRequest = Static<typeof EventAppendRequestSchema>;
export type EventReadQuery = Static<typeof EventReadQuerySchema>;

export type EventAppendResult = {
  event_id: string;
  event_seq: number;
  system_time: string;
};

export type EventReadItem = {
  event_id: string;
  case_id: string;
  event_seq: number;
  event_type: string;
  actor_id?: string;
  subject_id?: string;
  object_id?: string;
  payload: Record<string, unknown>;
  valid_time: string;
  system_time: string;
};

export class EventService {
  constructor(
    private readonly backend: GatewayBackendClient
  ) {}

  async appendEvent(request: EventAppendRequest): Promise<EventAppendResult> {
    if (!request.case_id && !request.stream_id) {
      throw new TdbError(
        'MISSING_CASE_OR_STREAM',
        400,
        'Either case_id or stream_id must be provided'
      );
    }

    const res = await this.backend.appendEvent({
      case_id: request.case_id,
      stream_id: request.stream_id,
      event_type: request.event_type,
      actor_id: request.actor_id,
      subject_id: request.subject_id,
      object_id: request.object_id,
      payload_json: JSON.stringify(request.payload ?? {}),
      event_text: request.event_text ?? extractTextFromPayload(request.payload),
      embedding: request.embedding,
      embedding_model: request.embedding_model,
      valid_time: request.valid_time,
      system_time: request.system_time
    });

    return {
      event_id: res.event_id,
      event_seq: res.event_seq,
      system_time: normalizeIso(res.system_time)
    };
  }

  async readEvents(query: EventReadQuery): Promise<EventReadItem[]> {
    if (
      typeof query.from_seq === 'number' &&
      typeof query.to_seq === 'number' &&
      query.from_seq > query.to_seq
    ) {
      throw new TdbError(
        'INVALID_EVENT_RANGE',
        400,
        'from_seq must be less than or equal to to_seq'
      );
    }

    const items = await this.backend.getEvents({
      case_id: query.case_id,
      from_seq: query.from_seq,
      to_seq: query.to_seq,
      limit: query.limit
    });

    return items.map(mapEventItem);
  }
}

function mapEventItem(item: EventItem): EventReadItem {
  let payload: Record<string, unknown> = {};
  try {
    payload = JSON.parse(item.payload_json);
  } catch (e) {
    // Ignore parse error
  }

  return {
    event_id: item.event_id,
    case_id: item.case_id,
    event_seq: item.event_seq,
    event_type: item.event_type,
    actor_id: item.actor_id || undefined,
    subject_id: item.subject_id || undefined,
    object_id: item.object_id || undefined,
    payload,
    valid_time: normalizeIso(item.valid_time),
    system_time: normalizeIso(item.system_time)
  };
}

function normalizeIso(value: string): string {
  return new Date(value).toISOString();
}

function extractTextFromPayload(
  payload?: Record<string, unknown>
): string | undefined {
  if (!payload) {
    return undefined;
  }
  const candidate = payload.text;
  return typeof candidate === 'string' ? candidate : undefined;
}

import { createHash, randomUUID } from 'node:crypto';

import type { Static } from '@sinclair/typebox';

import { EVENT_TYPES } from '../domain/event.js';
import { insertArtifact, insertArtifactVersion } from '../db/queries/artifact.queries.js';
import {
  IngestArtifactsRequestSchema,
  IngestBundleRequestSchema,
  IngestEdgeRequestSchema,
  IngestEntitiesRequestSchema,
  IngestEventsRequestSchema,
  IngestPropertyRequestSchema,
  IngestTextRequestSchema
} from '../schema/v2/ingest.js';
import type { GatewayBackendClient } from '../clients/gateway_backend.types.js';
import { EntityService } from './entity.service.js';
import { EventService } from './event.service.js';
import { StateService } from './state.service.js';
import { ArtifactService } from './artifact.service.js';

type IngestEntitiesRequest = Static<typeof IngestEntitiesRequestSchema>;
type IngestArtifactsRequest = Static<typeof IngestArtifactsRequestSchema>;
type IngestBundleRequest = Static<typeof IngestBundleRequestSchema>;
type IngestEventsRequest = Static<typeof IngestEventsRequestSchema>;
type IngestTextRequest = Static<typeof IngestTextRequestSchema>;
type IngestPropertyRequest = Static<typeof IngestPropertyRequestSchema>;
type IngestEdgeRequest = Static<typeof IngestEdgeRequestSchema>;

type IngestErrorItem = {
  index: number;
  code: string;
  message: string;
};

type IngestRefState = {
  entity_ref_to_id?: Record<string, string>;
  artifact_ref_to_id?: Record<string, string>;
  artifact_ref_to_version_id?: Record<string, string>;
  event_ref_to_id?: Record<string, string>;
};

type IngestResponseBase = {
  ingest_run_id: string;
  stream_id: string;
  accepted: number;
  rejected: number;
  errors: IngestErrorItem[];
  ref_state_delta: IngestRefState;
};

type IngestEntityResult = {
  index: number;
  entity_ref?: string;
  entity_id: string;
};

type IngestArtifactResult = {
  index: number;
  artifact_ref?: string;
  artifact_id: string;
  artifact_version_ids: string[];
};

type IngestEventResult = {
  index: number;
  event_ref?: string;
  event_id: string;
};

type IngestEntitiesResponse = IngestResponseBase & {
  results: IngestEntityResult[];
};

type IngestArtifactsResponse = IngestResponseBase & {
  results: IngestArtifactResult[];
};

type IngestEventsResponse = IngestResponseBase & {
  event_ids: string[];
  results: IngestEventResult[];
};

type IngestPropertyResult = {
  index: number;
  property_state_id: string;
};

type IngestPropertyResponse = IngestResponseBase & {
  results: IngestPropertyResult[];
};

type IngestEdgeResult = {
  index: number;
  edge_state_id: string;
};

type IngestEdgeResponse = IngestResponseBase & {
  results: IngestEdgeResult[];
};

type IngestBundleResponse = {
  ingest_run_id: string;
  stream_id: string;
  ref_state: IngestRefState;
  totals: {
    accepted: number;
    rejected: number;
    errors: number;
  };
  phases: {
    entities: IngestEntitiesResponse;
    artifacts: IngestArtifactsResponse;
    events: IngestEventsResponse;
    properties: IngestPropertyResponse;
    edges: IngestEdgeResponse;
  };
};

const EVENT_TYPE_SET = new Set<string>(EVENT_TYPES);

export class IngestService {
  private readonly entityService: EntityService;
  private readonly eventService: EventService;
  private readonly stateService: StateService;
  private readonly artifactService: ArtifactService;

  constructor(
    private readonly backend: GatewayBackendClient
  ) {
    this.entityService = new EntityService(backend);
    this.eventService = new EventService(backend);
    this.stateService = new StateService(backend);
    this.artifactService = new ArtifactService(backend);
  }

  async ingestEntities(request: IngestEntitiesRequest): Promise<IngestEntitiesResponse> {
    const ingestRunId = request.ingest_run_id ?? randomUUID();
    const errors: IngestErrorItem[] = [];
    const results: IngestEntityResult[] = [];
    const refStateDelta: IngestRefState = { entity_ref_to_id: {} };

    let accepted = 0;
    let rejected = 0;
    for (const [index, item] of request.items.entries()) {
      try {
        const entityId = request.dry_run
          ? item.entity_id ?? randomUUID()
          : (
              await this.entityService.upsert({
                entity_id: item.entity_id,
                entity_type: item.entity_type,
                display_name: item.display_name,
                external_refs: item.external_refs,
                status: item.status
              })
            ).entity_id;

        const entityRef = item.entity_ref;
        if (entityRef) {
          refStateDelta.entity_ref_to_id![entityRef] = entityId;
        }

        results.push({
          index,
          entity_ref: entityRef,
          entity_id: entityId
        });
        accepted += 1;
      } catch (error) {
        rejected += 1;
        errors.push(toIngestError(index, error));
      }
    }

    return {
      ingest_run_id: ingestRunId,
      stream_id: request.stream_id,
      accepted,
      rejected,
      errors,
      ref_state_delta: compactRefState(refStateDelta),
      results
    };
  }

  async ingestArtifacts(request: IngestArtifactsRequest): Promise<IngestArtifactsResponse> {
    const ingestRunId = request.ingest_run_id ?? randomUUID();
    const errors: IngestErrorItem[] = [];
    const results: IngestArtifactResult[] = [];
    const refStateInput = normalizeRefState(request.ref_state);
    const refStateDelta: IngestRefState = {
      artifact_ref_to_id: {},
      artifact_ref_to_version_id: {}
    };

    let accepted = 0;
    let rejected = 0;
    for (const [index, item] of request.items.entries()) {
      try {
        let artifactId: string;
        const versionIds: string[] = [];
        if (request.dry_run) {
          artifactId = randomUUID();
          for (const _version of item.versions) {
            versionIds.push(randomUUID());
          }
        } else {
          const artifact = await this.artifactService.createArtifact({
            artifact_type: item.artifact.artifact_type,
            name: item.artifact.name,
            description: item.artifact.description
          });

          artifactId = artifact.artifact_id;
          for (const [versionIndex, version] of item.versions.entries()) {
            const created = await this.artifactService.createArtifactVersion({
              artifact_id: artifactId,
              version_number: version.version_number,
              status: version.status,
              valid_from: version.valid_from,
              valid_to: version.valid_to,
              system_from: version.system_from,
              content_ref: version.content_ref,
              content_hash: version.content_hash,
              author_id: resolveOptionalEntityRefId(
                version.author_id,
                version.author_ref,
                refStateInput,
                `items[${index}].versions[${versionIndex}].author`
              ),
              approver_id: resolveOptionalEntityRefId(
                version.approver_id,
                version.approver_ref,
                refStateInput,
                `items[${index}].versions[${versionIndex}].approver`
              )
            });
            versionIds.push(created.artifact_version_id);
          }
        }

        const artifactRef = item.artifact_ref;
        if (artifactRef) {
          refStateDelta.artifact_ref_to_id![artifactRef] = artifactId;
          if (versionIds.length > 0) {
            refStateDelta.artifact_ref_to_version_id![artifactRef] = versionIds[versionIds.length - 1];
          }
        }

        results.push({
          index,
          artifact_ref: artifactRef,
          artifact_id: artifactId,
          artifact_version_ids: versionIds
        });
        accepted += 1;
      } catch (error) {
        rejected += 1;
        errors.push(toIngestError(index, error));
      }
    }

    return {
      ingest_run_id: ingestRunId,
      stream_id: request.stream_id,
      accepted,
      rejected,
      errors,
      ref_state_delta: compactRefState(refStateDelta),
      results
    };
  }

  async ingestEvents(request: IngestEventsRequest): Promise<IngestEventsResponse> {
    const ingestRunId = request.ingest_run_id ?? randomUUID();
    const errors: IngestErrorItem[] = [];
    const results: IngestEventResult[] = [];
    const eventIds: string[] = [];

    const refStateInput = normalizeRefState(request.ref_state);
    const refStateDelta: IngestRefState = {
      event_ref_to_id: {}
    };

    let accepted = 0;
    let rejected = 0;
    for (const [index, item] of request.items.entries()) {
      try {
        const eventType = item.event_type ?? 'fact_observed';
        if (!EVENT_TYPE_SET.has(eventType)) {
          throw new Error(`unsupported event_type: ${eventType}`);
        }

        const payload: Record<string, unknown> = item.payload ? { ...item.payload } : {};
        if (item.event_text && typeof payload.text !== 'string') {
          payload.text = item.event_text;
        }
        const caseId = resolveOptionalCaseId(
          item.case_id,
          item.case_ref,
          request.stream_id,
          `items[${index}].case`
        );

        const eventId = request.dry_run
          ? randomUUID()
          : (
              await this.eventService.appendEvent({
                case_id: caseId,
                stream_id: request.stream_id,
                event_type: eventType as (typeof EVENT_TYPES)[number],
                actor_id: resolveOptionalObjectRefId(
                  item.actor_id,
                  item.actor_ref,
                  refStateInput,
                  `items[${index}].actor`
                ),
                subject_id: resolveOptionalObjectRefId(
                  item.subject_id,
                  item.subject_ref,
                  refStateInput,
                  `items[${index}].subject`
                ),
                object_id: resolveOptionalObjectRefId(
                  item.object_id,
                  item.object_ref,
                  refStateInput,
                  `items[${index}].object`
                ),
                payload,
                event_text: item.event_text,
                embedding: item.embedding,
                embedding_model: item.embedding_model,
                valid_time: item.valid_time ?? new Date().toISOString(),
                system_time: item.system_time
              })
            ).event_id;

        const eventRef = item.event_ref;
        if (eventRef) {
          refStateInput.event_ref_to_id[eventRef] = eventId;
          refStateDelta.event_ref_to_id![eventRef] = eventId;
        }

        results.push({
          index,
          event_ref: eventRef,
          event_id: eventId
        });
        eventIds.push(eventId);
        accepted += 1;
      } catch (error) {
        rejected += 1;
        errors.push(toIngestError(index, error));
      }
    }

    return {
      ingest_run_id: ingestRunId,
      stream_id: request.stream_id,
      accepted,
      rejected,
      errors,
      ref_state_delta: compactRefState(refStateDelta),
      event_ids: eventIds,
      results
    };
  }

  async ingestText(request: IngestTextRequest): Promise<IngestEventsResponse> {
    const normalizedEvents: IngestEventsRequest = {
      ingest_run_id: request.ingest_run_id,
      stream_id: request.stream_id,
      dry_run: request.dry_run,
      items: request.items.map((item, index) => {
        const payload: Record<string, unknown> = item.payload ? { ...item.payload } : {};
        if (typeof payload.text !== 'string') {
          payload.text = item.text;
        }
        const embedding = item.embedding;
        return {
          event_ref: item.event_ref,
          payload,
          event_text: item.text,
          event_type: request.event_type ?? 'fact_observed',
          embedding,
          embedding_model: embedding ? request.embedding_model : undefined,
          valid_time: request.valid_time,
          system_time: request.system_time
        };
      })
    };

    return this.ingestEvents(normalizedEvents);
  }

  async ingestBundle(request: IngestBundleRequest): Promise<IngestBundleResponse> {
    const ingestRunId = request.ingest_run_id ?? randomUUID();
    const refState = normalizeRefState(undefined);

    const entities = request.entities?.length
      ? await this.ingestEntities({
          ingest_run_id: ingestRunId,
          stream_id: request.stream_id,
          dry_run: request.dry_run,
          items: request.entities
        } as IngestEntitiesRequest)
      : emptyEntitiesResponse(ingestRunId, request.stream_id);
    mergeRefState(refState, entities.ref_state_delta);

    const artifacts = request.artifacts?.length
      ? await this.ingestArtifacts({
          ingest_run_id: ingestRunId,
          stream_id: request.stream_id,
          dry_run: request.dry_run,
          ref_state: refState,
          items: request.artifacts
        } as IngestArtifactsRequest)
      : emptyArtifactsResponse(ingestRunId, request.stream_id);
    mergeRefState(refState, artifacts.ref_state_delta);

    const events = request.events?.length
      ? await this.ingestEvents({
          ingest_run_id: ingestRunId,
          stream_id: request.stream_id,
          dry_run: request.dry_run,
          ref_state: refState,
          items: request.events.map((item) => ({
            ...item,
            event_type: item.event_type ?? request.defaults?.event_type,
            valid_time: item.valid_time ?? request.defaults?.valid_time,
            system_time: item.system_time ?? request.defaults?.system_time
          }))
        } as IngestEventsRequest)
      : emptyEventsResponse(ingestRunId, request.stream_id);
    mergeRefState(refState, events.ref_state_delta);

    const properties = request.properties?.length
      ? await this.ingestProperty({
          ingest_run_id: ingestRunId,
          stream_id: request.stream_id,
          dry_run: request.dry_run,
          ref_state: refState,
          items: request.properties.map((item) => ({
            ...item,
            valid_from: requireBundleTimestamp(
              item.valid_from ?? request.defaults?.valid_time,
              'properties[].valid_from'
            ),
            system_from: item.system_from ?? request.defaults?.system_time
          }))
        } as IngestPropertyRequest)
      : emptyPropertyResponse(ingestRunId, request.stream_id);

    const edges = request.edges?.length
      ? await this.ingestEdge({
          ingest_run_id: ingestRunId,
          stream_id: request.stream_id,
          dry_run: request.dry_run,
          ref_state: refState,
          items: request.edges.map((item) => ({
            ...item,
            valid_from: requireBundleTimestamp(
              item.valid_from ?? request.defaults?.valid_time,
              'edges[].valid_from'
            ),
            system_from: item.system_from ?? request.defaults?.system_time
          }))
        } as IngestEdgeRequest)
      : emptyEdgeResponse(ingestRunId, request.stream_id);

    const accepted =
      entities.accepted + artifacts.accepted + events.accepted + properties.accepted + edges.accepted;
    const rejected =
      entities.rejected + artifacts.rejected + events.rejected + properties.rejected + edges.rejected;
    const errors =
      entities.errors.length +
      artifacts.errors.length +
      events.errors.length +
      properties.errors.length +
      edges.errors.length;

    return {
      ingest_run_id: ingestRunId,
      stream_id: request.stream_id,
      ref_state: compactRefState(refState),
      totals: {
        accepted,
        rejected,
        errors
      },
      phases: {
        entities,
        artifacts,
        events,
        properties,
        edges
      }
    };
  }

  async ingestProperty(request: IngestPropertyRequest): Promise<IngestPropertyResponse> {
    const ingestRunId = request.ingest_run_id ?? randomUUID();
    const errors: IngestErrorItem[] = [];
    const results: IngestPropertyResult[] = [];
    const refStateInput = normalizeRefState(request.ref_state);

    let accepted = 0;
    let rejected = 0;
    for (const [index, item] of request.items.entries()) {
      try {
        const propertyStateId = request.dry_run
          ? randomUUID()
          : (
              await this.stateService.upsertProperty({
                object_id: resolveRequiredObjectRefId(
                  item.object_id,
                  item.object_ref,
                  refStateInput,
                  `items[${index}].object`
                ),
                key: item.key,
                value: item.value,
                valid_from: item.valid_from,
                system_from: item.system_from,
                source_event_id: resolveOptionalEventRefId(
                  item.source_event_id,
                  item.source_event_ref,
                  refStateInput,
                  `items[${index}].source_event`
                ),
                confidence: item.confidence
              })
            ).property_state_id;
        results.push({ index, property_state_id: propertyStateId });
        accepted += 1;
      } catch (error) {
        rejected += 1;
        errors.push(toIngestError(index, error));
      }
    }

    return {
      ingest_run_id: ingestRunId,
      stream_id: request.stream_id,
      accepted,
      rejected,
      errors,
      ref_state_delta: {},
      results
    };
  }

  async ingestEdge(request: IngestEdgeRequest): Promise<IngestEdgeResponse> {
    const ingestRunId = request.ingest_run_id ?? randomUUID();
    const errors: IngestErrorItem[] = [];
    const results: IngestEdgeResult[] = [];
    const refStateInput = normalizeRefState(request.ref_state);

    let accepted = 0;
    let rejected = 0;
    for (const [index, item] of request.items.entries()) {
      try {
        const edgeStateId = request.dry_run
          ? randomUUID()
          : (
              await this.stateService.upsertEdge({
                src_id: resolveRequiredObjectRefId(
                  item.src_id,
                  item.src_ref,
                  refStateInput,
                  `items[${index}].src`
                ),
                predicate: item.predicate,
                dst_id: resolveRequiredObjectRefId(
                  item.dst_id,
                  item.dst_ref,
                  refStateInput,
                  `items[${index}].dst`
                ),
                valid_from: item.valid_from,
                system_from: item.system_from,
                source_event_id: resolveOptionalEventRefId(
                  item.source_event_id,
                  item.source_event_ref,
                  refStateInput,
                  `items[${index}].source_event`
                ),
                confidence: item.confidence
              })
            ).edge_state_id;
        results.push({ index, edge_state_id: edgeStateId });
        accepted += 1;
      } catch (error) {
        rejected += 1;
        errors.push(toIngestError(index, error));
      }
    }

    return {
      ingest_run_id: ingestRunId,
      stream_id: request.stream_id,
      accepted,
      rejected,
      errors,
      ref_state_delta: {},
      results
    };
  }

}

function normalizeRefState(input: IngestRefState | undefined): {
  entity_ref_to_id: Record<string, string>;
  artifact_ref_to_id: Record<string, string>;
  artifact_ref_to_version_id: Record<string, string>;
  event_ref_to_id: Record<string, string>;
} {
  return {
    entity_ref_to_id: { ...(input?.entity_ref_to_id ?? {}) },
    artifact_ref_to_id: { ...(input?.artifact_ref_to_id ?? {}) },
    artifact_ref_to_version_id: { ...(input?.artifact_ref_to_version_id ?? {}) },
    event_ref_to_id: { ...(input?.event_ref_to_id ?? {}) }
  };
}

function compactRefState(state: IngestRefState): IngestRefState {
  const result: IngestRefState = {};
  if (state.entity_ref_to_id && Object.keys(state.entity_ref_to_id).length > 0) {
    result.entity_ref_to_id = state.entity_ref_to_id;
  }
  if (state.artifact_ref_to_id && Object.keys(state.artifact_ref_to_id).length > 0) {
    result.artifact_ref_to_id = state.artifact_ref_to_id;
  }
  if (state.artifact_ref_to_version_id && Object.keys(state.artifact_ref_to_version_id).length > 0) {
    result.artifact_ref_to_version_id = state.artifact_ref_to_version_id;
  }
  if (state.event_ref_to_id && Object.keys(state.event_ref_to_id).length > 0) {
    result.event_ref_to_id = state.event_ref_to_id;
  }
  return result;
}

function mergeRefState(
  target: ReturnType<typeof normalizeRefState>,
  delta: IngestRefState
): void {
  Object.assign(target.entity_ref_to_id, delta.entity_ref_to_id ?? {});
  Object.assign(target.artifact_ref_to_id, delta.artifact_ref_to_id ?? {});
  Object.assign(target.artifact_ref_to_version_id, delta.artifact_ref_to_version_id ?? {});
  Object.assign(target.event_ref_to_id, delta.event_ref_to_id ?? {});
}

function emptyResponseBase(ingestRunId: string, streamId: string): IngestResponseBase {
  return {
    ingest_run_id: ingestRunId,
    stream_id: streamId,
    accepted: 0,
    rejected: 0,
    errors: [],
    ref_state_delta: {}
  };
}

function emptyEntitiesResponse(ingestRunId: string, streamId: string): IngestEntitiesResponse {
  return {
    ...emptyResponseBase(ingestRunId, streamId),
    results: []
  };
}

function emptyArtifactsResponse(ingestRunId: string, streamId: string): IngestArtifactsResponse {
  return {
    ...emptyResponseBase(ingestRunId, streamId),
    results: []
  };
}

function emptyEventsResponse(ingestRunId: string, streamId: string): IngestEventsResponse {
  return {
    ...emptyResponseBase(ingestRunId, streamId),
    event_ids: [],
    results: []
  };
}

function emptyPropertyResponse(ingestRunId: string, streamId: string): IngestPropertyResponse {
  return {
    ...emptyResponseBase(ingestRunId, streamId),
    results: []
  };
}

function emptyEdgeResponse(ingestRunId: string, streamId: string): IngestEdgeResponse {
  return {
    ...emptyResponseBase(ingestRunId, streamId),
    results: []
  };
}

function resolveRequiredObjectRefId(
  directId: string | undefined,
  ref: string | undefined,
  state: ReturnType<typeof normalizeRefState>,
  fieldLabel: string
): string {
  const resolved = resolveOptionalObjectRefId(directId, ref, state, fieldLabel);
  if (!resolved) {
    throw new Error(`${fieldLabel} requires an id or ref`);
  }
  return resolved;
}

function resolveOptionalObjectRefId(
  directId: string | undefined,
  ref: string | undefined,
  state: ReturnType<typeof normalizeRefState>,
  fieldLabel: string
): string | undefined {
  return resolveOptionalRefId(directId, ref, fieldLabel, () => lookupObjectRef(ref, state));
}

function resolveOptionalEntityRefId(
  directId: string | undefined,
  ref: string | undefined,
  state: ReturnType<typeof normalizeRefState>,
  fieldLabel: string
): string | undefined {
  return resolveOptionalRefId(directId, ref, fieldLabel, () =>
    lookupNamedRef(ref, state.entity_ref_to_id, fieldLabel)
  );
}

function resolveOptionalEventRefId(
  directId: string | undefined,
  ref: string | undefined,
  state: ReturnType<typeof normalizeRefState>,
  fieldLabel: string
): string | undefined {
  return resolveOptionalRefId(directId, ref, fieldLabel, () =>
    lookupNamedRef(ref, state.event_ref_to_id, fieldLabel)
  );
}

function resolveOptionalRefId(
  directId: string | undefined,
  ref: string | undefined,
  fieldLabel: string,
  resolver: () => string
): string | undefined {
  if (!directId && !ref) {
    return undefined;
  }
  if (directId && !ref) {
    return directId;
  }

  const resolved = resolver();
  if (directId && directId !== resolved) {
    throw new Error(`${fieldLabel} id/ref mismatch`);
  }
  return directId ?? resolved;
}

function lookupObjectRef(ref: string | undefined, state: ReturnType<typeof normalizeRefState>): string {
  if (!ref) {
    throw new Error('object ref is required');
  }

  const matches = [
    state.entity_ref_to_id[ref],
    state.artifact_ref_to_id[ref],
    state.event_ref_to_id[ref]
  ].filter((value): value is string => Boolean(value));

  if (matches.length === 0) {
    throw new Error(`unknown ref: ${ref}`);
  }

  const distinct = [...new Set(matches)];
  if (distinct.length > 1) {
    throw new Error(`ambiguous ref: ${ref}`);
  }
  return distinct[0];
}

function lookupNamedRef(
  ref: string | undefined,
  mapping: Record<string, string>,
  fieldLabel: string
): string {
  if (!ref) {
    throw new Error(`${fieldLabel} ref is required`);
  }
  const resolved = mapping[ref];
  if (!resolved) {
    throw new Error(`unknown ref for ${fieldLabel}: ${ref}`);
  }
  return resolved;
}

function resolveOptionalCaseId(
  caseId: string | undefined,
  caseRef: string | undefined,
  streamId: string,
  fieldLabel: string
): string | undefined {
  if (!caseId && !caseRef) {
    return undefined;
  }
  if (!caseRef) {
    return caseId;
  }

  const resolved = deterministicUuid(`case_ref:${streamId}:${caseRef}`);
  if (caseId && caseId !== resolved) {
    throw new Error(`${fieldLabel} id/ref mismatch`);
  }
  return caseId ?? resolved;
}

function deterministicUuid(seed: string): string {
  const hex = createHash('md5').update(seed).digest('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-3${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

function requireBundleTimestamp(value: string | undefined, fieldLabel: string): string {
  if (!value) {
    throw new Error(`${fieldLabel} is required when bundle.defaults does not provide it`);
  }
  return value;
}

function toIngestError(index: number, error: unknown): IngestErrorItem {
  if (error instanceof Error) {
    return {
      index,
      code: 'INGEST_ITEM_FAILED',
      message: error.message
    };
  }
  return {
    index,
    code: 'INGEST_ITEM_FAILED',
    message: String(error)
  };
}

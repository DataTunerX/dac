import { randomUUID } from 'node:crypto';
import type { Static } from '@sinclair/typebox';
import type { GatewayBackendClient, EntityRecord } from '../clients/gateway_backend.types.js';

import { TdbError } from '../errors/tdb_error.js';
import {
  MemoryGetEntityStateRequestSchema,
  MemoryGetEntityStateResponseSchema,
  MemoryGetRelationsRequestSchema,
  MemoryGetRelationsResponseSchema,
  MemoryRecallAnswerArtifactsRequestSchema,
  MemoryRecallAnswerArtifactsResponseSchema,
  MemoryGetTaskContextRequestSchema,
  MemoryGetTaskContextResponseSchema,
  MemoryRecordAnswerArtifactRequestSchema,
  MemoryRecordAnswerArtifactResponseSchema,
  MemoryRecordAnswerValidationRequestSchema,
  MemoryRecordAnswerValidationResponseSchema,
  MemoryRecordEpisodeSummaryRequestSchema,
  MemoryRecordEpisodeSummaryResponseSchema,
  MemoryRecordDecisionRequestSchema,
  MemoryRecordDecisionResponseSchema,
  MemoryRecordRelationRequestSchema,
  MemoryRecordRelationResponseSchema,
  MemoryUpsertEntityStateRequestSchema,
  MemoryUpsertEntityStateResponseSchema,
} from '../schema/v2/memory.js';

export type MemoryRecordDecisionRequest = Static<typeof MemoryRecordDecisionRequestSchema>;
export type MemoryRecordDecisionResponse = Static<typeof MemoryRecordDecisionResponseSchema>;
export type MemoryGetEntityStateRequest = Static<typeof MemoryGetEntityStateRequestSchema>;
export type MemoryGetEntityStateResponse = Static<typeof MemoryGetEntityStateResponseSchema>;
export type MemoryGetRelationsRequest = Static<typeof MemoryGetRelationsRequestSchema>;
export type MemoryGetRelationsResponse = Static<typeof MemoryGetRelationsResponseSchema>;
export type MemoryRecallAnswerArtifactsRequest = Static<typeof MemoryRecallAnswerArtifactsRequestSchema>;
export type MemoryRecallAnswerArtifactsResponse = Static<typeof MemoryRecallAnswerArtifactsResponseSchema>;
export type MemoryGetTaskContextRequest = Static<typeof MemoryGetTaskContextRequestSchema>;
export type MemoryGetTaskContextResponse = Static<typeof MemoryGetTaskContextResponseSchema>;
export type MemoryRecordAnswerArtifactRequest = Static<typeof MemoryRecordAnswerArtifactRequestSchema>;
export type MemoryRecordAnswerArtifactResponse = Static<typeof MemoryRecordAnswerArtifactResponseSchema>;
export type MemoryRecordAnswerValidationRequest = Static<typeof MemoryRecordAnswerValidationRequestSchema>;
export type MemoryRecordAnswerValidationResponse = Static<typeof MemoryRecordAnswerValidationResponseSchema>;
export type MemoryRecordEpisodeSummaryRequest = Static<typeof MemoryRecordEpisodeSummaryRequestSchema>;
export type MemoryRecordEpisodeSummaryResponse = Static<typeof MemoryRecordEpisodeSummaryResponseSchema>;
export type MemoryUpsertEntityStateRequest = Static<typeof MemoryUpsertEntityStateRequestSchema>;
export type MemoryUpsertEntityStateResponse = Static<typeof MemoryUpsertEntityStateResponseSchema>;
export type MemoryRecordRelationRequest = Static<typeof MemoryRecordRelationRequestSchema>;
export type MemoryRecordRelationResponse = Static<typeof MemoryRecordRelationResponseSchema>;
type StateFieldDto = MemoryGetEntityStateResponse['durable_state'][string];
type EvidenceRefDto = MemoryGetEntityStateResponse['supporting_evidence'][number];
const NIL_UUID = '00000000-0000-0000-0000-000000000000';

function effectiveTopicId(request: { topic_id?: string }): string {
  return request.topic_id?.trim() || '';
}

export class MemoryService {
  constructor(private readonly gatewayBackend: GatewayBackendClient) {}

  async recordDecision(request: MemoryRecordDecisionRequest): Promise<MemoryRecordDecisionResponse> {
    const topicId = effectiveTopicId(request);
    if (!topicId) {
      throw new TdbError('INVALID_ARGUMENT', 400, 'topic_id is required.');
    }

    const res = await this.gatewayBackend.insertMemoryDecision({
      task_id: topicId,
      run_id: request.run_id,
      decision_text: request.decision,
      rationale_text: request.rationale,
      alternatives_considered: request.alternatives_considered ?? [],
      source_evidence_json: JSON.stringify(request.source_evidence ?? []),
      entity_ids: request.entity_ids ?? [],
      confidence: request.confidence ?? 0.99,
      author_json: JSON.stringify(request.author ?? {}),
      decision_timestamp: request.timestamp,
      consequences: request.consequences ?? [],
      metadata_json: JSON.stringify(request.metadata ?? {}),
      idempotency_key: request.idempotency_key
    });

    return {
      decision_id: res.memory_decision_id,
      status: 'recorded' as const,
      stored_at: res.created_at,
      topic_id: res.task_id,
      run_id: res.run_id,
      deduplicated: false,
      provenance_summary: {
        evidence_count: request.source_evidence.length,
        entity_count: request.entity_ids?.length ?? 0
      }
    };
  }

  async recordEpisodeSummary(
    request: MemoryRecordEpisodeSummaryRequest,
  ): Promise<MemoryRecordEpisodeSummaryResponse> {
    const topicId = effectiveTopicId(request);
    if (!topicId) {
      throw new TdbError('INVALID_ARGUMENT', 400, 'topic_id is required.');
    }

    const res = await this.gatewayBackend.insertMemoryEpisodeSummary({
      task_id: topicId,
      run_id: request.run_id,
      session_id: request.session_id,
      episode_label: request.episode_label,
      summary_text: request.summary,
      outcomes: request.outcomes ?? [],
      key_facts_json: JSON.stringify(request.key_facts ?? []),
      decisions: request.decisions ?? [],
      unresolved_questions: request.unresolved_questions ?? [],
      source_evidence_json: JSON.stringify(request.source_evidence ?? []),
      entity_ids: request.entity_ids ?? [],
      confidence: request.confidence ?? 0.99,
      author_json: JSON.stringify(request.author ?? {}),
      summary_timestamp: request.timestamp,
      metadata_json: JSON.stringify(request.metadata ?? {}),
      idempotency_key: request.idempotency_key
    });

    return {
      episode_summary_id: res.episode_summary_id,
      status: 'recorded' as const,
      stored_at: res.created_at,
      topic_id: topicId,
      run_id: res.run_id,
      deduplicated: false,
      provenance_summary: {
        evidence_count: request.source_evidence.length,
        entity_count: request.entity_ids?.length ?? 0
      }
    };
  }

  async recordAnswerArtifact(
    request: MemoryRecordAnswerArtifactRequest,
  ): Promise<MemoryRecordAnswerArtifactResponse> {
    const res = await this.gatewayBackend.insertMemoryAnswerArtifact({
      domain_id: request.domain_id,
      intent: request.intent,
      normalized_question: request.normalized_question,
      question_fingerprint_json: JSON.stringify(request.question_fingerprint ?? {}),
      entity_ids: request.entity_ids ?? [],
      answer_text: request.answer_text,
      answer_payload_json: JSON.stringify(request.answer_payload ?? {}),
      source_task_id: request.source_task_id,
      source_run_id: request.source_run_id,
      source_decision_id: request.source_decision_id,
      source_episode_summary_id: request.source_episode_summary_id,
      evidence_refs_json: JSON.stringify(request.evidence_refs ?? []),
      provenance_json: JSON.stringify(request.provenance ?? {}),
      freshness_policy_json: JSON.stringify(request.freshness_policy ?? {}),
      validation_contract_json: JSON.stringify(request.validation_contract ?? {}),
      metadata_json: JSON.stringify(request.metadata ?? {}),
      serving_status: request.serving_status,
      superseded_by: request.superseded_by,
      idempotency_key: request.idempotency_key,
    });

    return {
      answer_artifact_id: res.answer_artifact_id,
      status: 'recorded',
      stored_at: res.created_at,
    };
  }

  async recallAnswerArtifacts(
    request: MemoryRecallAnswerArtifactsRequest,
  ): Promise<MemoryRecallAnswerArtifactsResponse> {
    const rows = await this.gatewayBackend.recallMemoryAnswerArtifacts({
      domain_id: request.domain_id,
      intent: request.intent,
      question_fingerprint_json: JSON.stringify(request.question_fingerprint ?? {}),
      entity_ids: request.entity_ids ?? [],
      serving_statuses: request.serving_statuses ?? [],
      limit: request.limit ?? 5,
    });

    return {
      candidates: rows.map((row) => ({
        answer_artifact_id: row.answer_artifact_id,
        domain_id: row.domain_id,
        intent: row.intent,
        normalized_question: row.normalized_question,
        question_fingerprint: parseJsonObject(row.question_fingerprint_json),
        entity_ids: row.entity_ids ?? [],
        answer_text: row.answer_text,
        answer_payload: parseJsonObject(row.answer_payload_json),
        source_task_id: optionalString(row.source_task_id),
        source_run_id: optionalString(row.source_run_id),
        source_decision_id: optionalString(row.source_decision_id),
        source_episode_summary_id: optionalString(row.source_episode_summary_id),
        evidence_refs: parseJsonArray(row.evidence_refs_json),
        provenance: parseJsonObject(row.provenance_json),
        freshness_policy: parseJsonObject(row.freshness_policy_json),
        validation_contract: parseJsonObject(row.validation_contract_json),
        metadata: parseJsonObject(row.metadata_json),
        serving_status: row.serving_status,
        superseded_by: optionalString(row.superseded_by),
        created_at: row.created_at,
        updated_at: row.updated_at,
      })),
    };
  }

  async recordAnswerValidation(
    request: MemoryRecordAnswerValidationRequest,
  ): Promise<MemoryRecordAnswerValidationResponse> {
    const res = await this.gatewayBackend.insertMemoryAnswerValidation({
      answer_artifact_id: request.answer_artifact_id,
      validator_type: request.validator_type,
      check_spec_json: JSON.stringify(request.check_spec ?? {}),
      observed_values_json: JSON.stringify(request.observed_values ?? {}),
      pass: request.pass,
      failure_reason: request.failure_reason,
      latency_ms: request.latency_ms,
      metadata_json: JSON.stringify(request.metadata ?? {}),
      validated_at: request.validated_at,
    });

    return {
      answer_validation_id: res.answer_validation_id,
      answer_artifact_id: res.answer_artifact_id,
      status: 'recorded',
      stored_at: res.validated_at,
    };
  }

  async upsertEntityState(
    request: MemoryUpsertEntityStateRequest,
  ): Promise<MemoryUpsertEntityStateResponse> {
    if (request.entity_id === NIL_UUID) {
      throw new TdbError('INVALID_ARGUMENT', 400, 'The nil UUID is not allowed as entity_id.');
    }
    if (!request.entity_id && !request.entity_ref) {
      throw new TdbError('INVALID_ARGUMENT', 400, 'Either entity_id or entity_ref must be provided.');
    }

    let existingId = request.entity_id;
    let existing: any;

    if (existingId) {
      try {
        existing = await this.gatewayBackend.getEntity({ entity_id: existingId });
      } catch (error) {
        if (!request.entity_ref) {
          throw error;
        }
      }
    } else if (request.entity_ref) {
      const entities = await this.gatewayBackend.listEntities({
        entity_type: request.entity_ref.type,
        query: request.entity_ref.name
      });
      if (entities.length > 1) {
        throw new TdbError('AMBIGUOUS_ENTITY', 400, 'Multiple entities matched.', {
          candidates: entities.map(e => ({ entity_id: e.entity_id, display_name: e.display_name }))
        });
      }
      existing = entities[0];
      existingId = existing?.entity_id;
    }

    const entityType = existing?.entity_type ?? request.entity_ref?.type;
    const displayName = request.display_name?.trim() || existing?.display_name || request.entity_ref?.name?.trim();

    const mergedExternalRefs = {
      ...(existing?.external_refs ?? {}),
      ...request.durable_state
    };

    const row = await this.gatewayBackend.upsertEntity({
      entity_id: existingId || randomUUID(),
      entity_type: entityType || '',
      display_name: displayName || '',
      external_refs_json: JSON.stringify(mergedExternalRefs),
      status: request.status ?? existing?.status ?? 'active'
    });

    const finalRefs = JSON.parse(row.external_refs_json || '{}');
    return {
      entity_id: row.entity_id,
      canonical_ref: finalRefs.canonical_ref || `${row.entity_type}:${slugify(row.display_name)}`,
      status: existing ? 'updated' : 'created',
      stored_at: row.updated_at
    };
  }

  async getEntityState(request: MemoryGetEntityStateRequest): Promise<MemoryGetEntityStateResponse> {
    const entity = await this.resolveEntity(request);
    const canonicalRef = canonicalEntityRef(entity);
    const decisions = await this.gatewayBackend.listRecentMemoryDecisions({
      task_id: '', // Not filtering by task
      entity_ids: [canonicalRef, entity.entity_id],
      as_of: request.as_of,
      limit: request.max_supporting_evidence ?? 5
    });

    const inferredFromMetadata = decisions
      .map(d => JSON.parse(d.metadata_json || '{}').inferred_state)
      .filter(v => !!v && typeof v === 'object');

    const inferredState = mergeStateMaps(inferredFromMetadata);
    const supportingEvidence = dedupeEvidence(
      decisions.flatMap(d => JSON.parse(d.source_evidence_json || '[]')).slice(0, request.max_supporting_evidence ?? 5)
    );

    const latestTimestamp = decisions[0]?.decision_timestamp ?? (entity as any).updated_at;
    const asOf = request.as_of ?? new Date().toISOString();

    return {
      entity: {
        entity_id: entity.entity_id,
        canonical_ref: canonicalRef,
        resolved_from: request.entity_ref,
        entity_type: entity.entity_type,
        display_name: entity.display_name,
      },
      durable_state: buildDurableState(entity, request.field_filter ?? []),
      last_observed_state: {},
      inferred_state: inferredState,
      freshness: {
        as_of: asOf,
        staleness_seconds: stalenessSeconds(latestTimestamp, asOf),
      },
      conflicts: [],
      supporting_evidence: supportingEvidence,
    };
  }

  async recordRelation(request: MemoryRecordRelationRequest): Promise<MemoryRecordRelationResponse> {
    const source = await this.resolveRelationEntity(request.source_entity_id, request.source_entity_ref);
    const target = await this.resolveRelationEntity(request.target_entity_id, request.target_entity_ref);

    const row = await this.gatewayBackend.upsertEdge({
      src_id: source.entity_id,
      predicate: request.predicate.trim(),
      dst_id: target.entity_id,
      valid_from: request.valid_from,
      system_from: request.system_from,
      source_event_id: request.source_event_id,
      confidence: request.confidence,
    });

    return mapEdgeRow(row);
  }

  async getRelations(request: MemoryGetRelationsRequest): Promise<MemoryGetRelationsResponse> {
    const source = await this.resolveRelationEntity(request.source_entity_id, request.source_entity_ref);
    const rows = await this.gatewayBackend.getEdgesAsOf({
      src_id: source.entity_id,
      predicate: request.predicate?.trim(),
      as_of_valid_time: request.as_of_valid_time,
      as_of_system_time: request.as_of_system_time,
    });

    return {
      relations: rows.map((row) => mapEdgeRow(row)),
    };
  }

  private async resolveEntity(request: MemoryGetEntityStateRequest): Promise<any> {
    if (request.entity_id === NIL_UUID) {
      throw new TdbError('INVALID_ARGUMENT', 400, 'The nil UUID is not allowed as entity_id.');
    }
    if (request.entity_id) {
      const entity = await this.gatewayBackend.getEntity({ entity_id: request.entity_id });
      if (!entity) {
        throw new TdbError('NOT_FOUND', 404, 'No entity found.');
      }
      return entity;
    }

    if (!request.entity_ref) {
      throw new TdbError('INVALID_ARGUMENT', 400, 'Either entity_id or entity_ref must be provided.');
    }

    const entities = await this.gatewayBackend.listEntities({
      entity_type: request.entity_ref.type,
      query: request.entity_ref.name
    });

    if (entities.length === 0) {
      throw new TdbError('NOT_FOUND', 404, 'No entity could be resolved.');
    }
    if (entities.length > 1) {
      throw new TdbError('AMBIGUOUS_ENTITY', 400, 'Multiple entities matched.', {
        candidates: entities.map(e => ({ entity_id: e.entity_id, display_name: e.display_name }))
      });
    }
    return entities[0];
  }

  private async resolveRelationEntity(
    entityId: string | undefined,
    entityRef: { type: string; name: string } | undefined,
  ): Promise<EntityRecord> {
    if (entityId === NIL_UUID) {
      throw new TdbError('INVALID_ARGUMENT', 400, 'The nil UUID is not allowed as entity_id.');
    }
    if (entityId) {
      const entity = await this.gatewayBackend.getEntity({ entity_id: entityId });
      if (!entity) {
        throw new TdbError('NOT_FOUND', 404, 'No entity found.');
      }
      return entity;
    }
    if (!entityRef) {
      throw new TdbError('INVALID_ARGUMENT', 400, 'Either entity_id or entity_ref must be provided.');
    }

    const entities = await this.gatewayBackend.listEntities({
      entity_type: entityRef.type,
      query: entityRef.name,
    });

    if (entities.length === 0) {
      throw new TdbError('NOT_FOUND', 404, 'No entity could be resolved.');
    }
    if (entities.length > 1) {
      throw new TdbError('AMBIGUOUS_ENTITY', 400, 'Multiple entities matched.', {
        candidates: entities.map((entity) => ({ entity_id: entity.entity_id, display_name: entity.display_name })),
      });
    }
    return entities[0];
  }

  async getTaskContext(request: MemoryGetTaskContextRequest): Promise<MemoryGetTaskContextResponse> {
    const topicId = effectiveTopicId(request);
    if (!topicId) {
      throw new TdbError('INVALID_ARGUMENT', 400, 'topic_id is required.');
    }

    const [decisions, episodeSummaries] = await Promise.all([
      this.gatewayBackend.listRecentMemoryDecisions({
        task_id: topicId,
        run_id: request.run_id,
        as_of: request.as_of,
        limit: request.max_items?.decisions ?? 5,
        entity_ids: []
      }),
      this.gatewayBackend.listRecentMemoryEpisodeSummaries({
        task_id: topicId,
        run_id: request.run_id,
        as_of: request.as_of,
        limit: request.max_items?.decisions ?? 5
      })
    ]);

    const latestEvidenceAt = latestTimestamp(
      decisions[0]?.decision_timestamp,
      episodeSummaries[0]?.summary_timestamp,
    );
    const evidenceLimit = request.max_items?.supporting_evidence ?? 8;
    const supportingEvidence = dedupeEvidence(
      [
        ...decisions.flatMap(d => JSON.parse(d.source_evidence_json || '[]')),
        ...episodeSummaries.flatMap(e => JSON.parse(e.source_evidence_json || '[]')),
      ].slice(0, evidenceLimit),
    );

    const entities = await this.buildTopicEntities(decisions, episodeSummaries);

    const facts = episodeSummaries.flatMap(episode => {
      const keyFacts = JSON.parse(episode.key_facts_json || '[]');
      return keyFacts.map((fact: any) => ({
        ...fact,
        episode_summary_id: episode.episode_summary_id,
      }));
    });

    const openQuestions = dedupeOpenQuestions([
      ...episodeSummaries.flatMap(episode => episode.unresolved_questions.map(text => ({ text }))),
      ...(decisions.length === 0 && episodeSummaries.length === 0
        ? [{ text: 'No semantic decisions have been recorded for this task yet.' }]
        : []),
    ]);

    return {
      task: {
        topic_id: topicId,
        run_id: request.run_id,
      },
      facts,
      entities,
      decisions: decisions.map((decision) => ({
        decision_id: decision.memory_decision_id,
        decision: decision.decision_text,
        confidence: decision.confidence,
        timestamp: decision.decision_timestamp,
      })),
      episode_summaries: episodeSummaries.map((episode) => ({
        episode_summary_id: episode.episode_summary_id,
        episode_label: episode.episode_label,
        topic_id: episode.task_id,
        run_id: episode.run_id,
        session_id: episode.session_id,
        summary: episode.summary_text,
        outcomes: episode.outcomes,
        key_facts: JSON.parse(episode.key_facts_json || '[]'),
        decisions: episode.decisions,
        unresolved_questions: episode.unresolved_questions,
        entity_ids: episode.entity_ids,
        confidence: episode.confidence,
        summary_timestamp: episode.summary_timestamp,
        metadata: JSON.parse(episode.metadata_json || '{}'),
      })),
      open_questions: openQuestions,
      supporting_evidence: supportingEvidence,
      freshness: {
        as_of: request.as_of ?? new Date().toISOString(),
        latest_evidence_at: latestEvidenceAt,
      },
    };
  }

  private async buildTopicEntities(
    decisions: any[],
    episodeSummaries: any[],
  ): Promise<MemoryGetTaskContextResponse['entities']> {
    const seen = new Set<string>();
    const entityIds = [
      ...decisions.flatMap(d => d.entity_ids),
      ...episodeSummaries.flatMap(e => e.entity_ids),
    ].filter(id => {
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    });

    const results: MemoryGetTaskContextResponse['entities'] = [];
    for (const entityId of entityIds) {
      let row: any;
      try {
        row = await this.resolveTopicEntity(entityId);
      } catch (e) {
        // Safe to ignore if not found
      }

      const inferredState = mergeStateMaps(
        decisions
          .filter(d => d.entity_ids.includes(entityId))
          .map(d => JSON.parse(d.metadata_json || '{}').inferred_state)
          .filter(v => !!v && typeof v === 'object')
      );

      if (!row) {
        const [entityType, ...rest] = entityId.split(':');
        results.push({
          entity_id: entityId,
          canonical_ref: entityId,
          entity_type: entityType || undefined,
          display_name: rest.length > 0 ? rest.join(':') : undefined,
          inferred_state: inferredState,
        });
        continue;
      }

      results.push({
        entity_id: entityId,
        canonical_ref: canonicalEntityRef(row),
        entity_type: row.entity_type,
        display_name: row.display_name,
        durable_state: buildDurableState(row, []),
        inferred_state: inferredState,
      });
    }
    return results;
  }

  private async resolveTopicEntity(entityId: string): Promise<any> {
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(entityId)) {
      return this.gatewayBackend.getEntity({ entity_id: entityId });
    }
    const [entityType, ...rest] = entityId.split(':');
    if (!entityType || rest.length === 0) return undefined;
    const entities = await this.gatewayBackend.listEntities({
      entity_type: entityType,
      query: rest.join(':'),
    });
    return entities[0];
  }
}

function canonicalEntityRef(entity: any): string {
  const configured = typeof entity.external_refs?.canonical_ref === 'string'
    ? entity.external_refs.canonical_ref
    : undefined;
  if (configured && configured.trim().length > 0) {
    return configured;
  }
  return `${entity.entity_type}:${slugify(entity.display_name)}`;
}

function mapEdgeRow(row: {
  edge_state_id: string;
  src_id: string;
  predicate: string;
  dst_id: string;
  valid_from: string;
  valid_to?: string | null;
  system_from: string;
  system_to?: string | null;
  source_event_id?: string | null;
  confidence?: number | null;
}): MemoryRecordRelationResponse {
  return {
    edge_state_id: row.edge_state_id,
    source_entity_id: row.src_id,
    predicate: row.predicate,
    target_entity_id: row.dst_id,
    valid_from: row.valid_from,
    valid_to: row.valid_to ?? undefined,
    system_from: row.system_from,
    system_to: row.system_to ?? undefined,
    source_event_id: row.source_event_id ?? undefined,
    confidence: row.confidence ?? undefined,
  };
}

function inferCanonicalRef(
  durableState: Record<string, unknown>,
  entityRef: { type: string; name: string } | undefined,
  entityType: string,
  displayName: string,
  existing?: any,
): string {
  if (typeof durableState.canonical_ref === 'string' && durableState.canonical_ref.trim().length > 0) {
    return durableState.canonical_ref.trim();
  }
  if (entityRef) {
    return `${entityRef.type}:${slugify(entityRef.name)}`;
  }
  if (existing) {
    return canonicalEntityRef(existing);
  }
  return `${entityType}:${slugify(displayName)}`;
}

function resolveExistingEntityForUpsert(matches: any[], canonicalRef: string): any | undefined {
  if (matches.length === 0) return undefined;
  const canonicalMatches = matches.filter((row) => canonicalEntityRef(row) === canonicalRef);
  if (canonicalMatches.length > 0) {
    return canonicalMatches[0];
  }
  if (matches.length === 1) {
    return matches[0];
  }
  return undefined;
}

function slugify(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

function buildDurableState(entity: any, fieldFilter: string[]): Record<string, StateFieldDto> {
  const all: Record<string, StateFieldDto> = {
    display_name: { value: entity.display_name, confidence: 0.99 },
    entity_type: { value: entity.entity_type, confidence: 0.99 },
    status: { value: entity.status, confidence: 0.99 },
  };

  const externalRefs = JSON.parse(entity.external_refs_json || '{}');
  for (const [key, value] of Object.entries(externalRefs)) {
    all[key] = { value: value as any, confidence: 0.99 };
  }

  if (fieldFilter.length === 0) {
    return all;
  }

  const filtered: Record<string, StateFieldDto> = {};
  for (const field of fieldFilter) {
    if (all[field]) {
      filtered[field] = all[field];
    }
  }
  return filtered;
}

function mergeStateMaps(maps: Array<Record<string, unknown>>): Record<string, StateFieldDto> {
  const merged: Record<string, StateFieldDto> = {};
  for (const map of maps) {
    for (const [key, value] of Object.entries(map)) {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        merged[key] = value as StateFieldDto;
      } else {
        merged[key] = { value };
      }
    }
  }
  return merged;
}

function dedupeEvidence(items: Array<Record<string, unknown>>): EvidenceRefDto[] {
  const seen = new Set<string>();
  const results: EvidenceRefDto[] = [];
  for (const item of items) {
    const key = JSON.stringify(item);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    results.push(item as EvidenceRefDto);
  }
  return results;
}

function stalenessSeconds(latestTimestamp: string, asOf: string): number {
  const latest = Date.parse(latestTimestamp);
  const current = Date.parse(asOf);
  if (Number.isNaN(latest) || Number.isNaN(current) || current <= latest) {
    return 0;
  }
  return Math.floor((current - latest) / 1000);
}

// helper functions remain but will use any for entity rows

function dedupeOpenQuestions(items: Array<Record<string, unknown>>): Array<Record<string, unknown>> {
  const seen = new Set<string>();
  const results: Array<Record<string, unknown>> = [];
  for (const item of items) {
    const key = JSON.stringify(item);
    if (seen.has(key)) continue;
    seen.add(key);
    results.push(item);
  }
  return results;
}

function latestTimestamp(...values: Array<string | undefined>): string | undefined {
  return values
    .filter((value): value is string => Boolean(value))
    .sort((left, right) => Date.parse(right) - Date.parse(left))[0];
}

function parseJsonObject(value: string | undefined): Record<string, unknown> {
  if (!value) {
    return {};
  }
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function parseJsonArray<T extends Record<string, unknown>>(value: string | undefined): T[] {
  if (!value) {
    return [];
  }
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

function optionalString(value: string | undefined): string | undefined {
  if (!value || value.trim().length === 0) {
    return undefined;
  }
  return value;
}

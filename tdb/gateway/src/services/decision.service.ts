import type { Static } from '@sinclair/typebox';

import type {
  GatewayBackendClient,
  DecisionRecord,
  DecisionEvidenceRecord,
  ArtifactVersionRecord,
  EventItem,
  SnapshotRecord
} from '../clients/gateway_backend.types.js';
import {
  DecisionCreateRequestSchema,
  DecisionEvidenceAttachRequestSchema,
  DecisionExplainQuerySchema,
  DecisionGetQuerySchema,
  DecisionTraceQuerySchema
} from '../schema/v2/decision.js';

export type DecisionCreateRequest = Static<typeof DecisionCreateRequestSchema>;
export type DecisionEvidenceAttachRequest = Static<typeof DecisionEvidenceAttachRequestSchema>;
export type DecisionGetQuery = Static<typeof DecisionGetQuerySchema>;
export type DecisionTraceQuery = Static<typeof DecisionTraceQuerySchema>;
export type DecisionExplainQuery = Static<typeof DecisionExplainQuerySchema>;

export type DecisionDto = {
  decision_id: string;
  case_id: string;
  event_seq: number;
  projection_version: string;
  chosen_action: string;
  candidates: Array<Record<string, unknown>>;
  scores: Record<string, number>;
  constraints_hit: string[];
  detail: Record<string, unknown>;
  created_at: string;
};

export type DecisionEvidenceDto = {
  decision_evidence_id: string;
  decision_id: string;
  artifact_version_id: string;
  citation: Record<string, unknown>;
  created_at: string;
};

export type ArtifactVersionDto = {
  artifact_version_id: string;
  artifact_id: string;
  version_number: number;
  status: string;
  valid_from: string;
  valid_to?: string;
  system_from: string;
  system_to?: string;
  content_ref: string;
  content_hash?: string;
  author_id?: string;
  approver_id?: string;
  created_at: string;
};

export type DecisionTraceDto = {
  decision?: DecisionDto;
  evidence: DecisionEvidenceDto[];
  event?: {
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
  snapshot_anchor?: {
    snapshot_id: string;
    case_id: string;
    event_seq: number;
    projection_version: string;
    state_blob: Record<string, unknown>;
    state_hash?: string;
    created_at: string;
  };
  artifact_versions: ArtifactVersionDto[];
  explanation: {
    status: 'resolved' | 'partial' | 'missing_decision';
    summary: string;
    decision_found: boolean;
    event_found: boolean;
    snapshot_anchor_found: boolean;
    evidence_count: number;
    artifact_version_count: number;
    missing_artifact_version_ids: string[];
    missing_components: string[];
    reasoning_steps: string[];
  };
};

export class DecisionService {
  constructor(private readonly backend: GatewayBackendClient) {}

  async createDecision(request: DecisionCreateRequest): Promise<DecisionDto> {
    const record = await this.backend.upsertDecision({
      case_id: request.case_id,
      event_seq: request.event_seq,
      projection_version: request.projection_version,
      chosen_action: request.chosen_action,
      candidates_json: JSON.stringify(request.candidates ?? []),
      scores_json: JSON.stringify(request.scores ?? {}),
      constraints_hit: request.constraints_hit ?? [],
      detail_json: JSON.stringify(request.detail ?? {})
    });
    return mapDecision(record);
  }

  async attachEvidence(request: DecisionEvidenceAttachRequest): Promise<DecisionEvidenceDto> {
    const record = await this.backend.insertDecisionEvidence({
      decision_id: request.decision_id,
      artifact_version_id: request.artifact_version_id,
      citation_json: JSON.stringify(request.citation ?? {})
    });
    return mapEvidence(record);
  }

  async getDecision(query: DecisionGetQuery): Promise<{ decision?: DecisionDto; evidence: DecisionEvidenceDto[] }> {
    const decision = await this.backend.findDecision({
      case_id: query.case_id,
      event_seq: query.event_seq,
      projection_version: query.projection_version
    });

    if (!decision) {
      return { evidence: [] };
    }

    const evidence = await this.backend.listDecisionEvidence({
      decision_id: decision.decision_id
    });

    return {
      decision: mapDecision(decision),
      evidence: evidence.map(mapEvidence)
    };
  }

  async traceDecision(query: DecisionTraceQuery): Promise<DecisionTraceDto> {
    const base = await this.getDecision(query);
    const [events, snapshot, artifactVersions] = await Promise.all([
      this.backend.getEvents({
        case_id: query.case_id,
        from_seq: query.event_seq,
        to_seq: query.event_seq,
        limit: 1
      }),
      this.backend.getLatestSnapshot({
        case_id: query.case_id,
        projection_version: query.projection_version,
        target_seq: query.event_seq
      }),
      Promise.all(
        base.evidence.map(async (item) => {
          const record = await this.backend.getArtifactVersionById({
            artifact_version_id: item.artifact_version_id
          });
          return record ? mapArtifactVersion(record) : undefined;
        })
      )
    ]);

    const resolvedArtifactVersions = artifactVersions.filter((value): value is ArtifactVersionDto => Boolean(value));
    const missingArtifactVersionIds = base.evidence
      .map((item) => item.artifact_version_id)
      .filter((id) => !resolvedArtifactVersions.some((v) => v.artifact_version_id === id));

    return {
      decision: base.decision,
      evidence: base.evidence,
      event: events[0] ? mapEvent(events[0]) : undefined,
      snapshot_anchor: snapshot ? mapSnapshot(snapshot) : undefined,
      artifact_versions: resolvedArtifactVersions,
      explanation: buildDecisionExplanation({
        query,
        decision: base.decision,
        evidence: base.evidence,
        event: events[0] ? mapEvent(events[0]) : undefined,
        snapshot: snapshot ? mapSnapshot(snapshot) : undefined,
        artifactVersions: resolvedArtifactVersions,
        missingArtifactVersionIds
      })
    };
  }

  async explainDecision(query: DecisionExplainQuery): Promise<DecisionTraceDto> {
    return this.traceDecision(query);
  }
}

function mapDecision(record: DecisionRecord): DecisionDto {
  return {
    decision_id: record.decision_id,
    case_id: record.case_id,
    event_seq: Number(record.event_seq),
    projection_version: record.projection_version,
    chosen_action: record.chosen_action,
    candidates: JSON.parse(record.candidates_json),
    scores: JSON.parse(record.scores_json),
    constraints_hit: record.constraints_hit,
    detail: JSON.parse(record.detail_json),
    created_at: record.created_at
  };
}

function mapEvidence(record: DecisionEvidenceRecord): DecisionEvidenceDto {
  return {
    decision_evidence_id: record.decision_evidence_id,
    decision_id: record.decision_id,
    artifact_version_id: record.artifact_version_id,
    citation: JSON.parse(record.citation_json),
    created_at: record.created_at
  };
}

function mapArtifactVersion(record: ArtifactVersionRecord): ArtifactVersionDto {
  return {
    artifact_version_id: record.artifact_version_id,
    artifact_id: record.artifact_id,
    version_number: record.version_number,
    status: record.status,
    valid_from: record.valid_from,
    valid_to: record.valid_to || undefined,
    system_from: record.system_from,
    system_to: record.system_to || undefined,
    content_ref: record.content_ref,
    content_hash: record.content_hash || undefined,
    author_id: record.author_id || undefined,
    approver_id: record.approver_id || undefined,
    created_at: record.created_at
  };
}

function mapEvent(record: EventItem): DecisionTraceDto['event'] {
  return {
    event_id: record.event_id,
    case_id: record.case_id,
    event_seq: Number(record.event_seq),
    event_type: record.event_type,
    actor_id: record.actor_id || undefined,
    subject_id: record.subject_id || undefined,
    object_id: record.object_id || undefined,
    payload: JSON.parse(record.payload_json),
    valid_time: record.valid_time,
    system_time: record.system_time
  };
}

function mapSnapshot(record: SnapshotRecord): NonNullable<DecisionTraceDto['snapshot_anchor']> {
  return {
    snapshot_id: record.snapshot_id,
    case_id: record.case_id,
    event_seq: Number(record.event_seq),
    projection_version: record.projection_version,
    state_blob: JSON.parse(record.state_blob_json),
    state_hash: record.state_hash || undefined,
    created_at: record.created_at
  };
}

function buildDecisionExplanation(input: {
  query: DecisionTraceQuery;
  decision?: DecisionDto;
  evidence: DecisionEvidenceDto[];
  event?: DecisionTraceDto['event'];
  snapshot?: DecisionTraceDto['snapshot_anchor'];
  artifactVersions: ArtifactVersionDto[];
  missingArtifactVersionIds: string[];
}): DecisionTraceDto['explanation'] {
  const reasoningSteps: string[] = [];
  const missingComponents: string[] = [];

  if (input.decision) {
    reasoningSteps.push(
      `Decision ${input.decision.decision_id} was found for case ${input.query.case_id} at event_seq ${input.query.event_seq}.`
    );
  } else {
    reasoningSteps.push(
      `No decision record was found for case ${input.query.case_id} at event_seq ${input.query.event_seq}.`
    );
    missingComponents.push('decision');
  }

  if (input.event) {
    reasoningSteps.push(`Event ledger row ${input.event.event_id} supplies the event context.`);
  } else {
    reasoningSteps.push('No event ledger row was found for the requested event_seq.');
    missingComponents.push('event');
  }

  if (input.snapshot) {
    reasoningSteps.push(
      `Snapshot anchor ${input.snapshot.snapshot_id} at event_seq ${input.snapshot.event_seq} supplies replay state.`
    );
  } else {
    reasoningSteps.push('No snapshot anchor was found at or before the requested event_seq.');
    missingComponents.push('snapshot_anchor');
  }

  reasoningSteps.push(`Loaded ${input.evidence.length} evidence link(s) from decision evidence.`);

  if (input.missingArtifactVersionIds.length > 0) {
    reasoningSteps.push(
      `Resolved ${input.artifactVersions.length} artifact version(s); ${input.missingArtifactVersionIds.length} evidence reference(s) are missing.`
    );
    missingComponents.push('artifact_versions');
  } else {
    reasoningSteps.push(`Resolved ${input.artifactVersions.length} artifact version(s) referenced by the decision.`);
  }

  const status = !input.decision
    ? 'missing_decision'
    : missingComponents.length === 0
      ? 'resolved'
      : 'partial';
  const summary =
    status === 'missing_decision'
      ? `No decision record exists for case ${input.query.case_id}, event_seq ${input.query.event_seq}, projection ${input.query.projection_version}.`
      : status === 'resolved'
        ? `Decision ${input.decision?.chosen_action} is fully explained by event context, snapshot anchor, and versioned evidence.`
        : `Decision ${input.decision?.chosen_action} was found, but some supporting components are missing: ${missingComponents.join(', ')}.`;

  return {
    status,
    summary,
    decision_found: Boolean(input.decision),
    event_found: Boolean(input.event),
    snapshot_anchor_found: Boolean(input.snapshot),
    evidence_count: input.evidence.length,
    artifact_version_count: input.artifactVersions.length,
    missing_artifact_version_ids: input.missingArtifactVersionIds,
    missing_components: missingComponents,
    reasoning_steps: reasoningSteps
  };
}

import type { Static } from '@sinclair/typebox';

import { TdbError } from '../errors/tdb_error.js';
import type {
  GatewayBackendClient,
  PropertyRecord as BasePropertyRecord,
  EdgeRecord
} from '../clients/gateway_backend.types.js';
import {
  EdgeAsOfQuerySchema,
  EdgeDiffQuerySchema,
  EdgeUpsertRequestSchema,
  PropertyAsOfQuerySchema,
  PropertyDiffQuerySchema,
  PropertyWhyQuerySchema,
  PropertyUpsertRequestSchema
} from '../schema/v2/state.js';

export type PropertyUpsertRequest = Static<typeof PropertyUpsertRequestSchema>;
export type PropertyAsOfQuery = Static<typeof PropertyAsOfQuerySchema>;
export type EdgeUpsertRequest = Static<typeof EdgeUpsertRequestSchema>;
export type EdgeAsOfQuery = Static<typeof EdgeAsOfQuerySchema>;
export type PropertyDiffQuery = Static<typeof PropertyDiffQuerySchema>;
export type EdgeDiffQuery = Static<typeof EdgeDiffQuerySchema>;
export type PropertyWhyQuery = Static<typeof PropertyWhyQuerySchema>;

export type PropertyRecord = BasePropertyRecord & {
  value: Record<string, unknown>;
};

export type { EdgeRecord };

export type PropertyDiffResult = {
  object_id: string;
  key: string;
  from: {
    valid_time: string;
    system_time: string;
    property?: PropertyRecord;
  };
  to: {
    valid_time: string;
    system_time: string;
    property?: PropertyRecord;
  };
  changed: boolean;
  change_type: 'none' | 'added' | 'removed' | 'updated';
};

export type EdgeDiffResult = {
  src_id: string;
  predicate?: string;
  from: {
    valid_time: string;
    system_time: string;
    edges: EdgeRecord[];
  };
  to: {
    valid_time: string;
    system_time: string;
    edges: EdgeRecord[];
  };
  changed: boolean;
  added: EdgeRecord[];
  removed: EdgeRecord[];
};

export type PropertyWhyResult = {
  object_id: string;
  key: string;
  as_of_valid_time: string;
  as_of_system_time: string;
  selected?: PropertyRecord;
  explanation: {
    outcome: 'selected' | 'not_found';
    summary: string;
    selected_reason_codes: string[];
    diagnostics: string[];
    eligible_candidate_count: number;
    candidate_limit: number;
  };
  candidates: Array<{
    property: PropertyRecord;
    matched_valid_time: boolean;
    matched_system_time: boolean;
    eligible: boolean;
    selected: boolean;
    reason_codes: string[];
  }>;
};

export class StateService {
  constructor(private readonly backend: GatewayBackendClient) {}

  async upsertProperty(request: PropertyUpsertRequest): Promise<PropertyRecord> {
    const res = await this.backend.upsertProperty({
      object_id: request.object_id,
      key: request.key,
      value_json: JSON.stringify(request.value),
      valid_from: request.valid_from,
      system_from: request.system_from,
      source_event_id: request.source_event_id,
      confidence: request.confidence
    });
    return mapProperty(res);
  }

  async getPropertyAsOf(query: PropertyAsOfQuery): Promise<PropertyRecord | undefined> {
    const res = await this.backend.getPropertyAsOf({
      object_id: query.object_id,
      key: query.key,
      as_of_valid_time: query.as_of_valid_time,
      as_of_system_time: query.as_of_system_time
    });
    return res ? mapProperty(res) : undefined;
  }

  async upsertEdge(request: EdgeUpsertRequest): Promise<EdgeRecord> {
    const res = await this.backend.upsertEdge({
      src_id: request.src_id,
      predicate: request.predicate,
      dst_id: request.dst_id,
      valid_from: request.valid_from,
      system_from: request.system_from,
      source_event_id: request.source_event_id,
      confidence: request.confidence
    });
    return mapEdge(res);
  }

  async getEdgesAsOf(query: EdgeAsOfQuery): Promise<EdgeRecord[]> {
    const items = await this.backend.getEdgesAsOf({
      src_id: query.src_id,
      predicate: query.predicate,
      as_of_valid_time: query.as_of_valid_time,
      as_of_system_time: query.as_of_system_time
    });
    return items.map(mapEdge);
  }

  async diffProperty(query: PropertyDiffQuery): Promise<PropertyDiffResult> {
    const fromSystem = query.from_system_time ?? nowIso();
    const toSystem = query.to_system_time ?? nowIso();
    const [fromProperty, toProperty] = await Promise.all([
      this.getPropertyAsOf({
        object_id: query.object_id,
        key: query.key,
        as_of_valid_time: query.from_valid_time,
        as_of_system_time: fromSystem
      }),
      this.getPropertyAsOf({
        object_id: query.object_id,
        key: query.key,
        as_of_valid_time: query.to_valid_time,
        as_of_system_time: toSystem
      })
    ]);

    return {
      object_id: query.object_id,
      key: query.key,
      from: {
        valid_time: normalizeIso(query.from_valid_time),
        system_time: normalizeIso(fromSystem),
        property: fromProperty
      },
      to: {
        valid_time: normalizeIso(query.to_valid_time),
        system_time: normalizeIso(toSystem),
        property: toProperty
      },
      changed: !arePropertiesEquivalent(fromProperty, toProperty),
      change_type: classifyPropertyChange(fromProperty, toProperty)
    };
  }

  async explainProperty(query: PropertyWhyQuery): Promise<PropertyWhyResult> {
    const asOfSystem = query.as_of_system_time ?? nowIso();
    const candidateLimit = query.candidate_limit ?? 10;
    const [selected, candidateRecords] = await Promise.all([
      this.getPropertyAsOf({
        object_id: query.object_id,
        key: query.key,
        as_of_valid_time: query.as_of_valid_time,
        as_of_system_time: asOfSystem
      }),
      this.backend.listPropertyRows({
        object_id: query.object_id,
        key: query.key,
        limit: candidateLimit
      })
    ]);

    const candidates = candidateRecords.map(mapProperty).map((property) => {
      const matchedValidTime = isTimeWithinInterval(
        query.as_of_valid_time,
        property.valid_from,
        property.valid_to
      );
      const matchedSystemTime = isTimeWithinInterval(
        asOfSystem,
        property.system_from,
        property.system_to
      );
      const eligible = matchedValidTime && matchedSystemTime;
      const selectedCandidate = property.property_state_id === selected?.property_state_id;
      const reasonCodes = explainPropertyCandidate(
        property,
        selected,
        matchedValidTime,
        matchedSystemTime,
        selectedCandidate
      );

      return {
        property,
        matched_valid_time: matchedValidTime,
        matched_system_time: matchedSystemTime,
        eligible,
        selected: selectedCandidate,
        reason_codes: reasonCodes
      };
    });

    const eligibleCandidateCount = candidates.filter((item) => item.eligible).length;
    const selectedReasonCodes = selected ? explainSelectedProperty(selected) : [];
    const summary = selected
      ? `Selected property row ${selected.property_state_id} for ${query.key} because it matches the as-of window and has the highest precedence.`
      : `No property row matches object ${query.object_id} key ${query.key} at the requested as-of window.`;

    return {
      object_id: query.object_id,
      key: query.key,
      as_of_valid_time: normalizeIso(query.as_of_valid_time),
      as_of_system_time: normalizeIso(asOfSystem),
      selected,
      explanation: {
        outcome: selected ? 'selected' : 'not_found',
        summary,
        selected_reason_codes: selectedReasonCodes,
        diagnostics: selected ? [] : ['no_candidate_matched_bitemporal_window'],
        eligible_candidate_count: eligibleCandidateCount,
        candidate_limit: candidateLimit
      },
      candidates
    };
  }

  async diffEdges(query: EdgeDiffQuery): Promise<EdgeDiffResult> {
    const fromSystem = query.from_system_time ?? nowIso();
    const toSystem = query.to_system_time ?? nowIso();
    const [fromEdges, toEdges] = await Promise.all([
      this.getEdgesAsOf({
        src_id: query.src_id,
        predicate: query.predicate,
        as_of_valid_time: query.from_valid_time,
        as_of_system_time: fromSystem
      }),
      this.getEdgesAsOf({
        src_id: query.src_id,
        predicate: query.predicate,
        as_of_valid_time: query.to_valid_time,
        as_of_system_time: toSystem
      })
    ]);

    const fromKeys = new Set(fromEdges.map(edgeIdentity));
    const toKeys = new Set(toEdges.map(edgeIdentity));
    const added = toEdges.filter((edge) => !fromKeys.has(edgeIdentity(edge)));
    const removed = fromEdges.filter((edge) => !toKeys.has(edgeIdentity(edge)));

    return {
      src_id: query.src_id,
      predicate: query.predicate,
      from: {
        valid_time: normalizeIso(query.from_valid_time),
        system_time: normalizeIso(fromSystem),
        edges: fromEdges
      },
      to: {
        valid_time: normalizeIso(query.to_valid_time),
        system_time: normalizeIso(toSystem),
        edges: toEdges
      },
      changed: added.length > 0 || removed.length > 0,
      added,
      removed
    };
  }
}

function mapProperty(p: BasePropertyRecord): PropertyRecord {
  let value: Record<string, unknown> = {};
  if ((p as any).value_json) {
    try {
      value = JSON.parse((p as any).value_json);
    } catch (e) {
      // Ignore parse error
    }
  } else if ((p as any).value) {
    value = (p as any).value;
  }
  
  return {
    ...p,
    value: value as any,
    valid_from: normalizeIso(p.valid_from),
    valid_to: p.valid_to ? normalizeIso(p.valid_to) : undefined,
    system_from: normalizeIso(p.system_from),
    system_to: p.system_to ? normalizeIso(p.system_to) : undefined,
    source_event_id: p.source_event_id || undefined,
    confidence: p.confidence || undefined
  } as PropertyRecord;
}

function mapEdge(e: EdgeRecord): EdgeRecord {
  return {
    ...e,
    valid_from: normalizeIso(e.valid_from),
    valid_to: e.valid_to ? normalizeIso(e.valid_to) : undefined,
    system_from: normalizeIso(e.system_from),
    system_to: e.system_to ? normalizeIso(e.system_to) : undefined,
    source_event_id: e.source_event_id || undefined,
    confidence: e.confidence || undefined
  };
}

function normalizeIso(value: string): string {
  return new Date(value).toISOString();
}

function isTimeWithinInterval(value: string, from: string, to?: string): boolean {
  const point = new Date(value).getTime();
  const start = new Date(from).getTime();
  const end = to ? new Date(to).getTime() : Number.POSITIVE_INFINITY;
  return point >= start && point < end;
}

function explainSelectedProperty(property: PropertyRecord): string[] {
  const reasons = ['matched_valid_time', 'matched_system_time', 'selected_highest_precedence'];
  if (!property.valid_to) {
    reasons.push('open_valid_interval');
  }
  if (!property.system_to) {
    reasons.push('open_system_interval');
  }
  return reasons;
}

function explainPropertyCandidate(
  property: PropertyRecord,
  selected: PropertyRecord | undefined,
  matchedValidTime: boolean,
  matchedSystemTime: boolean,
  selectedCandidate: boolean
): string[] {
  if (selectedCandidate) {
    return explainSelectedProperty(property);
  }

  const reasons: string[] = [];
  if (!matchedValidTime) {
    reasons.push('outside_valid_window');
  }
  if (!matchedSystemTime) {
    reasons.push('outside_system_window');
  }
  if (reasons.length > 0) {
    return reasons;
  }
  if (selected) {
    const selectedValid = new Date(selected.valid_from).getTime();
    const candidateValid = new Date(property.valid_from).getTime();
    if (selectedValid > candidateValid) {
      reasons.push('superseded_by_newer_valid_from');
    } else {
      const selectedSystem = new Date(selected.system_from).getTime();
      const candidateSystem = new Date(property.system_from).getTime();
      if (selectedSystem > candidateSystem) {
        reasons.push('superseded_by_newer_system_from');
      } else {
        reasons.push('lower_precedence_match');
      }
    }
  } else {
    reasons.push('not_selected');
  }
  return reasons;
}

function nowIso(): string {
  return new Date().toISOString();
}

function arePropertiesEquivalent(a?: PropertyRecord, b?: PropertyRecord): boolean {
  if (!a && !b) {
    return true;
  }
  if (!a || !b) {
    return false;
  }
  return JSON.stringify(a.value) === JSON.stringify(b.value);
}

function classifyPropertyChange(
  fromProperty?: PropertyRecord,
  toProperty?: PropertyRecord
): PropertyDiffResult['change_type'] {
  if (!fromProperty && !toProperty) {
    return 'none';
  }
  if (!fromProperty && toProperty) {
    return 'added';
  }
  if (fromProperty && !toProperty) {
    return 'removed';
  }
  return arePropertiesEquivalent(fromProperty, toProperty) ? 'none' : 'updated';
}

function edgeIdentity(edge: EdgeRecord): string {
  return `${edge.src_id}|${edge.predicate}|${edge.dst_id}`;
}

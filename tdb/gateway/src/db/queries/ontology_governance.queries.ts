import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';

import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export type OntologyFactRow = {
  fact_id: string;
  src_concept_id: string;
  predicate: string;
  dst_concept_id: string;
  qualifier_json: Record<string, unknown>;
  confidence: number;
  extractor: string;
  status: string;
  review_note: string;
  valid_from: string | null;
  valid_to: string | null;
  created_at: string;
  updated_at: string;
};

export type OntologyFactReviewRow = {
  review_id: string;
  reviewer: string;
  decision: string;
  note: string;
  created_at: string;
};

export type OntologyFactEvidenceRow = {
  stream_id: string;
  event_id: string;
  asset_id: string | null;
  version_number: string | null;
  source_span: string | null;
  evidence_json: Record<string, unknown>;
  confidence: number;
  created_at: string;
  updated_at: string;
};

export type OntologyFactBulkSelectionRow = {
  fact_id: string;
  status: string;
  confidence: number;
};

export type OntologyFactLinkedCaseRow = {
  case_id: string;
  stream_id: string;
  title: string;
  status: string;
  priority: string;
  owner: string;
  linked_at: string;
};

export type OntologyFactLinkedAlertRow = {
  alert_id: string;
  case_id: string | null;
  stream_id: string;
  severity: string;
  status: string;
  message: string;
  rule_key: string | null;
  linked_at: string;
};

export async function reviewOntologyFact(
  tx: DatabaseTransactionConnection,
  input: {
    factId: number;
    decision: 'accept' | 'reject' | 'needs_work';
    reviewer: string;
    note: string;
  }
): Promise<number> {
  const status = decisionToFactStatus(input.decision);
  const updatedRow = await tx.one(sql.typeAlias('record')`
    WITH updated AS (
      UPDATE ontology_fact
      SET status = ${status},
          review_note = CASE
            WHEN ${input.note.trim()} = '' THEN review_note
            ELSE ${input.note.trim()}
          END,
          updated_at = NOW()
      WHERE fact_id = ${input.factId}
      RETURNING fact_id
    ),
    inserted AS (
      INSERT INTO ontology_fact_review (fact_id, reviewer, decision, note)
      SELECT fact_id, ${input.reviewer.trim()}, ${input.decision}, ${input.note.trim()}
      FROM updated
      RETURNING fact_id
    )
    SELECT COUNT(*)::text AS updated_rows
    FROM inserted
  `);

  return Number((updatedRow as Record<string, unknown>).updated_rows ?? 0);
}

export async function getOntologyFact(
  db: Queryable,
  factId: number
): Promise<OntologyFactRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      fact_id::text,
      src_concept_id,
      predicate,
      dst_concept_id,
      qualifier_json,
      confidence,
      extractor,
      status,
      review_note,
      valid_from::text,
      valid_to::text,
      created_at::text,
      updated_at::text
    FROM ontology_fact
    WHERE fact_id = ${factId}
  `);

  return row ? (row as unknown as OntologyFactRow) : undefined;
}

export async function listOntologyFactReviews(
  db: Queryable,
  factId: number
): Promise<OntologyFactReviewRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      review_id::text,
      reviewer,
      decision,
      note,
      created_at::text
    FROM ontology_fact_review
    WHERE fact_id = ${factId}
    ORDER BY created_at DESC
  `);

  return rows as unknown as OntologyFactReviewRow[];
}

export async function listOntologyFactEvidence(
  db: Queryable,
  input: {
    factId: number;
    evidenceLimit: number;
    streamId?: string;
  }
): Promise<OntologyFactEvidenceRow[]> {
  const predicates = [sql.fragment`fact_id = ${input.factId}`];
  if (input.streamId) {
    predicates.push(sql.fragment`stream_id = ${input.streamId}`);
  }

  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      stream_id,
      event_id,
      asset_id,
      version_number::text,
      source_span,
      evidence_json,
      confidence,
      created_at::text,
      updated_at::text
    FROM ontology_fact_evidence
    WHERE ${sql.join(predicates, sql.fragment` AND `)}
    ORDER BY updated_at DESC
    LIMIT ${input.evidenceLimit}
  `);

  return rows as unknown as OntologyFactEvidenceRow[];
}

export async function listOntologyFactLinkedCases(
  db: Queryable,
  factId: number
): Promise<OntologyFactLinkedCaseRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      c.case_id::text,
      c.stream_id,
      c.title,
      c.status,
      c.priority,
      c.owner,
      cf.created_at::text AS linked_at
    FROM ontology_case_fact cf
    JOIN ontology_case c ON c.case_id = cf.case_id
    WHERE cf.fact_id = ${factId}
    ORDER BY cf.created_at DESC
  `);

  return rows as unknown as OntologyFactLinkedCaseRow[];
}

export async function listOntologyFactLinkedAlerts(
  db: Queryable,
  factId: number
): Promise<OntologyFactLinkedAlertRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      a.alert_id::text,
      a.case_id::text,
      a.stream_id,
      a.severity,
      a.status,
      a.message,
      a.rule_key,
      af.created_at::text AS linked_at
    FROM ontology_alert_fact af
    JOIN ontology_alert a ON a.alert_id = af.alert_id
    WHERE af.fact_id = ${factId}
    ORDER BY af.created_at DESC
  `);

  return rows as unknown as OntologyFactLinkedAlertRow[];
}

export async function selectOntologyFactsForBulkReview(
  db: Queryable,
  input: {
    status: string;
    streamId?: string;
    predicate?: string;
    extractor?: string;
    staleDays?: number;
    minConfidence: number;
    maxConfidence: number;
    limit: number;
  }
): Promise<OntologyFactBulkSelectionRow[]> {
  const streamJoin = input.streamId
    ? sql.fragment`JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id`
    : sql.fragment``;
  const predicates = [
    input.status === 'all' ? sql.fragment`TRUE` : sql.fragment`f.status = ${input.status}`,
    sql.fragment`f.confidence >= ${input.minConfidence}`,
    sql.fragment`f.confidence <= ${input.maxConfidence}`
  ];
  if (input.streamId) {
    predicates.push(sql.fragment`fe.stream_id = ${input.streamId}`);
  }
  if (input.predicate) {
    predicates.push(sql.fragment`f.predicate = ${input.predicate}`);
  }
  if (input.extractor) {
    predicates.push(sql.fragment`f.extractor = ${input.extractor}`);
  }
  if (input.staleDays) {
    predicates.push(
      sql.fragment`f.updated_at < (NOW() - make_interval(days => ${input.staleDays}))`
    );
  }

  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      f.fact_id::text,
      f.status,
      f.confidence
    FROM ontology_fact f
    ${streamJoin}
    WHERE ${sql.join(predicates, sql.fragment` AND `)}
    GROUP BY f.fact_id, f.status, f.confidence, f.updated_at
    ORDER BY f.confidence DESC, f.updated_at DESC
    LIMIT ${input.limit}
  `);

  return rows as unknown as OntologyFactBulkSelectionRow[];
}

export type OntologyCaseRow = {
  case_id: string;
  stream_id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  owner: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
};

export type OntologyCaseSummaryRow = OntologyCaseRow & {
  fact_count: string;
  active_alert_count: string;
};

export type OntologyCaseFactRow = {
  fact_id: string;
  src_concept_id: string;
  predicate: string;
  dst_concept_id: string;
  confidence: number;
  status: string;
  extractor: string;
  updated_at: string;
  linked_at: string;
  added_by: string;
  added_note: string;
  evidence_count: string;
  evidence_sample: unknown;
};

export type OntologyCaseEventRow = {
  event_id: string;
  action: string;
  actor: string;
  note: string;
  payload_json: Record<string, unknown>;
  created_at: string;
};

export type OntologyAlertRow = {
  alert_id: string;
  case_id: string | null;
  stream_id: string;
  severity: string;
  status: string;
  message: string;
  detail_json: Record<string, unknown>;
  rule_key: string | null;
  trigger_count: number;
  first_triggered_at: string;
  last_triggered_at: string;
  acked_by: string | null;
  acked_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  case_title?: string | null;
  linked_fact_count?: string;
  linked_fact_ids?: unknown;
};

export type OntologyOpsRuleConfigRow = {
  config_id: string;
  stream_id: string | null;
  rule_name: string;
  enabled: boolean;
  stale_days: string | null;
  conflict_predicate: string | null;
  severity: string | null;
  note: string;
  updated_by: string;
  updated_at: string;
};

export type OntologyOpsRuleRunRow = {
  run_id: string;
  stream_id_filter: string | null;
  stale_days: string;
  conflict_predicate: string;
  dry_run: boolean;
  candidate_count: string;
  created_case_count: string;
  existing_case_count: string;
  created_alert_count: string;
  existing_alert_count: string;
  payload_json?: Record<string, unknown>;
  duration_ms: string;
  started_at: string;
  finished_at: string;
};

export type StalePendingCandidateRow = {
  stream_id: string;
  stale_fact_count: string;
  fact_ids: number[];
};

export type ConflictPredicateCandidateRow = {
  stream_id: string;
  src_concept_id: string;
  dst_count: string;
  dst_values: string[];
  fact_count: string;
  fact_ids: number[];
};

export async function insertOntologyCase(
  tx: DatabaseTransactionConnection,
  input: {
    streamId: string;
    title: string;
    description: string;
    priority: string;
    owner: string;
    createdBy: string;
  }
): Promise<OntologyCaseRow> {
  const row = await tx.one(sql.typeAlias('record')`
    INSERT INTO ontology_case (
      stream_id, title, description, status, priority, owner, created_by
    ) VALUES (
      ${input.streamId},
      ${input.title},
      ${input.description},
      'open',
      ${input.priority},
      ${input.owner},
      ${input.createdBy}
    )
    RETURNING
      case_id::text,
      stream_id,
      title,
      description,
      status,
      priority,
      owner,
      created_by,
      created_at::text,
      updated_at::text,
      closed_at::text
  `);

  return row as unknown as OntologyCaseRow;
}

export async function insertOntologyCaseEvent(
  tx: DatabaseTransactionConnection,
  input: {
    caseId: number;
    action: 'open' | 'status_change' | 'owner_change' | 'fact_link' | 'note' | 'alert_link';
    actor: string;
    note: string;
    payloadJson: Record<string, unknown>;
  }
): Promise<void> {
  await tx.query(sql.typeAlias('void')`
    INSERT INTO ontology_case_event (case_id, action, actor, note, payload_json)
    VALUES (
      ${input.caseId},
      ${input.action},
      ${input.actor},
      ${input.note},
      ${JSON.stringify(input.payloadJson)}::jsonb
    )
  `);
}

export async function linkOntologyCaseFact(
  tx: DatabaseTransactionConnection,
  input: {
    caseId: number;
    factId: number;
    addedBy: string;
    addedNote: string;
    streamId: string;
  }
): Promise<boolean> {
  const row = await tx.one(sql.typeAlias('record')`
    WITH inserted AS (
      INSERT INTO ontology_case_fact (case_id, fact_id, added_by, added_note)
      SELECT
        ${input.caseId},
        ${input.factId},
        ${input.addedBy},
        ${input.addedNote}
      WHERE EXISTS (
        SELECT 1 FROM ontology_fact f WHERE f.fact_id = ${input.factId}
      )
        AND EXISTS (
          SELECT 1
          FROM ontology_fact_evidence fe
          WHERE fe.fact_id = ${input.factId}
            AND fe.stream_id = ${input.streamId}
        )
      ON CONFLICT (case_id, fact_id) DO NOTHING
      RETURNING fact_id
    )
    SELECT EXISTS(SELECT 1 FROM inserted) AS inserted
  `);

  return Boolean((row as Record<string, unknown>).inserted);
}

export async function listOntologyCases(
  db: Queryable,
  input: {
    streamId?: string;
    status: string;
    limit: number;
  }
): Promise<OntologyCaseSummaryRow[]> {
  const predicates = [
    input.streamId ? sql.fragment`c.stream_id = ${input.streamId}` : sql.fragment`TRUE`,
    input.status === 'all' ? sql.fragment`TRUE` : sql.fragment`c.status = ${input.status}`
  ];

  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      c.case_id::text,
      c.stream_id,
      c.title,
      c.description,
      c.status,
      c.priority,
      c.owner,
      c.created_by,
      c.created_at::text,
      c.updated_at::text,
      c.closed_at::text,
      (
        SELECT COUNT(*)::text
        FROM ontology_case_fact cf
        WHERE cf.case_id = c.case_id
      ) AS fact_count,
      (
        SELECT COUNT(*)::text
        FROM ontology_alert a
        WHERE a.case_id = c.case_id
          AND a.status <> 'closed'
      ) AS active_alert_count
    FROM ontology_case c
    WHERE ${sql.join(predicates, sql.fragment` AND `)}
    ORDER BY c.updated_at DESC
    LIMIT ${input.limit}
  `);

  return rows as unknown as OntologyCaseSummaryRow[];
}

export async function getOntologyCase(
  db: Queryable,
  caseId: number
): Promise<OntologyCaseRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      case_id::text,
      stream_id,
      title,
      description,
      status,
      priority,
      owner,
      created_by,
      created_at::text,
      updated_at::text,
      closed_at::text
    FROM ontology_case
    WHERE case_id = ${caseId}
  `);

  return row ? (row as unknown as OntologyCaseRow) : undefined;
}

export async function listOntologyCaseFacts(
  db: Queryable,
  input: {
    caseId: number;
    evidenceLimit: number;
  }
): Promise<OntologyCaseFactRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      f.fact_id::text,
      f.src_concept_id,
      f.predicate,
      f.dst_concept_id,
      f.confidence,
      f.status,
      f.extractor,
      f.updated_at::text,
      cf.created_at::text AS linked_at,
      cf.added_by,
      cf.added_note,
      (
        SELECT COUNT(*)::text
        FROM ontology_fact_evidence fe
        WHERE fe.fact_id = f.fact_id
      ) AS evidence_count,
      (
        SELECT COALESCE(json_agg(
          json_build_object(
            'stream_id', x.stream_id,
            'event_id', x.event_id,
            'session_id', x.session_id,
            'updated_at', x.updated_at::text,
            'source_span', x.source_span,
            'text_snippet', x.text_snippet
          )
          ORDER BY x.updated_at DESC
        ), '[]'::json)
        FROM (
          SELECT
            fe.stream_id,
            fe.event_id,
            COALESCE(
              cel.payload->>'session_id',
              cel.payload->>'sessionId',
              ''
            ) AS session_id,
            fe.updated_at,
            fe.source_span,
            LEFT(COALESCE(cel.payload->>'text', ''), 280) AS text_snippet
          FROM ontology_fact_evidence fe
          LEFT JOIN case_event_ledger cel
            ON cel.event_id::text = fe.event_id
          WHERE fe.fact_id = f.fact_id
          ORDER BY fe.updated_at DESC
          LIMIT ${input.evidenceLimit}
        ) x
      ) AS evidence_sample
    FROM ontology_case_fact cf
    JOIN ontology_fact f ON f.fact_id = cf.fact_id
    WHERE cf.case_id = ${input.caseId}
    ORDER BY cf.created_at DESC
  `);

  return rows as unknown as OntologyCaseFactRow[];
}

export async function listOntologyCaseEvents(
  db: Queryable,
  caseId: number
): Promise<OntologyCaseEventRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      event_id::text,
      action,
      actor,
      note,
      payload_json,
      created_at::text
    FROM ontology_case_event
    WHERE case_id = ${caseId}
    ORDER BY created_at DESC
  `);

  return rows as unknown as OntologyCaseEventRow[];
}

export async function listOntologyAlertsForCase(
  db: Queryable,
  caseId: number
): Promise<OntologyAlertRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      a.alert_id::text,
      a.case_id::text,
      a.stream_id,
      a.severity,
      a.status,
      a.message,
      a.detail_json,
      a.rule_key,
      a.trigger_count,
      a.first_triggered_at::text,
      a.last_triggered_at::text,
      a.acked_by,
      a.acked_at::text,
      a.closed_at::text,
      a.created_at::text,
      a.updated_at::text,
      COALESCE(
        (
          SELECT json_agg(af.fact_id ORDER BY af.fact_id)
          FROM ontology_alert_fact af
          WHERE af.alert_id = a.alert_id
        ),
        '[]'::json
      ) AS linked_fact_ids
    FROM ontology_alert a
    WHERE a.case_id = ${caseId}
    ORDER BY a.updated_at DESC
  `);

  return rows as unknown as OntologyAlertRow[];
}

export async function updateOntologyCase(
  tx: DatabaseTransactionConnection,
  input: {
    caseId: number;
    status?: string;
    owner?: string;
  }
): Promise<OntologyCaseRow | undefined> {
  const row = await tx.maybeOne(sql.typeAlias('record')`
    UPDATE ontology_case
    SET
      status = COALESCE(${input.status ?? null}, status),
      owner = COALESCE(${input.owner ?? null}, owner),
      updated_at = NOW(),
      closed_at = CASE
        WHEN COALESCE(${input.status ?? null}, status) IN ('resolved', 'dismissed') THEN COALESCE(closed_at, NOW())
        WHEN COALESCE(${input.status ?? null}, status) IN ('open', 'in_review') THEN NULL
        ELSE closed_at
      END
    WHERE case_id = ${input.caseId}
    RETURNING
      case_id::text,
      stream_id,
      title,
      description,
      status,
      priority,
      owner,
      created_by,
      created_at::text,
      updated_at::text,
      closed_at::text
  `);

  return row ? (row as unknown as OntologyCaseRow) : undefined;
}

export async function getOntologyCaseStream(
  db: Queryable,
  caseId: number
): Promise<string | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT stream_id
    FROM ontology_case
    WHERE case_id = ${caseId}
    LIMIT 1
  `);

  return row ? ((row as Record<string, unknown>).stream_id as string | undefined) : undefined;
}

export async function insertOntologyAlert(
  tx: DatabaseTransactionConnection,
  input: {
    caseId?: number;
    streamId: string;
    severity: string;
    message: string;
    detailJson: Record<string, unknown>;
    ruleKey?: string;
  }
): Promise<OntologyAlertRow> {
  const row = await tx.one(sql.typeAlias('record')`
    INSERT INTO ontology_alert (case_id, stream_id, severity, status, message, detail_json, rule_key)
    VALUES (
      ${input.caseId ?? null},
      ${input.streamId},
      ${input.severity},
      'open',
      ${input.message},
      ${JSON.stringify(input.detailJson)}::jsonb,
      ${input.ruleKey ?? null}
    )
    RETURNING
      alert_id::text,
      case_id::text,
      stream_id,
      severity,
      status,
      message,
      detail_json,
      rule_key,
      trigger_count,
      first_triggered_at::text,
      last_triggered_at::text,
      acked_by,
      acked_at::text,
      closed_at::text,
      created_at::text,
      updated_at::text
  `);

  return row as unknown as OntologyAlertRow;
}

export async function listOntologyAlerts(
  db: Queryable,
  input: {
    streamId?: string;
    status: string;
    limit: number;
  }
): Promise<OntologyAlertRow[]> {
  const predicates = [
    input.streamId ? sql.fragment`a.stream_id = ${input.streamId}` : sql.fragment`TRUE`,
    input.status === 'all' ? sql.fragment`TRUE` : sql.fragment`a.status = ${input.status}`
  ];

  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      a.alert_id::text,
      a.case_id::text,
      a.stream_id,
      a.severity,
      a.status,
      a.message,
      a.detail_json,
      a.rule_key,
      a.trigger_count,
      a.first_triggered_at::text,
      a.last_triggered_at::text,
      a.acked_by,
      a.acked_at::text,
      a.closed_at::text,
      a.created_at::text,
      a.updated_at::text,
      c.title AS case_title,
      (
        SELECT COUNT(*)::text
        FROM ontology_alert_fact af
        WHERE af.alert_id = a.alert_id
      ) AS linked_fact_count
    FROM ontology_alert a
    LEFT JOIN ontology_case c ON c.case_id = a.case_id
    WHERE ${sql.join(predicates, sql.fragment` AND `)}
    ORDER BY
      CASE a.severity
        WHEN 'critical' THEN 1
        WHEN 'high' THEN 2
        WHEN 'medium' THEN 3
        ELSE 4
      END ASC,
      a.updated_at DESC
    LIMIT ${input.limit}
  `);

  return rows as unknown as OntologyAlertRow[];
}

export async function getOntologyAlertDetail(
  db: Queryable,
  alertId: number
): Promise<OntologyAlertRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      a.alert_id::text,
      a.case_id::text,
      a.stream_id,
      a.severity,
      a.status,
      a.message,
      a.detail_json,
      a.rule_key,
      a.trigger_count,
      a.first_triggered_at::text,
      a.last_triggered_at::text,
      a.acked_by,
      a.acked_at::text,
      a.closed_at::text,
      a.created_at::text,
      a.updated_at::text,
      c.title AS case_title,
      (
        SELECT COUNT(*)::text
        FROM ontology_alert_fact af
        WHERE af.alert_id = a.alert_id
      ) AS linked_fact_count,
      COALESCE(
        (
          SELECT json_agg(af.fact_id ORDER BY af.fact_id)
          FROM ontology_alert_fact af
          WHERE af.alert_id = a.alert_id
        ),
        '[]'::json
      ) AS linked_fact_ids
    FROM ontology_alert a
    LEFT JOIN ontology_case c ON c.case_id = a.case_id
    WHERE a.alert_id = ${alertId}
    LIMIT 1
  `);

  return row ? (row as unknown as OntologyAlertRow) : undefined;
}

export async function updateOntologyAlert(
  tx: DatabaseTransactionConnection,
  input: {
    alertId: number;
    status: string;
    actor: string;
  }
): Promise<OntologyAlertRow | undefined> {
  const row = await tx.maybeOne(sql.typeAlias('record')`
    UPDATE ontology_alert
    SET
      status = ${input.status},
      updated_at = NOW(),
      acked_by = CASE WHEN ${input.status} = 'acked' THEN ${input.actor} ELSE acked_by END,
      acked_at = CASE WHEN ${input.status} = 'acked' THEN NOW() ELSE acked_at END,
      closed_at = CASE WHEN ${input.status} = 'closed' THEN NOW() ELSE NULL END
    WHERE alert_id = ${input.alertId}
    RETURNING
      alert_id::text,
      case_id::text,
      stream_id,
      severity,
      status,
      message,
      detail_json,
      rule_key,
      trigger_count,
      first_triggered_at::text,
      last_triggered_at::text,
      acked_by,
      acked_at::text,
      closed_at::text,
      created_at::text,
      updated_at::text
  `);

  return row ? (row as unknown as OntologyAlertRow) : undefined;
}

export async function getActiveOntologyCaseByTitle(
  db: Queryable,
  input: {
    streamId: string;
    title: string;
  }
): Promise<OntologyCaseRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      case_id::text,
      stream_id,
      title,
      description,
      status,
      priority,
      owner,
      created_by,
      created_at::text,
      updated_at::text,
      closed_at::text
    FROM ontology_case
    WHERE stream_id = ${input.streamId}
      AND title = ${input.title}
      AND status IN ('open', 'in_review')
    ORDER BY updated_at DESC
    LIMIT 1
  `);

  return row ? (row as unknown as OntologyCaseRow) : undefined;
}

export async function getActiveOntologyAlertByRuleKey(
  db: Queryable,
  input: {
    streamId: string;
    ruleKey: string;
  }
): Promise<OntologyAlertRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      alert_id::text,
      case_id::text,
      stream_id,
      severity,
      status,
      message,
      detail_json,
      rule_key,
      trigger_count,
      first_triggered_at::text,
      last_triggered_at::text,
      acked_by,
      acked_at::text,
      closed_at::text,
      created_at::text,
      updated_at::text
    FROM ontology_alert
    WHERE stream_id = ${input.streamId}
      AND rule_key = ${input.ruleKey}
      AND status IN ('open', 'acked')
    ORDER BY updated_at DESC
    LIMIT 1
  `);

  return row ? (row as unknown as OntologyAlertRow) : undefined;
}

export async function refreshTriggeredOntologyAlert(
  tx: DatabaseTransactionConnection,
  input: {
    alertId: number;
    caseId: number;
    severity: string;
    message: string;
    detailJson: Record<string, unknown>;
  }
): Promise<void> {
  await tx.query(sql.typeAlias('void')`
    UPDATE ontology_alert
    SET
      case_id = COALESCE(case_id, ${input.caseId}),
      severity = ${input.severity},
      message = ${input.message},
      detail_json = ${JSON.stringify(input.detailJson)}::jsonb,
      trigger_count = GREATEST(trigger_count + 1, 1),
      last_triggered_at = NOW(),
      updated_at = NOW()
    WHERE alert_id = ${input.alertId}
  `);
}

export async function linkOntologyAlertFact(
  tx: DatabaseTransactionConnection,
  input: {
    alertId: number;
    factId: number;
    linkedBy: string;
    linkedNote: string;
  }
): Promise<void> {
  await tx.query(sql.typeAlias('void')`
    INSERT INTO ontology_alert_fact (alert_id, fact_id, linked_by, linked_note)
    VALUES (
      ${input.alertId},
      ${input.factId},
      ${input.linkedBy},
      ${input.linkedNote}
    )
    ON CONFLICT (alert_id, fact_id) DO NOTHING
  `);
}

export async function listOntologyOpsRuleConfig(
  db: Queryable,
  streamId?: string
): Promise<OntologyOpsRuleConfigRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      config_id::text,
      stream_id,
      rule_name,
      enabled,
      stale_days::text,
      conflict_predicate,
      severity,
      note,
      updated_by,
      updated_at::text
    FROM ontology_ops_rule_config
    WHERE ${
      streamId
        ? sql.fragment`stream_id = ${streamId} OR stream_id IS NULL`
        : sql.fragment`TRUE`
    }
    ORDER BY
      CASE WHEN stream_id IS NULL THEN 1 ELSE 0 END,
      stream_id ASC NULLS LAST,
      rule_name ASC
  `);

  return rows as unknown as OntologyOpsRuleConfigRow[];
}

export async function listApplicableOntologyOpsRuleConfig(
  db: Queryable,
  streamId?: string
): Promise<OntologyOpsRuleConfigRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      config_id::text,
      stream_id,
      rule_name,
      enabled,
      stale_days::text,
      conflict_predicate,
      severity,
      note,
      updated_by,
      updated_at::text
    FROM ontology_ops_rule_config
    WHERE ${
      streamId
        ? sql.fragment`stream_id = ${streamId} OR stream_id IS NULL`
        : sql.fragment`stream_id IS NULL`
    }
    ORDER BY
      CASE
        WHEN ${streamId ?? null}::text IS NOT NULL AND stream_id = ${streamId ?? null}::text THEN 1
        ELSE 0
      END ASC,
      updated_at ASC
  `);

  return rows as unknown as OntologyOpsRuleConfigRow[];
}

export async function upsertOntologyOpsRuleConfig(
  tx: DatabaseTransactionConnection,
  input: {
    ruleName: string;
    streamId?: string;
    enabled: boolean;
    staleDays?: number;
    conflictPredicate?: string;
    severity?: string;
    note: string;
    updatedBy: string;
  }
): Promise<OntologyOpsRuleConfigRow> {
  const existing = await tx.maybeOne(sql.typeAlias('record')`
    SELECT config_id::text
    FROM ontology_ops_rule_config
    WHERE rule_name = ${input.ruleName}
      AND COALESCE(stream_id, '') = COALESCE(${input.streamId ?? null}, '')
    LIMIT 1
  `);

  if (existing) {
    const row = await tx.one(sql.typeAlias('record')`
      UPDATE ontology_ops_rule_config
      SET
        enabled = ${input.enabled},
        stale_days = COALESCE(${input.staleDays ?? null}, stale_days),
        conflict_predicate = COALESCE(${input.conflictPredicate ?? null}, conflict_predicate),
        severity = COALESCE(${input.severity ?? null}, severity),
        note = ${input.note},
        updated_by = ${input.updatedBy},
        updated_at = NOW()
      WHERE config_id = ${(existing as Record<string, unknown>).config_id as string}::bigint
      RETURNING
        config_id::text,
        stream_id,
        rule_name,
        enabled,
        stale_days::text,
        conflict_predicate,
        severity,
        note,
        updated_by,
        updated_at::text
    `);
    return row as unknown as OntologyOpsRuleConfigRow;
  }

  const row = await tx.one(sql.typeAlias('record')`
    INSERT INTO ontology_ops_rule_config (
      stream_id,
      rule_name,
      enabled,
      stale_days,
      conflict_predicate,
      severity,
      note,
      updated_by
    ) VALUES (
      ${input.streamId ?? null},
      ${input.ruleName},
      ${input.enabled},
      ${input.staleDays ?? null},
      ${input.conflictPredicate ?? null},
      ${input.severity ?? null},
      ${input.note},
      ${input.updatedBy}
    )
    RETURNING
      config_id::text,
      stream_id,
      rule_name,
      enabled,
      stale_days::text,
      conflict_predicate,
      severity,
      note,
      updated_by,
      updated_at::text
  `);
  return row as unknown as OntologyOpsRuleConfigRow;
}

export async function listOntologyOpsRuns(
  db: Queryable,
  input: {
    streamId?: string;
    limit: number;
  }
): Promise<OntologyOpsRuleRunRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      run_id::text,
      stream_id_filter,
      stale_days::text,
      conflict_predicate,
      dry_run,
      candidate_count::text,
      created_case_count::text,
      existing_case_count::text,
      created_alert_count::text,
      existing_alert_count::text,
      duration_ms::text,
      started_at::text,
      finished_at::text
    FROM ontology_ops_rule_run
    WHERE ${input.streamId ? sql.fragment`stream_id_filter = ${input.streamId}` : sql.fragment`TRUE`}
    ORDER BY started_at DESC
    LIMIT ${input.limit}
  `);

  return rows as unknown as OntologyOpsRuleRunRow[];
}

export async function getOntologyOpsRun(
  db: Queryable,
  runId: number
): Promise<OntologyOpsRuleRunRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      run_id::text,
      stream_id_filter,
      stale_days::text,
      conflict_predicate,
      dry_run,
      candidate_count::text,
      created_case_count::text,
      existing_case_count::text,
      created_alert_count::text,
      existing_alert_count::text,
      payload_json,
      duration_ms::text,
      started_at::text,
      finished_at::text
    FROM ontology_ops_rule_run
    WHERE run_id = ${runId}
    LIMIT 1
  `);

  return row ? (row as unknown as OntologyOpsRuleRunRow) : undefined;
}

export async function insertOntologyOpsRuleRun(
  db: Queryable,
  input: {
    streamIdFilter?: string;
    staleDays: number;
    conflictPredicate: string;
    dryRun: boolean;
    candidateCount: number;
    createdCaseCount: number;
    existingCaseCount: number;
    createdAlertCount: number;
    existingAlertCount: number;
    payloadJson: Record<string, unknown>;
    durationMs: number;
  }
): Promise<void> {
  await db.query(sql.typeAlias('void')`
    INSERT INTO ontology_ops_rule_run (
      stream_id_filter,
      stale_days,
      conflict_predicate,
      dry_run,
      candidate_count,
      created_case_count,
      existing_case_count,
      created_alert_count,
      existing_alert_count,
      payload_json,
      started_at,
      finished_at,
      duration_ms
    ) VALUES (
      ${input.streamIdFilter ?? null},
      ${input.staleDays},
      ${input.conflictPredicate},
      ${input.dryRun},
      ${input.candidateCount},
      ${input.createdCaseCount},
      ${input.existingCaseCount},
      ${input.createdAlertCount},
      ${input.existingAlertCount},
      ${JSON.stringify(input.payloadJson)}::jsonb,
      NOW(),
      NOW(),
      ${input.durationMs}
    )
  `);
}

export async function listStalePendingOntologyCandidates(
  db: Queryable,
  input: {
    streamId?: string;
    staleDays: number;
  }
): Promise<StalePendingCandidateRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      fe.stream_id,
      COUNT(DISTINCT f.fact_id)::text AS stale_fact_count,
      ARRAY_AGG(DISTINCT f.fact_id) AS fact_ids
    FROM ontology_fact f
    JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
    WHERE f.status IN ('candidate', 'needs_review')
      AND f.updated_at < (NOW() - make_interval(days => ${input.staleDays}::int))
      AND ${input.streamId ? sql.fragment`fe.stream_id = ${input.streamId}` : sql.fragment`TRUE`}
    GROUP BY fe.stream_id
    ORDER BY COUNT(DISTINCT f.fact_id) DESC, fe.stream_id ASC
  `);

  return rows as unknown as StalePendingCandidateRow[];
}

export async function listConflictPredicateOntologyCandidates(
  db: Queryable,
  input: {
    streamId?: string;
    predicate: string;
  }
): Promise<ConflictPredicateCandidateRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      fe.stream_id,
      f.src_concept_id,
      COUNT(DISTINCT f.dst_concept_id)::text AS dst_count,
      ARRAY_AGG(DISTINCT f.dst_concept_id) AS dst_values,
      COUNT(DISTINCT f.fact_id)::text AS fact_count,
      ARRAY_AGG(DISTINCT f.fact_id) AS fact_ids
    FROM ontology_fact f
    JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
    WHERE f.predicate = ${input.predicate}
      AND f.status IN ('accepted', 'candidate', 'needs_review')
      AND ${input.streamId ? sql.fragment`fe.stream_id = ${input.streamId}` : sql.fragment`TRUE`}
    GROUP BY fe.stream_id, f.src_concept_id
    HAVING COUNT(DISTINCT f.dst_concept_id) > 1
    ORDER BY COUNT(DISTINCT f.fact_id) DESC, fe.stream_id ASC, f.src_concept_id ASC
  `);

  return rows as unknown as ConflictPredicateCandidateRow[];
}

function decisionToFactStatus(decision: 'accept' | 'reject' | 'needs_work'): string {
  switch (decision) {
    case 'accept':
      return 'accepted';
    case 'reject':
      return 'rejected';
    default:
      return 'needs_review';
  }
}

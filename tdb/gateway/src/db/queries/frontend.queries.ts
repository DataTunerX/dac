import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';

import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export type BusinessObjectRow = {
  object_id: string;
  object_type: string;
  display_name: string;
  source_system: string | null;
  external_ref: string | null;
  status: string;
  health: 'healthy' | 'watch' | 'at_risk' | 'blocked';
  stage: string;
  owner: string;
  summary: string;
  current_state: Record<string, unknown>;
  key_facts: Array<Record<string, unknown>>;
  metrics: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
};

export type BusinessObjectLinkRow = {
  link_id: string;
  src_object_id: string;
  relation: string;
  dst_object_id: string;
  status: string;
  detail_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type BusinessExceptionRow = {
  exception_id: string;
  object_id: string | null;
  queue_context: string;
  code: string;
  title: string;
  severity: 'info' | 'low' | 'medium' | 'high' | 'critical';
  status: 'open' | 'acked' | 'resolved' | 'dismissed';
  summary: string;
  due_at: string | null;
  owner: string;
  recommended_action_json: Record<string, unknown>;
  evidence_json: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
};

export type BusinessRecommendationRow = {
  recommendation_id: string;
  object_id: string | null;
  page_type: string;
  queue_context: string;
  action_key: string;
  label: string;
  style: 'primary' | 'secondary' | 'danger' | 'ghost';
  reason: string;
  confidence: number | null;
  requires_confirmation: boolean;
  required_permissions: string[];
  args_hint: Record<string, unknown>;
  priority: number;
  status: 'active' | 'inactive';
  created_at: string;
  updated_at: string;
};

export type PageContextSnapshotRow = {
  context_snapshot_id: string;
  user_id: string;
  role: string;
  page_type: string;
  object_id: string | null;
  goal: string;
  queue_context: string;
  summary_json: Record<string, unknown>;
  current_state_json: Record<string, unknown>;
  key_facts_json: Array<Record<string, unknown>>;
  recent_changes_json: Array<Record<string, unknown>>;
  exceptions_json: Array<Record<string, unknown>>;
  recommended_actions_json: Array<Record<string, unknown>>;
  ui_blocks_json: Array<Record<string, unknown>>;
  evidence_json: Array<Record<string, unknown>>;
  created_at: string;
};

export async function upsertBusinessObject(
  db: Queryable,
  input: {
    objectId: string;
    objectType: string;
    displayName: string;
    sourceSystem?: string;
    externalRef?: string;
    status?: string;
    health?: 'healthy' | 'watch' | 'at_risk' | 'blocked';
    stage?: string;
    owner?: string;
    summary?: string;
    currentState?: Record<string, unknown>;
    keyFacts?: Array<Record<string, unknown>>;
    metrics?: Array<Record<string, unknown>>;
  }
): Promise<BusinessObjectRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO business_object (
      object_id,
      object_type,
      display_name,
      source_system,
      external_ref,
      status,
      health,
      stage,
      owner,
      summary,
      current_state,
      key_facts,
      metrics,
      updated_at
    ) VALUES (
      ${input.objectId},
      ${input.objectType},
      ${input.displayName},
      ${input.sourceSystem ?? null},
      ${input.externalRef ?? null},
      ${input.status ?? 'unknown'},
      ${input.health ?? 'healthy'},
      ${input.stage ?? ''},
      ${input.owner ?? ''},
      ${input.summary ?? ''},
      ${JSON.stringify(input.currentState ?? {})}::jsonb,
      ${JSON.stringify(input.keyFacts ?? [])}::jsonb,
      ${JSON.stringify(input.metrics ?? [])}::jsonb,
      NOW()
    )
    ON CONFLICT (object_id) DO UPDATE SET
      object_type = EXCLUDED.object_type,
      display_name = EXCLUDED.display_name,
      source_system = EXCLUDED.source_system,
      external_ref = EXCLUDED.external_ref,
      status = EXCLUDED.status,
      health = EXCLUDED.health,
      stage = EXCLUDED.stage,
      owner = EXCLUDED.owner,
      summary = EXCLUDED.summary,
      current_state = EXCLUDED.current_state,
      key_facts = EXCLUDED.key_facts,
      metrics = EXCLUDED.metrics,
      updated_at = NOW()
    RETURNING
      object_id,
      object_type,
      display_name,
      source_system,
      external_ref,
      status,
      health,
      stage,
      owner,
      summary,
      current_state,
      key_facts,
      metrics,
      created_at::text,
      updated_at::text
  `);

  return row as unknown as BusinessObjectRow;
}

export async function getBusinessObjectById(
  db: Queryable,
  objectId: string
): Promise<BusinessObjectRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      object_id,
      object_type,
      display_name,
      source_system,
      external_ref,
      status,
      health,
      stage,
      owner,
      summary,
      current_state,
      key_facts,
      metrics,
      created_at::text,
      updated_at::text
    FROM business_object
    WHERE object_id = ${objectId}
    LIMIT 1
  `);

  return row ? (row as unknown as BusinessObjectRow) : undefined;
}

export async function listBusinessObjectsByIds(
  db: Queryable,
  objectIds: string[]
): Promise<BusinessObjectRow[]> {
  if (objectIds.length === 0) {
    return [];
  }

  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      object_id,
      object_type,
      display_name,
      source_system,
      external_ref,
      status,
      health,
      stage,
      owner,
      summary,
      current_state,
      key_facts,
      metrics,
      created_at::text,
      updated_at::text
    FROM business_object
    WHERE object_id = ANY(${sql.array(objectIds, 'text')})
  `);

  return rows as unknown as BusinessObjectRow[];
}

export async function upsertBusinessObjectLink(
  db: Queryable,
  input: {
    linkId?: string;
    srcObjectId: string;
    relation: string;
    dstObjectId: string;
    status?: string;
    detailJson?: Record<string, unknown>;
  }
): Promise<BusinessObjectLinkRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO business_object_link (
      link_id,
      src_object_id,
      relation,
      dst_object_id,
      status,
      detail_json,
      updated_at
    ) VALUES (
      COALESCE(${input.linkId ?? null}, gen_random_uuid()::text),
      ${input.srcObjectId},
      ${input.relation},
      ${input.dstObjectId},
      ${input.status ?? ''},
      ${JSON.stringify(input.detailJson ?? {})}::jsonb,
      NOW()
    )
    ON CONFLICT (src_object_id, relation, dst_object_id) DO UPDATE SET
      status = EXCLUDED.status,
      detail_json = EXCLUDED.detail_json,
      updated_at = NOW()
    RETURNING
      link_id,
      src_object_id,
      relation,
      dst_object_id,
      status,
      detail_json,
      created_at::text,
      updated_at::text
  `);

  return row as unknown as BusinessObjectLinkRow;
}

export async function listBusinessObjectLinks(
  db: Queryable,
  objectId: string
): Promise<BusinessObjectLinkRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      link_id,
      src_object_id,
      relation,
      dst_object_id,
      status,
      detail_json,
      created_at::text,
      updated_at::text
    FROM business_object_link
    WHERE src_object_id = ${objectId}
    ORDER BY relation ASC, dst_object_id ASC
  `);

  return rows as unknown as BusinessObjectLinkRow[];
}

export async function upsertBusinessException(
  db: Queryable,
  input: {
    exceptionId?: string;
    objectId?: string;
    queueContext?: string;
    code: string;
    title: string;
    severity: 'info' | 'low' | 'medium' | 'high' | 'critical';
    status?: 'open' | 'acked' | 'resolved' | 'dismissed';
    summary?: string;
    dueAt?: string;
    owner?: string;
    recommendedActionJson?: Record<string, unknown>;
    evidenceJson?: Array<Record<string, unknown>>;
  }
): Promise<BusinessExceptionRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO business_exception (
      exception_id,
      object_id,
      queue_context,
      code,
      title,
      severity,
      status,
      summary,
      due_at,
      owner,
      recommended_action_json,
      evidence_json,
      updated_at
    ) VALUES (
      COALESCE(${input.exceptionId ?? null}, gen_random_uuid()::text),
      ${input.objectId ?? null},
      ${input.queueContext ?? ''},
      ${input.code},
      ${input.title},
      ${input.severity},
      ${input.status ?? 'open'},
      ${input.summary ?? ''},
      ${input.dueAt ?? null}::timestamptz,
      ${input.owner ?? ''},
      ${JSON.stringify(input.recommendedActionJson ?? {})}::jsonb,
      ${JSON.stringify(input.evidenceJson ?? [])}::jsonb,
      NOW()
    )
    ON CONFLICT (exception_id) DO UPDATE SET
      object_id = EXCLUDED.object_id,
      queue_context = EXCLUDED.queue_context,
      code = EXCLUDED.code,
      title = EXCLUDED.title,
      severity = EXCLUDED.severity,
      status = EXCLUDED.status,
      summary = EXCLUDED.summary,
      due_at = EXCLUDED.due_at,
      owner = EXCLUDED.owner,
      recommended_action_json = EXCLUDED.recommended_action_json,
      evidence_json = EXCLUDED.evidence_json,
      updated_at = NOW()
    RETURNING
      exception_id,
      object_id,
      queue_context,
      code,
      title,
      severity,
      status,
      summary,
      due_at::text,
      owner,
      recommended_action_json,
      evidence_json,
      created_at::text,
      updated_at::text
  `);

  return row as unknown as BusinessExceptionRow;
}

export async function listBusinessExceptions(
  db: Queryable,
  input: {
    objectId?: string;
    queueContext?: string;
    status?: 'open' | 'acked' | 'resolved' | 'dismissed' | 'all';
    limit: number;
  }
): Promise<BusinessExceptionRow[]> {
  const predicates = [sql.fragment`1 = 1`];
  if (input.objectId) {
    predicates.push(sql.fragment`object_id = ${input.objectId}`);
  }
  if (input.queueContext) {
    predicates.push(sql.fragment`queue_context = ${input.queueContext}`);
  }
  if (input.status && input.status !== 'all') {
    predicates.push(sql.fragment`status = ${input.status}`);
  }

  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      exception_id,
      object_id,
      queue_context,
      code,
      title,
      severity,
      status,
      summary,
      due_at::text,
      owner,
      recommended_action_json,
      evidence_json,
      created_at::text,
      updated_at::text
    FROM business_exception
    WHERE ${sql.join(predicates, sql.fragment` AND `)}
    ORDER BY
      CASE severity
        WHEN 'critical' THEN 5
        WHEN 'high' THEN 4
        WHEN 'medium' THEN 3
        WHEN 'low' THEN 2
        ELSE 1
      END DESC,
      due_at ASC NULLS LAST,
      updated_at DESC
    LIMIT ${input.limit}
  `);

  return rows as unknown as BusinessExceptionRow[];
}

export async function upsertBusinessRecommendation(
  db: Queryable,
  input: {
    recommendationId?: string;
    objectId?: string;
    pageType?: string;
    queueContext?: string;
    actionKey: string;
    label: string;
    style?: 'primary' | 'secondary' | 'danger' | 'ghost';
    reason?: string;
    confidence?: number;
    requiresConfirmation?: boolean;
    requiredPermissions?: string[];
    argsHint?: Record<string, unknown>;
    priority?: number;
    status?: 'active' | 'inactive';
  }
): Promise<BusinessRecommendationRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO business_recommendation (
      recommendation_id,
      object_id,
      page_type,
      queue_context,
      action_key,
      label,
      style,
      reason,
      confidence,
      requires_confirmation,
      required_permissions,
      args_hint,
      priority,
      status,
      updated_at
    ) VALUES (
      COALESCE(${input.recommendationId ?? null}, gen_random_uuid()::text),
      ${input.objectId ?? null},
      ${input.pageType ?? ''},
      ${input.queueContext ?? ''},
      ${input.actionKey},
      ${input.label},
      ${input.style ?? 'secondary'},
      ${input.reason ?? ''},
      ${input.confidence ?? null},
      ${input.requiresConfirmation ?? false},
      ${JSON.stringify(input.requiredPermissions ?? [])}::jsonb,
      ${JSON.stringify(input.argsHint ?? {})}::jsonb,
      ${input.priority ?? 50},
      ${input.status ?? 'active'},
      NOW()
    )
    ON CONFLICT (recommendation_id) DO UPDATE SET
      object_id = EXCLUDED.object_id,
      page_type = EXCLUDED.page_type,
      queue_context = EXCLUDED.queue_context,
      action_key = EXCLUDED.action_key,
      label = EXCLUDED.label,
      style = EXCLUDED.style,
      reason = EXCLUDED.reason,
      confidence = EXCLUDED.confidence,
      requires_confirmation = EXCLUDED.requires_confirmation,
      required_permissions = EXCLUDED.required_permissions,
      args_hint = EXCLUDED.args_hint,
      priority = EXCLUDED.priority,
      status = EXCLUDED.status,
      updated_at = NOW()
    RETURNING
      recommendation_id,
      object_id,
      page_type,
      queue_context,
      action_key,
      label,
      style,
      reason,
      confidence,
      requires_confirmation,
      required_permissions,
      args_hint,
      priority,
      status,
      created_at::text,
      updated_at::text
  `);

  return row as unknown as BusinessRecommendationRow;
}

export async function listBusinessRecommendations(
  db: Queryable,
  input: {
    objectId?: string;
    pageType?: string;
    queueContext?: string;
    status?: 'active' | 'inactive' | 'all';
    limit: number;
  }
): Promise<BusinessRecommendationRow[]> {
  const predicates = [sql.fragment`1 = 1`];
  if (input.objectId) {
    predicates.push(sql.fragment`object_id = ${input.objectId}`);
  }
  if (input.pageType) {
    predicates.push(sql.fragment`page_type = ${input.pageType}`);
  }
  if (input.queueContext) {
    predicates.push(sql.fragment`queue_context = ${input.queueContext}`);
  }
  if (input.status && input.status !== 'all') {
    predicates.push(sql.fragment`status = ${input.status}`);
  }

  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      recommendation_id,
      object_id,
      page_type,
      queue_context,
      action_key,
      label,
      style,
      reason,
      confidence,
      requires_confirmation,
      required_permissions,
      args_hint,
      priority,
      status,
      created_at::text,
      updated_at::text
    FROM business_recommendation
    WHERE ${sql.join(predicates, sql.fragment` AND `)}
    ORDER BY priority DESC, updated_at DESC
    LIMIT ${input.limit}
  `);

  return rows as unknown as BusinessRecommendationRow[];
}

export async function insertPageContextSnapshot(
  db: Queryable,
  input: {
    contextSnapshotId?: string;
    userId: string;
    role: string;
    pageType: string;
    objectId?: string;
    goal?: string;
    queueContext?: string;
    summaryJson?: Record<string, unknown>;
    currentStateJson?: Record<string, unknown>;
    keyFactsJson?: Array<Record<string, unknown>>;
    recentChangesJson?: Array<Record<string, unknown>>;
    exceptionsJson?: Array<Record<string, unknown>>;
    recommendedActionsJson?: Array<Record<string, unknown>>;
    uiBlocksJson?: Array<Record<string, unknown>>;
    evidenceJson?: Array<Record<string, unknown>>;
  }
): Promise<PageContextSnapshotRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO page_context_snapshot (
      context_snapshot_id,
      user_id,
      role,
      page_type,
      object_id,
      goal,
      queue_context,
      summary_json,
      current_state_json,
      key_facts_json,
      recent_changes_json,
      exceptions_json,
      recommended_actions_json,
      ui_blocks_json,
      evidence_json
    ) VALUES (
      COALESCE(${input.contextSnapshotId ?? null}, gen_random_uuid()::text),
      ${input.userId},
      ${input.role},
      ${input.pageType},
      ${input.objectId ?? null},
      ${input.goal ?? ''},
      ${input.queueContext ?? ''},
      ${JSON.stringify(input.summaryJson ?? {})}::jsonb,
      ${JSON.stringify(input.currentStateJson ?? {})}::jsonb,
      ${JSON.stringify(input.keyFactsJson ?? [])}::jsonb,
      ${JSON.stringify(input.recentChangesJson ?? [])}::jsonb,
      ${JSON.stringify(input.exceptionsJson ?? [])}::jsonb,
      ${JSON.stringify(input.recommendedActionsJson ?? [])}::jsonb,
      ${JSON.stringify(input.uiBlocksJson ?? [])}::jsonb,
      ${JSON.stringify(input.evidenceJson ?? [])}::jsonb
    )
    RETURNING
      context_snapshot_id,
      user_id,
      role,
      page_type,
      object_id,
      goal,
      queue_context,
      summary_json,
      current_state_json,
      key_facts_json,
      recent_changes_json,
      exceptions_json,
      recommended_actions_json,
      ui_blocks_json,
      evidence_json,
      created_at::text
  `);

  return row as unknown as PageContextSnapshotRow;
}

export async function getLatestPageContextSnapshot(
  db: Queryable,
  input: {
    userId: string;
    role: string;
    pageType: string;
    objectId?: string;
    queueContext?: string;
  }
): Promise<PageContextSnapshotRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      context_snapshot_id,
      user_id,
      role,
      page_type,
      object_id,
      goal,
      queue_context,
      summary_json,
      current_state_json,
      key_facts_json,
      recent_changes_json,
      exceptions_json,
      recommended_actions_json,
      ui_blocks_json,
      evidence_json,
      created_at::text
    FROM page_context_snapshot
    WHERE user_id = ${input.userId}
      AND role = ${input.role}
      AND page_type = ${input.pageType}
      AND object_id IS NOT DISTINCT FROM ${input.objectId ?? null}
      AND queue_context = ${input.queueContext ?? ''}
    ORDER BY created_at DESC, context_snapshot_id DESC
    LIMIT 1
  `);

  return row ? (row as unknown as PageContextSnapshotRow) : undefined;
}

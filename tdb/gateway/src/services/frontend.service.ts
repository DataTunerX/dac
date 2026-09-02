import type { DatabasePool } from 'slonik';
import type { Static } from '@sinclair/typebox';

import {
  getBusinessObjectById,
  getLatestPageContextSnapshot,
  listBusinessExceptions,
  listBusinessObjectLinks,
  listBusinessObjectsByIds,
  listBusinessRecommendations,
  type BusinessExceptionRow,
  type BusinessObjectRow,
  type BusinessRecommendationRow,
  type PageContextSnapshotRow
} from '../db/queries/frontend.queries.js';
import { TdbError } from '../errors/tdb_error.js';
import {
  ActionProposeRequestSchema,
  ActionProposeResponseSchema,
  ActionSimulateRequestSchema,
  ActionSimulateResponseSchema,
  ContextPackResponseSchema,
  ContextPackRequestSchema,
  DecisionBriefRequestSchema,
  DecisionBriefResponseSchema,
  ExceptionFeedRequestSchema,
  ExceptionFeedResponseSchema,
  Object360ResponseSchema,
  Object360RequestSchema
} from '../schema/v2/frontend.js';

export type ContextPackRequest = Static<typeof ContextPackRequestSchema>;
export type Object360Request = Static<typeof Object360RequestSchema>;
export type DecisionBriefRequest = Static<typeof DecisionBriefRequestSchema>;
export type ExceptionFeedRequest = Static<typeof ExceptionFeedRequestSchema>;
export type ActionProposeRequest = Static<typeof ActionProposeRequestSchema>;
export type ActionSimulateRequest = Static<typeof ActionSimulateRequestSchema>;
export type ContextPackResponse = Static<typeof ContextPackResponseSchema>;
export type Object360Response = Static<typeof Object360ResponseSchema>;
export type DecisionBriefResponse = Static<typeof DecisionBriefResponseSchema>;
export type ExceptionFeedResponse = Static<typeof ExceptionFeedResponseSchema>;
export type ActionProposeResponse = Static<typeof ActionProposeResponseSchema>;
export type ActionSimulateResponse = Static<typeof ActionSimulateResponseSchema>;

export class FrontendService {
  constructor(private readonly db: DatabasePool) {}

  async contextPack(request: ContextPackRequest): Promise<ContextPackResponse> {
    const objectId = request.object_ref?.object_id;
    const queueContext = request.queue_context?.trim() ?? '';
    const object = objectId ? await this.requireObject(objectId) : undefined;

    const snapshot = await getLatestPageContextSnapshot(this.db, {
      userId: request.user_id,
      role: request.role,
      pageType: request.page_type,
      objectId,
      queueContext
    });

    const liveExceptions = await listBusinessExceptions(this.db, {
      objectId,
      queueContext: objectId ? undefined : queueContext || undefined,
      status: 'open',
      limit: 20
    });
    const liveRecommendations = await listBusinessRecommendations(this.db, {
      objectId,
      pageType: request.page_type,
      queueContext: objectId ? undefined : queueContext || undefined,
      status: 'active',
      limit: 10
    });

    const summary = buildContextSummary(snapshot, object, liveExceptions, liveRecommendations, request.page_type);
    const keyFacts = coerceArray(snapshot?.key_facts_json, object?.key_facts ?? []);
    const recentChanges = coerceArray(
      snapshot?.recent_changes_json,
      readArrayField(object?.current_state, 'timeline')
    );
    const exceptions = coerceArray(
      snapshot?.exceptions_json,
      liveExceptions.map(mapBusinessException)
    );
    const recommendedActions = coerceArray(
      snapshot?.recommended_actions_json,
      liveRecommendations.map(mapBusinessRecommendation)
    );
    const evidence = coerceArray(
      snapshot?.evidence_json,
      collectEvidenceFromExceptions(liveExceptions)
    );
    const currentState = coerceRecord(snapshot?.current_state_json, object?.current_state ?? {});
    const uiBlocks = coerceArray(
      snapshot?.ui_blocks_json,
      buildContextUiBlocks({
        summary,
        object,
        exceptions,
        recommendedActions
      })
    );

    return {
      contract_version: 'business_frontend_v1',
      generated_at: latestTimestamp(snapshot?.created_at, object?.updated_at),
      page_type: request.page_type,
      object_ref: request.object_ref ?? (object ? mapBusinessObjectRef(object) : undefined),
      summary,
      current_state: currentState,
      key_facts: keyFacts,
      recent_changes: recentChanges,
      exceptions,
      recommended_actions: recommendedActions,
      ui_blocks: uiBlocks,
      evidence
    } as ContextPackResponse;
  }

  async object360(request: Object360Request): Promise<Object360Response> {
    const object = await this.requireObject(request.object_ref.object_id);
    const snapshot =
      request.user_id && request.role
        ? await getLatestPageContextSnapshot(this.db, {
            userId: request.user_id,
            role: request.role,
            pageType: 'object_360',
            objectId: object.object_id,
            queueContext: ''
          })
        : undefined;

    const links = await listBusinessObjectLinks(this.db, object.object_id);
    const linkedObjects = await listBusinessObjectsByIds(
      this.db,
      links.map((link) => link.dst_object_id)
    );
    const linkedObjectMap = new Map(linkedObjects.map((item) => [item.object_id, item]));
    const exceptions = await listBusinessExceptions(this.db, {
      objectId: object.object_id,
      status: 'open',
      limit: 20
    });
    const recommendations = await listBusinessRecommendations(this.db, {
      objectId: object.object_id,
      pageType: 'object_360',
      status: 'active',
      limit: 10
    });

    const summary = buildObjectSummary(snapshot, object, exceptions, recommendations);
    const timeline = coerceArray(
      snapshot?.recent_changes_json,
      readArrayField(object.current_state, 'timeline')
    );
    const artifacts = readArrayField(object.current_state, 'artifacts');
    const decisions = readArrayField(object.current_state, 'decisions');
    const evidence = coerceArray(
      snapshot?.evidence_json,
      collectEvidenceFromExceptions(exceptions)
    );

    return {
      contract_version: 'business_frontend_v1',
      generated_at: latestTimestamp(snapshot?.created_at, object.updated_at),
      object: {
        ref: mapBusinessObjectRef(object),
        status: object.status,
        health: object.health,
        stage: emptyToUndefined(object.stage),
        owner: emptyToUndefined(object.owner),
        freshness: new Date(object.updated_at).toISOString()
      },
      summary,
      key_facts: object.key_facts ?? [],
      metrics: object.metrics ?? [],
      linked_objects: links.map((link) => ({
        relation: link.relation,
        object: linkedObjectMap.has(link.dst_object_id)
          ? mapBusinessObjectRef(linkedObjectMap.get(link.dst_object_id)!)
          : {
              object_id: link.dst_object_id,
              object_type: 'unknown',
              display_name: link.dst_object_id
            },
        status: emptyToUndefined(link.status)
      })),
      timeline,
      artifacts,
      decisions,
      exceptions: exceptions.map(mapBusinessException),
      recommended_actions: recommendations.map(mapBusinessRecommendation),
      ui_blocks: coerceArray(
        snapshot?.ui_blocks_json,
        buildObjectUiBlocks({
          summary,
          object,
          exceptions: exceptions.map(mapBusinessException),
          recommendations: recommendations.map(mapBusinessRecommendation)
        })
      ),
      evidence
    } as Object360Response;
  }

  async exceptionFeed(request: ExceptionFeedRequest): Promise<ExceptionFeedResponse> {
    const queueContext = request.queue_context?.trim() ?? '';
    const exceptions = await listBusinessExceptions(this.db, {
      queueContext: queueContext || undefined,
      status: 'open',
      limit: request.limit ?? 50
    });
    const explicitRecommendations = await listBusinessRecommendations(this.db, {
      queueContext: queueContext || undefined,
      status: 'active',
      limit: 20
    });

    const items = exceptions.map(mapBusinessException);
    const recommendedActions = rankExceptionFeedActions(explicitRecommendations, exceptions);

    return {
      contract_version: 'business_frontend_v1',
      generated_at: latestTimestamp(
        ...exceptions.map((item) => item.updated_at),
        ...explicitRecommendations.map((item) => item.updated_at)
      ),
      summary: buildExceptionFeedSummary(queueContext, exceptions, recommendedActions),
      total_open: exceptions.length,
      items,
      recommended_actions: recommendedActions
    } as ExceptionFeedResponse;
  }

  async decisionBrief(request: DecisionBriefRequest): Promise<DecisionBriefResponse> {
    const object = request.object_ref?.object_id
      ? await this.requireObject(request.object_ref.object_id)
      : undefined;
    const snapshot = object
      ? await getLatestPageContextSnapshot(this.db, {
          userId: request.user_id,
          role: request.role,
          pageType: 'approval_review',
          objectId: object.object_id,
          queueContext: ''
        })
      : undefined;
    const exceptions = object
      ? await listBusinessExceptions(this.db, {
          objectId: object.object_id,
          status: 'open',
          limit: 20
        })
      : [];
    const recommendationRows = object
      ? await listBusinessRecommendations(this.db, {
          objectId: object.object_id,
          pageType: 'approval_review',
          status: 'active',
          limit: 10
        })
      : [];
    const recommendations = filterDecisionRecommendations(recommendationRows, request.candidate_actions);
    const missingPrerequisites = extractDecisionMissingPrerequisites(snapshot, object, exceptions);
    const impactPreview = extractDecisionImpactPreview(snapshot, object);
    const evidence = coerceArray(
      snapshot?.evidence_json,
      collectDecisionEvidence(object, exceptions)
    );
    const decision = buildDecisionRecommendation(
      request.approval_ref,
      object,
      recommendations,
      exceptions,
      missingPrerequisites
    );
    const summary = buildDecisionSummary(
      snapshot,
      request.approval_ref,
      object,
      decision,
      exceptions,
      missingPrerequisites,
      evidence
    );
    const uiBlocks = coerceArray(
      snapshot?.ui_blocks_json,
      buildDecisionUiBlocks({
        summary,
        decision,
        missingPrerequisites,
        impactPreview,
        evidence,
        exceptions: exceptions.map(mapBusinessException),
        recommendations: recommendations.map(mapBusinessRecommendation)
      })
    );

    return {
      contract_version: 'business_frontend_v1',
      generated_at: latestTimestamp(
        snapshot?.created_at,
        object?.updated_at,
        ...exceptions.map((item) => item.updated_at),
        ...recommendationRows.map((item) => item.updated_at)
      ),
      summary,
      recommendation: decision,
      missing_prerequisites: missingPrerequisites,
      impact_preview: impactPreview,
      evidence,
      ui_blocks: uiBlocks
    } as DecisionBriefResponse;
  }

  async actionPropose(request: ActionProposeRequest): Promise<ActionProposeResponse> {
    const object = request.object_ref?.object_id
      ? await this.requireObject(request.object_ref.object_id)
      : undefined;
    const snapshot = await getLatestPageContextSnapshot(this.db, {
      userId: request.user_id,
      role: request.role,
      pageType: request.page_type,
      objectId: object?.object_id,
      queueContext: ''
    });
    const exceptions = object
      ? await listBusinessExceptions(this.db, {
          objectId: object.object_id,
          status: 'open',
          limit: 20
        })
      : [];
    const recommendationRows = await listBusinessRecommendations(this.db, {
      objectId: object?.object_id,
      pageType: request.page_type,
      status: 'active',
      limit: 20
    });
    const proposedActions = buildActionProposals(request, object, recommendationRows, exceptions);
    const missingInputs = extractActionMissingInputs(
      snapshot,
      object,
      proposedActions,
      request.draft_args ?? {}
    );
    const constraints = extractActionConstraints(snapshot, object, proposedActions);
    const evidence = coerceArray(
      snapshot?.evidence_json,
      collectActionEvidence(object, exceptions)
    );
    const summary = buildActionProposeSummary(object, request.intent, proposedActions, missingInputs, constraints);
    const uiBlocks = buildActionProposalUiBlocks({
      proposedActions,
      summary,
      evidence
    });

    return {
      contract_version: 'business_frontend_v1',
      generated_at: latestTimestamp(
        snapshot?.created_at,
        object?.updated_at,
        ...recommendationRows.map((item) => item.updated_at),
        ...exceptions.map((item) => item.updated_at)
      ),
      summary,
      proposed_actions: proposedActions,
      missing_inputs: missingInputs,
      constraints,
      evidence,
      ui_blocks: uiBlocks
    } as ActionProposeResponse;
  }

  async actionSimulate(request: ActionSimulateRequest): Promise<ActionSimulateResponse> {
    const object = request.object_ref?.object_id
      ? await this.requireObject(request.object_ref.object_id)
      : undefined;
    const snapshot =
      request.page_type || object
        ? await getLatestPageContextSnapshot(this.db, {
            userId: request.user_id,
            role: request.role,
            pageType: request.page_type ?? 'object_360',
            objectId: object?.object_id,
            queueContext: ''
          })
        : undefined;
    const linkedObjects = object
      ? await resolveLinkedBusinessObjects(this.db, object.object_id)
      : [];
    const recommendationRows = await listBusinessRecommendations(this.db, {
      objectId: object?.object_id,
      pageType: request.page_type,
      status: 'active',
      limit: 20
    });
    const fallbackRecommendations =
      recommendationRows.length === 0 && object
        ? await listBusinessRecommendations(this.db, {
            objectId: object.object_id,
            status: 'active',
            limit: 20
          })
        : recommendationRows;
    const selectedAction = findSelectedAction(
      request.action_key,
      fallbackRecommendations,
      object
    );
    const blockers = extractSimulationBlockers(snapshot, object, selectedAction, request.args ?? {});
    const changes = extractSimulationChanges(snapshot, object, selectedAction, request.args ?? {}, linkedObjects);
    const followUpActions = extractSimulationFollowUps(
      object,
      selectedAction,
      fallbackRecommendations,
      request.page_type
    );
    const affectedObjects = extractAffectedObjects(object, linkedObjects, changes);
    const evidence = extractSimulationEvidence(snapshot, object, selectedAction);
    const simulationStatus = blockers.length > 0 ? 'blocked' : selectedAction.requires_confirmation ? 'needs_confirmation' : 'ready';
    const summary = buildActionSimulateSummary(object, selectedAction, simulationStatus, blockers, changes);
    const uiBlocks = buildActionSimulationUiBlocks({
      summary,
      selectedAction,
      changes,
      blockers
    });

    return {
      contract_version: 'business_frontend_v1',
      generated_at: latestTimestamp(
        snapshot?.created_at,
        object?.updated_at,
        ...fallbackRecommendations.map((item) => item.updated_at)
      ),
      summary,
      simulation_status: simulationStatus,
      selected_action: selectedAction,
      affected_objects: affectedObjects,
      changes,
      follow_up_actions: followUpActions,
      blockers,
      evidence,
      ui_blocks: uiBlocks
    } as ActionSimulateResponse;
  }

  private async requireObject(objectId: string): Promise<BusinessObjectRow> {
    const object = await getBusinessObjectById(this.db, objectId);
    if (!object) {
      throw new TdbError('BUSINESS_OBJECT_NOT_FOUND', 404, `business object not found: ${objectId}`);
    }
    return object;
  }
}

function buildContextSummary(
  snapshot: PageContextSnapshotRow | undefined,
  object: BusinessObjectRow | undefined,
  exceptions: BusinessExceptionRow[],
  recommendations: BusinessRecommendationRow[],
  pageType: string
): Record<string, unknown> {
  if (snapshot?.summary_json && Object.keys(snapshot.summary_json).length > 0) {
    return coerceRecord(snapshot.summary_json, {});
  }

  if (object) {
    return {
      title: object.summary || `${object.display_name} is ${object.status}`,
      subtitle: emptyToUndefined(object.display_name),
      status: object.status,
      health: object.health,
      freshness: new Date(object.updated_at).toISOString(),
      why_it_matters:
        exceptions[0]?.summary ||
        recommendations[0]?.reason ||
        `This ${object.object_type} page is generated from the current semantic read model.`
    };
  }

  const openCount = exceptions.length;
  return {
    title:
      openCount > 0
        ? `${openCount} open item${openCount === 1 ? '' : 's'} require attention`
        : `No open issues in ${pageType}`,
    status: openCount > 0 ? 'active' : 'clear',
    health: openCount > 0 ? 'watch' : 'healthy',
    freshness: new Date().toISOString(),
    why_it_matters: recommendations[0]?.reason ?? 'This page summarizes the current queue context.'
  };
}

function buildObjectSummary(
  snapshot: PageContextSnapshotRow | undefined,
  object: BusinessObjectRow,
  exceptions: BusinessExceptionRow[],
  recommendations: BusinessRecommendationRow[]
): Record<string, unknown> {
  if (snapshot?.summary_json && Object.keys(snapshot.summary_json).length > 0) {
    return coerceRecord(snapshot.summary_json, {});
  }

  return {
    title: object.summary || `${object.display_name} is ${object.status}`,
    subtitle: object.display_name,
    status: object.status,
    health: object.health,
    freshness: new Date(object.updated_at).toISOString(),
    why_it_matters:
      exceptions[0]?.summary ||
      recommendations[0]?.reason ||
      `${object.display_name} is being served from the business object semantic view.`
  };
}

function buildExceptionFeedSummary(
  queueContext: string,
  exceptions: BusinessExceptionRow[],
  recommendedActions: Array<Record<string, unknown>>
): Record<string, unknown> {
  const criticalCount = exceptions.filter((item) => item.severity === 'critical').length;
  const highCount = exceptions.filter((item) => item.severity === 'high').length;
  const title =
    exceptions.length === 0
      ? queueContext
        ? `No open issues in ${queueContext}`
        : 'No open issues in the current queue'
      : criticalCount > 0
        ? `${criticalCount} critical item${criticalCount === 1 ? '' : 's'} need immediate attention`
        : highCount > 0
          ? `${highCount} high-priority item${highCount === 1 ? '' : 's'} need attention`
          : `${exceptions.length} open item${exceptions.length === 1 ? '' : 's'} require triage`;

  return {
    title,
    status: exceptions.length > 0 ? 'active' : 'clear',
    health:
      criticalCount > 0 ? 'blocked' : highCount > 0 ? 'at_risk' : exceptions.length > 0 ? 'watch' : 'healthy',
    freshness: latestTimestamp(...exceptions.map((item) => item.updated_at)),
    why_it_matters:
      recommendedActions[0]?.reason ??
      (queueContext
        ? `This feed is prioritized for ${queueContext}.`
        : 'This feed summarizes the current open exception queue.')
  };
}

function buildDecisionSummary(
  snapshot: PageContextSnapshotRow | undefined,
  approvalRef: string,
  object: BusinessObjectRow | undefined,
  recommendation: Record<string, unknown>,
  exceptions: BusinessExceptionRow[],
  missingPrerequisites: Array<Record<string, unknown>>,
  evidence: Array<Record<string, unknown>>
): Record<string, unknown> {
  if (snapshot?.summary_json && Object.keys(snapshot.summary_json).length > 0) {
    return coerceRecord(snapshot.summary_json, {});
  }

  const disposition = String(recommendation.disposition ?? 'investigate_more');
  const objectName = object?.display_name ?? approvalRef;
  const blockingMissing = missingPrerequisites.filter(isBlockingPrerequisite);
  const highestSeverity = highestExceptionSeverity(exceptions);

  const title =
    disposition === 'approve'
      ? blockingMissing.length > 0
        ? `Approve ${objectName} after resolving ${blockingMissing.length} blocking item${blockingMissing.length === 1 ? '' : 's'}`
        : `Approve ${objectName}${missingPrerequisites.length > 0 ? ' with follow-up control' : ''}`
      : disposition === 'reject'
        ? `Reject ${objectName} until policy issues are resolved`
        : disposition === 'request_info'
          ? `Request more information for ${objectName}`
          : `Investigate ${objectName} before approval`;

  return {
    title,
    subtitle: object ? `Approval ${approvalRef}` : approvalRef,
    status: decisionStatus(disposition),
    health: decisionHealth(disposition, highestSeverity),
    confidence: recommendation.confidence,
    freshness: latestTimestamp(object?.updated_at, ...exceptions.map((item) => item.updated_at)),
    why_it_matters:
      recommendation.reason ??
      (blockingMissing.length > 0
        ? `${blockingMissing.length} blocking prerequisite${blockingMissing.length === 1 ? '' : 's'} still need resolution.`
        : highestSeverity === 'critical'
          ? 'Critical issues remain open and need review before approval.'
          : evidence.length > 0
            ? 'Supporting evidence is present for a decision-ready review.'
            : 'This brief is assembled from the semantic business object model.')
  };
}

function buildActionProposeSummary(
  object: BusinessObjectRow | undefined,
  intent: string,
  proposedActions: Array<Record<string, unknown>>,
  missingInputs: Array<Record<string, unknown>>,
  constraints: string[]
): Record<string, unknown> {
  const title =
    proposedActions.length > 0
      ? `${proposedActions.length} valid action${proposedActions.length === 1 ? '' : 's'} are available for ${object?.display_name ?? 'this workflow'}`
      : `No strong action proposal is available for ${object?.display_name ?? 'this workflow'}`;

  return {
    title,
    subtitle: intent,
    status: proposedActions.length > 0 ? 'actionable' : 'needs_review',
    health: missingInputs.length > 0 || constraints.length > 0 ? 'watch' : object?.health ?? 'healthy',
    confidence: Number(proposedActions[0]?.confidence ?? (proposedActions.length > 0 ? 0.72 : 0.45)),
    freshness: latestTimestamp(object?.updated_at),
    why_it_matters:
      String(
        proposedActions[0]?.reason ??
          (missingInputs.length > 0
            ? 'Some action prerequisites are still missing.'
            : 'These actions reflect the highest-signal options in the current page context.')
      )
  };
}

function buildActionSimulateSummary(
  object: BusinessObjectRow | undefined,
  selectedAction: Record<string, unknown>,
  simulationStatus: 'ready' | 'needs_confirmation' | 'blocked',
  blockers: Array<Record<string, unknown>>,
  changes: Array<Record<string, unknown>>
): Record<string, unknown> {
  const actionLabel = String(selectedAction.label ?? selectedAction.action_key ?? 'Selected action');
  const statusTitle =
    simulationStatus === 'blocked'
      ? `${actionLabel} is blocked until required inputs are resolved`
      : simulationStatus === 'needs_confirmation'
        ? `${actionLabel} is ready but requires confirmation`
        : `${actionLabel} is ready to run`;

  return {
    title: statusTitle,
    subtitle: object?.display_name,
    status: simulationStatus,
    health:
      simulationStatus === 'blocked' ? 'blocked' : simulationStatus === 'needs_confirmation' ? 'watch' : 'healthy',
    confidence: Number(selectedAction.confidence ?? (simulationStatus === 'ready' ? 0.8 : 0.74)),
    freshness: latestTimestamp(object?.updated_at),
    why_it_matters:
      String(
        selectedAction.reason ??
          (blockers.length > 0
            ? `${blockers.length} blocker${blockers.length === 1 ? '' : 's'} need resolution before execution.`
            : changes.length > 0
              ? 'This simulation shows the expected object-level impact before execution.'
              : 'This simulation previews the likely effect of the selected action.')
      )
  };
}

function buildContextUiBlocks(input: {
  summary: Record<string, unknown>;
  object: BusinessObjectRow | undefined;
  exceptions: Array<Record<string, unknown>>;
  recommendedActions: Array<Record<string, unknown>>;
}): Array<Record<string, unknown>> {
  const blocks: Array<Record<string, unknown>> = [
    {
      block_id: 'summary-auto',
      type: 'summary_block',
      title: 'Summary',
      priority: 90,
      summary: String(input.summary.title ?? 'Page Summary')
    }
  ];

  if (input.object) {
    blocks.push({
      block_id: 'status-auto',
      type: 'status_strip',
      title: 'Status',
      priority: 85,
      items: [
        {
          key: 'status',
          label: 'Status',
          value: input.object.status
        },
        {
          key: 'health',
          label: 'Health',
          value: input.object.health,
          severity: severityFromHealth(input.object.health)
        }
      ]
    });
  }

  if (input.recommendedActions.length > 0) {
    blocks.push({
      block_id: 'recommendation-auto',
      type: 'recommendation_block',
      title: 'Recommended Action',
      priority: 95,
      summary: String(input.recommendedActions[0].reason ?? input.recommendedActions[0].label ?? 'Recommended action'),
      recommended_action: input.recommendedActions[0]
    });
  }

  if (input.exceptions.length > 0) {
    blocks.push({
      block_id: 'exceptions-auto',
      type: 'exception_block',
      title: 'Open Exceptions',
      priority: 80,
      items: input.exceptions
    });
  }

  return blocks;
}

function buildObjectUiBlocks(input: {
  summary: Record<string, unknown>;
  object: BusinessObjectRow;
  exceptions: Array<Record<string, unknown>>;
  recommendations: Array<Record<string, unknown>>;
}): Array<Record<string, unknown>> {
  const blocks = buildContextUiBlocks({
    summary: input.summary,
    object: input.object,
    exceptions: input.exceptions,
    recommendedActions: input.recommendations
  });

  if ((input.object.metrics ?? []).length > 0) {
    blocks.push({
      block_id: 'metrics-auto',
      type: 'metric_strip',
      title: 'Metrics',
      priority: 75,
      items: input.object.metrics
    });
  }

  return blocks;
}

function buildDecisionUiBlocks(input: {
  summary: Record<string, unknown>;
  decision: Record<string, unknown>;
  missingPrerequisites: Array<Record<string, unknown>>;
  impactPreview: Array<Record<string, unknown>>;
  evidence: Array<Record<string, unknown>>;
  exceptions: Array<Record<string, unknown>>;
  recommendations: Array<Record<string, unknown>>;
}): Array<Record<string, unknown>> {
  const blocks: Array<Record<string, unknown>> = [
    {
      block_id: 'approval-brief-auto',
      type: 'approval_brief_block',
      title: 'Approval Brief',
      priority: 95,
      confidence: input.decision.confidence,
      recommendation: input.decision.disposition,
      summary: String(input.decision.reason ?? input.summary.title ?? 'Approval brief'),
      actions: input.recommendations.slice(0, 1),
      evidence_refs: input.evidence.slice(0, 3),
      ...(input.missingPrerequisites.length > 0
        ? { missing_prerequisites: input.missingPrerequisites }
        : {}),
      ...(input.impactPreview.length > 0 ? { impact_preview: input.impactPreview } : {})
    }
  ];

  if (input.exceptions.length > 0 || input.missingPrerequisites.length > 0) {
    blocks.push({
      block_id: 'approval-risks-auto',
      type: 'warning_block',
      title: 'Approval Risks',
      priority: 88,
      severity:
        input.exceptions.length > 0
          ? highestMappedExceptionSeverity(input.exceptions)
          : 'medium',
      summary: 'Review outstanding risks before finalizing the decision.',
      warning_items: [
        ...input.missingPrerequisites.map((item) => String(item.label ?? item.key ?? 'Missing prerequisite')),
        ...input.exceptions.slice(0, 3).map((item) => String(item.title ?? item.code ?? 'Open issue'))
      ]
    });
  }

  if (input.impactPreview.length > 0) {
    blocks.push({
      block_id: 'impact-preview-auto',
      type: 'impact_preview_block',
      title: 'Impact Preview',
      priority: 82,
      changes: input.impactPreview
    });
  }

  return blocks;
}

function buildActionProposalUiBlocks(input: {
  proposedActions: Array<Record<string, unknown>>;
  summary: Record<string, unknown>;
  evidence: Array<Record<string, unknown>>;
}): Array<Record<string, unknown>> {
  if (input.proposedActions.length === 0) {
    return [
      {
        block_id: 'action-propose-summary-auto',
        type: 'summary_block',
        title: 'Action Proposal',
        priority: 88,
        summary: String(input.summary.title ?? 'No strong next action available')
      }
    ];
  }

  return [
    {
      block_id: 'action-propose-rec-auto',
      type: 'recommendation_block',
      title: 'Best Next Action',
      priority: 93,
      summary: String(input.proposedActions[0].reason ?? input.proposedActions[0].label ?? 'Best next action'),
      recommended_action: input.proposedActions[0],
      evidence_refs: input.evidence.slice(0, 3),
      rationale: [
        'Ranked against the current intent and object state',
        'Filtered through active business recommendations'
      ]
    }
  ];
}

function buildActionSimulationUiBlocks(input: {
  summary: Record<string, unknown>;
  selectedAction: Record<string, unknown>;
  changes: Array<Record<string, unknown>>;
  blockers: Array<Record<string, unknown>>;
}): Array<Record<string, unknown>> {
  const blocks: Array<Record<string, unknown>> = [];

  if (input.changes.length > 0) {
    blocks.push({
      block_id: 'action-sim-impact-auto',
      type: 'impact_preview_block',
      title: 'Simulated Changes',
      priority: 90,
      changes: input.changes
    });
  }

  if (input.blockers.length > 0) {
    blocks.push({
      block_id: 'action-sim-blockers-auto',
      type: 'warning_block',
      title: 'Execution Blockers',
      priority: 92,
      severity: 'high',
      summary: String(input.summary.why_it_matters ?? 'Resolve blockers before execution.'),
      warning_items: input.blockers.map((item) => String(item.label ?? item.key ?? 'Missing input'))
    });
  }

  if (blocks.length === 0) {
    blocks.push({
      block_id: 'action-sim-summary-auto',
      type: 'recommendation_block',
      title: 'Simulation Summary',
      priority: 86,
      summary: String(input.summary.title ?? 'Action simulation'),
      recommended_action: input.selectedAction
    });
  }

  return blocks;
}

function mapBusinessObjectRef(row: BusinessObjectRow): Record<string, unknown> {
  return {
    object_id: row.object_id,
    object_type: row.object_type,
    display_name: row.display_name,
    source_system: emptyToUndefined(row.source_system),
    external_ref: emptyToUndefined(row.external_ref)
  };
}

function mapBusinessException(row: BusinessExceptionRow): Record<string, unknown> {
  const result: Record<string, unknown> = {
    exception_id: row.exception_id,
    code: row.code,
    title: row.title,
    severity: row.severity,
    status: row.status
  };

  if (row.summary) {
    result.summary = row.summary;
  }
  if (row.due_at) {
    result.due_at = new Date(row.due_at).toISOString();
  }
  if (row.owner) {
    result.owner = row.owner;
  }
  if (Object.keys(row.recommended_action_json ?? {}).length > 0) {
    result.recommended_action = row.recommended_action_json;
  }
  if ((row.evidence_json ?? []).length > 0) {
    result.evidence_refs = row.evidence_json;
  }

  return result;
}

function mapBusinessRecommendation(row: BusinessRecommendationRow): Record<string, unknown> {
  const result: Record<string, unknown> = {
    action_key: row.action_key,
    label: row.label
  };

  if (row.style) {
    result.style = row.style;
  }
  if (row.reason) {
    result.reason = row.reason;
  }
  if (typeof row.confidence === 'number') {
    result.confidence = row.confidence;
  }
  if (row.requires_confirmation) {
    result.requires_confirmation = row.requires_confirmation;
  }
  if ((row.required_permissions ?? []).length > 0) {
    result.required_permissions = row.required_permissions;
  }
  if (Object.keys(row.args_hint ?? {}).length > 0) {
    result.args_hint = row.args_hint;
  }

  return result;
}

function rankExceptionFeedActions(
  recommendations: BusinessRecommendationRow[],
  exceptions: BusinessExceptionRow[]
): Array<Record<string, unknown>> {
  const ranked = new Map<string, { action: Record<string, unknown>; score: number }>();

  for (const row of recommendations) {
    const action = mapBusinessRecommendation(row);
    const score =
      (row.priority ?? 0) * 10 +
      (typeof row.confidence === 'number' ? row.confidence * 100 : 0) +
      severityWeightFromReason(row.reason);
    ranked.set(row.action_key, { action, score });
  }

  for (const row of exceptions) {
    const action = row.recommended_action_json;
    const actionKey = typeof action?.action_key === 'string' ? action.action_key : undefined;
    if (!actionKey) {
      continue;
    }
    const previous = ranked.get(actionKey);
    const additionalScore = severityWeight(row.severity) * 100 + (row.status === 'open' ? 25 : 0);
    ranked.set(actionKey, {
      action,
      score: (previous?.score ?? 0) + additionalScore
    });
  }

  return Array.from(ranked.values())
    .sort((left, right) => right.score - left.score)
    .slice(0, 5)
    .map((item) => item.action);
}

function filterDecisionRecommendations(
  recommendations: BusinessRecommendationRow[],
  candidateActions: string[] | undefined
): BusinessRecommendationRow[] {
  if (!candidateActions || candidateActions.length === 0) {
    return recommendations;
  }

  const allowed = new Set(candidateActions);
  const filtered = recommendations.filter((item) => allowed.has(item.action_key));
  return filtered.length > 0 ? filtered : recommendations;
}

function buildActionProposals(
  request: ActionProposeRequest,
  object: BusinessObjectRow | undefined,
  recommendations: BusinessRecommendationRow[],
  exceptions: BusinessExceptionRow[]
): Array<Record<string, unknown>> {
  const allowed = request.available_actions ? new Set(request.available_actions) : undefined;
  const scored = recommendations
    .filter((item) => !allowed || allowed.has(item.action_key))
    .map((item) => ({
      action: mapBusinessRecommendation(item),
      score: scoreActionProposal(item, request.intent, object, exceptions)
    }))
    .sort((left, right) => right.score - left.score)
    .slice(0, 5)
    .map((item) => item.action);

  if (scored.length > 0) {
    return scored;
  }

  const fallbackActions = exceptions
    .map((item) => item.recommended_action_json)
    .filter((item) => typeof item?.action_key === 'string')
    .filter((item) => !allowed || allowed.has(String(item.action_key)))
    .slice(0, 5);

  return fallbackActions;
}

function scoreActionProposal(
  recommendation: BusinessRecommendationRow,
  intent: string,
  object: BusinessObjectRow | undefined,
  exceptions: BusinessExceptionRow[]
): number {
  const normalizedIntent = normalizeKey(intent);
  const haystack = `${recommendation.action_key} ${recommendation.label} ${recommendation.reason}`.toLowerCase();
  const intentTokens = normalizedIntent.split(/\s+/).filter((item) => item.length > 2);
  const intentMatches = intentTokens.filter((token) => haystack.includes(token)).length;

  return (
    (recommendation.priority ?? 0) * 10 +
    (recommendation.confidence ?? 0) * 100 +
    intentMatches * 25 +
    severityWeight(highestExceptionSeverity(exceptions)) * 10 +
    (object?.health === 'blocked' && haystack.includes('request') ? 15 : 0)
  );
}

function extractActionMissingInputs(
  snapshot: PageContextSnapshotRow | undefined,
  object: BusinessObjectRow | undefined,
  proposedActions: Array<Record<string, unknown>>,
  draftArgs: Record<string, unknown>
): Array<Record<string, unknown>> {
  const fromSnapshot = readArrayField(snapshot?.current_state_json, 'missing_inputs');
  if (fromSnapshot.length > 0) {
    return filterMissingInputsByArgs(fromSnapshot, draftArgs);
  }

  const byAction = coerceRecord(object?.current_state?.missing_inputs_by_action, {});
  const actionSpecific = proposedActions.flatMap((action) => {
    const actionKey = String(action.action_key ?? '');
    return coerceArray(byAction[actionKey]);
  });
  if (actionSpecific.length > 0) {
    return filterMissingInputsByArgs(actionSpecific, draftArgs);
  }

  return [];
}

function extractActionConstraints(
  snapshot: PageContextSnapshotRow | undefined,
  object: BusinessObjectRow | undefined,
  proposedActions: Array<Record<string, unknown>>
): string[] {
  const snapshotConstraints = readStringArrayField(snapshot?.current_state_json, 'constraints');
  if (snapshotConstraints.length > 0) {
    return snapshotConstraints;
  }

  const objectConstraints = readStringArrayField(object?.current_state, 'action_constraints');
  if (objectConstraints.length > 0) {
    return objectConstraints;
  }

  return proposedActions
    .flatMap((action) =>
      readStringArrayValue(
        coerceRecord(object?.current_state?.action_constraints_by_action, {})[String(action.action_key ?? '')]
      )
    )
    .slice(0, 5);
}

function extractDecisionMissingPrerequisites(
  snapshot: PageContextSnapshotRow | undefined,
  object: BusinessObjectRow | undefined,
  exceptions: BusinessExceptionRow[]
): Array<Record<string, unknown>> {
  const snapshotItems = readArrayField(snapshot?.current_state_json, 'missing_prerequisites');
  if (snapshotItems.length > 0) {
    return snapshotItems;
  }

  const objectItems = readArrayField(object?.current_state, 'missing_prerequisites');
  if (objectItems.length > 0) {
    return objectItems;
  }

  return exceptions
    .filter((item) => item.status === 'open')
    .slice(0, 3)
    .map((item) => ({
      key: normalizeKey(item.code),
      label: item.title,
      reason: item.summary || `${item.title} is still open.`,
      required_for: 'approval review'
    }));
}

async function resolveLinkedBusinessObjects(db: DatabasePool, objectId: string): Promise<BusinessObjectRow[]> {
  const links = await listBusinessObjectLinks(db, objectId);
  if (links.length === 0) {
    return [];
  }
  return listBusinessObjectsByIds(
    db,
    links.map((item) => item.dst_object_id)
  );
}

function extractDecisionImpactPreview(
  snapshot: PageContextSnapshotRow | undefined,
  object: BusinessObjectRow | undefined
): Array<Record<string, unknown>> {
  const snapshotItems = readArrayField(snapshot?.current_state_json, 'impact_preview');
  if (snapshotItems.length > 0) {
    return snapshotItems;
  }

  const objectItems = readArrayField(object?.current_state, 'impact_preview');
  if (objectItems.length > 0) {
    return objectItems;
  }

  if (!object) {
    return [];
  }

  return [
    {
      object: mapBusinessObjectRef(object),
      field: `${object.object_type}_status`,
      before: object.status,
      after: object.health === 'blocked' ? object.status : 'approved',
      summary: `${object.display_name} advances to the next workflow state after approval.`
    }
  ];
}

function collectDecisionEvidence(
  object: BusinessObjectRow | undefined,
  exceptions: BusinessExceptionRow[]
): Array<Record<string, unknown>> {
  const objectEvidence = readArrayField(object?.current_state, 'evidence');
  if (objectEvidence.length > 0) {
    return [...objectEvidence, ...collectEvidenceFromExceptions(exceptions)];
  }

  const artifactEvidence = readArrayField(object?.current_state, 'artifacts').map((item) => ({
    evidence_id: String(item.artifact_id ?? item.name ?? 'artifact'),
    kind: 'artifact_version',
    label: String(item.name ?? item.artifact_id ?? 'Artifact'),
    summary: typeof item.summary === 'string' ? item.summary : undefined,
    freshness: typeof item.freshness === 'string' ? item.freshness : undefined
  }));

  return [...artifactEvidence, ...collectEvidenceFromExceptions(exceptions)];
}

function collectActionEvidence(
  object: BusinessObjectRow | undefined,
  exceptions: BusinessExceptionRow[]
): Array<Record<string, unknown>> {
  const objectEvidence = readArrayField(object?.current_state, 'evidence');
  if (objectEvidence.length > 0) {
    return objectEvidence;
  }

  return collectEvidenceFromExceptions(exceptions);
}

function buildDecisionRecommendation(
  approvalRef: string,
  object: BusinessObjectRow | undefined,
  recommendations: BusinessRecommendationRow[],
  exceptions: BusinessExceptionRow[],
  missingPrerequisites: Array<Record<string, unknown>>
): Record<string, unknown> {
  const primary = recommendations[0];
  const inferred = inferDisposition(primary);
  const highestSeverity = highestExceptionSeverity(exceptions);
  const blockingMissing = missingPrerequisites.filter(isBlockingPrerequisite);
  const followUpMissing = missingPrerequisites.filter((item) => !isBlockingPrerequisite(item));

  let disposition: 'approve' | 'reject' | 'request_info' | 'investigate_more';
  if (inferred === 'reject') {
    disposition = 'reject';
  } else if (highestSeverity === 'critical') {
    disposition = 'investigate_more';
  } else if (blockingMissing.length > 0) {
    disposition = inferred === 'approve' ? 'request_info' : (inferred ?? 'request_info');
  } else if (inferred) {
    disposition = inferred;
  } else if (highestSeverity === 'high' || object?.health === 'blocked') {
    disposition = 'investigate_more';
  } else if (followUpMissing.length > 0) {
    disposition = 'approve';
  } else {
    disposition = 'approve';
  }

  return {
    disposition,
    reason:
      primary?.reason ||
      (disposition === 'approve'
        ? `${object?.display_name ?? approvalRef} has enough evidence to proceed.`
        : disposition === 'reject'
          ? `Reject ${object?.display_name ?? approvalRef} until policy issues are resolved.`
          : disposition === 'request_info'
            ? `More information is required before ${approvalRef} can be approved.`
            : `Open risks need investigation before ${approvalRef} can be finalized.`),
    confidence: normalizeDecisionConfidence(primary?.confidence, disposition, highestSeverity, blockingMissing.length)
  };
}

function findSelectedAction(
  actionKey: string,
  recommendations: BusinessRecommendationRow[],
  object: BusinessObjectRow | undefined
): Record<string, unknown> {
  const fromRecommendation = recommendations.find((item) => item.action_key === actionKey);
  if (fromRecommendation) {
    return mapBusinessRecommendation(fromRecommendation);
  }

  const actionCatalog = readArrayField(object?.current_state, 'action_catalog');
  const fromCatalog = actionCatalog.find((item) => item.action_key === actionKey);
  if (fromCatalog) {
    return fromCatalog;
  }

  return {
    action_key: actionKey,
    label: humanizeActionKey(actionKey),
    style: 'secondary',
    reason: `${humanizeActionKey(actionKey)} is being simulated from the current page context.`,
    confidence: 0.65,
    requires_confirmation: false
  };
}

function extractSimulationBlockers(
  snapshot: PageContextSnapshotRow | undefined,
  object: BusinessObjectRow | undefined,
  selectedAction: Record<string, unknown>,
  args: Record<string, unknown>
): Array<Record<string, unknown>> {
  const actionKey = String(selectedAction.action_key ?? '');
  const simulationMap = coerceRecord(object?.current_state?.action_simulations, {});
  const simulationEntry = coerceRecord(simulationMap[actionKey], {});
  const snapshotBlockers = readArrayField(snapshot?.current_state_json, 'blockers');
  const actionBlockers = coerceArray(simulationEntry.blockers);
  const missingInputsByAction = coerceRecord(object?.current_state?.missing_inputs_by_action, {});
  const missingInputs = coerceArray(missingInputsByAction[actionKey]);
  const combined = [...snapshotBlockers, ...actionBlockers, ...missingInputs];

  return filterMissingInputsByArgs(combined, args);
}

function extractSimulationChanges(
  snapshot: PageContextSnapshotRow | undefined,
  object: BusinessObjectRow | undefined,
  selectedAction: Record<string, unknown>,
  args: Record<string, unknown>,
  linkedObjects: BusinessObjectRow[]
): Array<Record<string, unknown>> {
  const snapshotChanges = readArrayField(snapshot?.current_state_json, 'changes');
  if (snapshotChanges.length > 0) {
    return snapshotChanges;
  }

  const actionKey = String(selectedAction.action_key ?? '');
  const simulationMap = coerceRecord(object?.current_state?.action_simulations, {});
  const simulationEntry = coerceRecord(simulationMap[actionKey], {});
  const configuredChanges = coerceArray(simulationEntry.changes);
  if (configuredChanges.length > 0) {
    return configuredChanges;
  }

  if (!object) {
    return [];
  }

  const changes: Array<Record<string, unknown>> = [];
  if (actionKey.includes('escalate')) {
    changes.push({
      object: mapBusinessObjectRef(object),
      field: 'priority',
      before: object.status,
      after: 'high',
      summary: `${object.display_name} is prioritized for urgent handling after escalation.`
    });

    if (linkedObjects[0]) {
      changes.push({
        object: mapBusinessObjectRef(linkedObjects[0]),
        field: 'owner',
        before: emptyToUndefined(linkedObjects[0].owner) ?? 'current_owner',
        after: String(args.manager ?? 'manager_queue'),
        summary: `${linkedObjects[0].display_name} is reassigned to the escalation owner.`
      });
    }
  } else if (actionKey.includes('request')) {
    changes.push({
      object: mapBusinessObjectRef(object),
      field: 'status',
      before: object.status,
      after: 'waiting_on_input',
      summary: `${object.display_name} moves into a waiting state while required inputs are collected.`
    });
  } else {
    changes.push({
      object: mapBusinessObjectRef(object),
      field: `${object.object_type}_status`,
      before: object.status,
      after: object.status,
      summary: `${humanizeActionKey(actionKey)} does not change persisted state until execution.`
    });
  }

  return changes;
}

function extractSimulationFollowUps(
  object: BusinessObjectRow | undefined,
  selectedAction: Record<string, unknown>,
  recommendations: BusinessRecommendationRow[],
  pageType: string | undefined
): Array<Record<string, unknown>> {
  const actionKey = String(selectedAction.action_key ?? '');
  const simulationMap = coerceRecord(object?.current_state?.action_simulations, {});
  const simulationEntry = coerceRecord(simulationMap[actionKey], {});
  const configured = coerceArray(simulationEntry.follow_up_actions);
  if (configured.length > 0) {
    return configured;
  }

  return recommendations
    .filter((item) => item.action_key !== actionKey)
    .filter((item) => !pageType || !item.page_type || item.page_type === pageType)
    .slice(0, 3)
    .map(mapBusinessRecommendation);
}

function extractAffectedObjects(
  object: BusinessObjectRow | undefined,
  linkedObjects: BusinessObjectRow[],
  changes: Array<Record<string, unknown>>
): Array<Record<string, unknown>> {
  const byId = new Map<string, Record<string, unknown>>();

  if (object) {
    byId.set(object.object_id, mapBusinessObjectRef(object));
  }

  for (const linked of linkedObjects) {
    byId.set(linked.object_id, mapBusinessObjectRef(linked));
  }

  for (const change of changes) {
    const objectRef = change.object;
    if (objectRef && typeof objectRef === 'object' && !Array.isArray(objectRef)) {
      const normalized = objectRef as Record<string, unknown>;
      const objectId = typeof normalized.object_id === 'string' ? normalized.object_id : undefined;
      if (objectId) {
        byId.set(objectId, normalized);
      }
    }
  }

  return Array.from(byId.values());
}

function extractSimulationEvidence(
  snapshot: PageContextSnapshotRow | undefined,
  object: BusinessObjectRow | undefined,
  selectedAction: Record<string, unknown>
): Array<Record<string, unknown>> {
  const snapshotEvidence = coerceArray(snapshot?.evidence_json);
  if (snapshotEvidence.length > 0) {
    return snapshotEvidence;
  }

  const actionKey = String(selectedAction.action_key ?? '');
  const simulationMap = coerceRecord(object?.current_state?.action_simulations, {});
  const simulationEntry = coerceRecord(simulationMap[actionKey], {});
  const configured = coerceArray(simulationEntry.evidence);
  if (configured.length > 0) {
    return configured;
  }

  return collectActionEvidence(object, []);
}

function collectEvidenceFromExceptions(rows: BusinessExceptionRow[]): Array<Record<string, unknown>> {
  return rows.flatMap((row) => row.evidence_json ?? []);
}

function readArrayField(
  currentState: Record<string, unknown> | undefined,
  key: string
): Array<Record<string, unknown>> {
  const raw = currentState?.[key];
  return Array.isArray(raw) ? (raw as Array<Record<string, unknown>>) : [];
}

function readStringArrayField(
  currentState: Record<string, unknown> | undefined,
  key: string
): string[] {
  const raw = currentState?.[key];
  return Array.isArray(raw) ? raw.filter((item): item is string => typeof item === 'string') : [];
}

function readStringArrayValue(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === 'string');
  }
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return readStringArrayField(value as Record<string, unknown>, 'items');
  }
  return [];
}

function coerceArray(
  value: unknown,
  fallback: Array<Record<string, unknown>> = []
): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : fallback;
}

function coerceRecord(
  value: unknown,
  fallback: Record<string, unknown>
): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : fallback;
}

function emptyToUndefined(value: string | null | undefined): string | undefined {
  if (!value) {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function severityFromHealth(health: BusinessObjectRow['health']): string {
  switch (health) {
    case 'blocked':
      return 'high';
    case 'at_risk':
      return 'medium';
    case 'watch':
      return 'low';
    default:
      return 'info';
  }
}

function severityWeight(severity: BusinessExceptionRow['severity']): number {
  switch (severity) {
    case 'critical':
      return 5;
    case 'high':
      return 4;
    case 'medium':
      return 3;
    case 'low':
      return 2;
    default:
      return 1;
  }
}

function severityWeightFromReason(reason: string): number {
  const normalized = reason.toLowerCase();
  if (normalized.includes('critical') || normalized.includes('immediate')) {
    return 30;
  }
  if (normalized.includes('high') || normalized.includes('blocked')) {
    return 20;
  }
  if (normalized.includes('risk') || normalized.includes('caution')) {
    return 10;
  }
  return 0;
}

function inferDisposition(
  recommendation: BusinessRecommendationRow | undefined
): 'approve' | 'reject' | 'request_info' | 'investigate_more' | undefined {
  if (!recommendation) {
    return undefined;
  }

  const normalized = `${recommendation.action_key} ${recommendation.label} ${recommendation.reason}`.toLowerCase();
  if (normalized.includes('reject') || normalized.includes('deny') || normalized.includes('decline')) {
    return 'reject';
  }
  if (
    normalized.includes('request_info') ||
    normalized.includes('request info') ||
    normalized.includes('request_approval') ||
    normalized.includes('request document') ||
    normalized.includes('request_') ||
    normalized.includes('collect_') ||
    normalized.includes('provide_') ||
    normalized.includes('upload_') ||
    normalized.includes('complete_')
  ) {
    return 'request_info';
  }
  if (
    normalized.includes('investigate') ||
    normalized.includes('review') ||
    normalized.includes('escalate') ||
    normalized.includes('triage')
  ) {
    return 'investigate_more';
  }
  if (
    normalized.includes('approve') ||
    normalized.includes('accept') ||
    normalized.includes('clear')
  ) {
    return 'approve';
  }
  return undefined;
}

function filterMissingInputsByArgs(
  items: Array<Record<string, unknown>>,
  args: Record<string, unknown>
): Array<Record<string, unknown>> {
  return items.filter((item) => {
    const key = typeof item.key === 'string' ? item.key : undefined;
    if (!key) {
      return true;
    }
    return !(key in args) || args[key] === undefined || args[key] === null || args[key] === '';
  });
}

function normalizeDecisionConfidence(
  confidence: number | null | undefined,
  disposition: 'approve' | 'reject' | 'request_info' | 'investigate_more',
  highestSeverity: BusinessExceptionRow['severity'],
  blockingMissingCount: number
): number {
  if (typeof confidence === 'number') {
    return confidence;
  }

  if (disposition === 'approve' && highestSeverity !== 'critical' && blockingMissingCount === 0) {
    return 0.82;
  }
  if (disposition === 'request_info') {
    return 0.74;
  }
  if (disposition === 'investigate_more') {
    return highestSeverity === 'critical' ? 0.78 : 0.7;
  }
  return 0.76;
}

function highestExceptionSeverity(exceptions: BusinessExceptionRow[]): BusinessExceptionRow['severity'] {
  return exceptions
    .map((item) => item.severity)
    .sort((left, right) => severityWeight(right) - severityWeight(left))[0] ?? 'info';
}

function highestMappedExceptionSeverity(
  exceptions: Array<Record<string, unknown>>
): 'info' | 'low' | 'medium' | 'high' | 'critical' {
  const severities = exceptions
    .map((item) => {
      const severity = item.severity;
      return typeof severity === 'string' ? severity : 'info';
    })
    .filter(
      (
        severity
      ): severity is 'info' | 'low' | 'medium' | 'high' | 'critical' =>
        ['info', 'low', 'medium', 'high', 'critical'].includes(severity)
    );

  return severities.sort((left, right) => severityWeight(right) - severityWeight(left))[0] ?? 'info';
}

function isBlockingPrerequisite(item: Record<string, unknown>): boolean {
  const requiredFor = String(item.required_for ?? '').toLowerCase();
  if (!requiredFor) {
    return true;
  }
  return !requiredFor.includes('post-approval') && !requiredFor.includes('follow-up');
}

function decisionStatus(disposition: string): string {
  switch (disposition) {
    case 'approve':
      return 'review_ready';
    case 'reject':
      return 'blocked';
    case 'request_info':
      return 'needs_info';
    default:
      return 'investigating';
  }
}

function decisionHealth(
  disposition: string,
  severity: BusinessExceptionRow['severity']
): 'healthy' | 'watch' | 'at_risk' | 'blocked' {
  if (disposition === 'reject' || severity === 'critical') {
    return 'blocked';
  }
  if (disposition === 'investigate_more' || severity === 'high') {
    return 'at_risk';
  }
  if (disposition === 'request_info' || severity === 'medium') {
    return 'watch';
  }
  return 'healthy';
}

function normalizeKey(value: string): string {
  return value.trim().toLowerCase();
}

function humanizeActionKey(value: string): string {
  return value
    .split('_')
    .filter((item) => item.length > 0)
    .map((item) => item[0].toUpperCase() + item.slice(1))
    .join(' ');
}

function latestTimestamp(...values: Array<string | undefined>): string {
  const defined = values.filter((value): value is string => typeof value === 'string' && value.length > 0);
  if (defined.length === 0) {
    return new Date().toISOString();
  }
  return new Date(
    defined
      .map((value) => new Date(value).getTime())
      .sort((a, b) => b - a)[0]
  ).toISOString();
}

import { randomUUID } from 'node:crypto';

import type { Static } from '@sinclair/typebox';

import type { GatewayBackendClient } from '../clients/gateway_backend.types.js';
import { TdbError } from '../errors/tdb_error.js';
import {
  PlanDryRunResponseSchema,
  PlanExecuteRequestSchema,
  PlanExecuteResponseSchema,
  PlanExplainResponseSchema,
  PlanReplayByIdRequestSchema,
  PlanReplayResponseSchema,
  PlanRunGetQuerySchema,
  PlanRunListQuerySchema,
  PlanValidateResponseSchema
} from '../schema/v2/plan.js';
import { ArtifactService } from './artifact.service.js';
import { DecisionService } from './decision.service.js';
import { EntityService } from './entity.service.js';
import { EventService } from './event.service.js';
import { GovernanceService } from './governance.service.js';
import { IngestService } from './ingest.service.js';
import { MemoryService } from './memory.service.js';
import { SearchService } from './search.service.js';
import { SnapshotService } from './snapshot.service.js';
import { StateService } from './state.service.js';

type PlanExecuteRequest = Static<typeof PlanExecuteRequestSchema>;
type PlanValidateResponse = Static<typeof PlanValidateResponseSchema>;
type PlanExplainResponse = Static<typeof PlanExplainResponseSchema>;
type PlanExecuteResponse = Static<typeof PlanExecuteResponseSchema>;
type PlanDryRunResponse = Static<typeof PlanDryRunResponseSchema>;
type PlanReplayResponse = Static<typeof PlanReplayResponseSchema>;
type PlanRunGetQuery = Static<typeof PlanRunGetQuerySchema>;
type PlanRunListQuery = Static<typeof PlanRunListQuerySchema>;
type PlanReplayByIdRequest = Static<typeof PlanReplayByIdRequestSchema>;

type PlanDiagnostic = {
  level: 'error' | 'warning';
  code: string;
  message: string;
  step_id?: string;
  op?: string;
  details?: unknown;
};

type PlanStepInspection = {
  id: string;
  op: string;
  supported: boolean;
  mutating: boolean;
  save_as?: string;
  on_error: 'fail' | 'continue';
  timeout_ms?: number;
  template_refs: string[];
  context_dependencies: string[];
  var_dependencies: string[];
  args_preview?: unknown;
  when_preview?: string;
};

type PlanStepResult = {
  id: string;
  op: string;
  ok: boolean;
  skipped?: boolean;
  dry_run_skipped?: boolean;
  would_mutate?: boolean;
  duration_ms: number;
  args_preview?: unknown;
  response?: unknown;
  error?: {
    code: string;
    message: string;
    details?: unknown;
  };
};

type PlanStepTrace = {
  id: string;
  op: string;
  status: 'executed' | 'skipped' | 'dry_run_skipped' | 'failed';
  mutating: boolean;
  save_as?: string;
  when?: string;
  when_result?: boolean;
  vars_before: Record<string, unknown>;
  vars_after: Record<string, unknown>;
  args_resolved?: unknown;
  saved_value_preview?: unknown;
  duration_ms: number;
  started_at: string;
  finished_at: string;
  error?: {
    code: string;
    message: string;
    details?: unknown;
  };
};

type ServiceBundle = {
  artifact: ArtifactService;
  decision: DecisionService;
  entity: EntityService;
  event: EventService;
  governance: GovernanceService;
  ingest: IngestService;
  search: SearchService;
  memory: MemoryService;
  snapshot: SnapshotService;
  state: StateService;
};

type OpContext = {
  services?: ServiceBundle;
};

type PlanAnalysis = {
  valid: boolean;
  execution_mode: 'safe' | 'best_effort';
  step_count: number;
  mutating_step_count: number;
  diagnostics: PlanDiagnostic[];
  steps: PlanStepInspection[];
};

const CONTINUE = 'continue';
const SAFE = 'safe';
const BEST_EFFORT = 'best_effort';
const SUPPORTED_OPS = new Set([
  'health.get',
  'health.db',
  'event.append',
  'event.read',
  'entity.upsert',
  'entity.get',
  'entity.list',
  'state.property.upsert',
  'state.property.asof',
  'state.property.diff',
  'state.property.why',
  'state.edge.upsert',
  'state.edge.asof',
  'state.edge.diff',
  'artifact.create',
  'artifact.version.create',
  'artifact.version.asof',
  'rule.upsert',
  'authority.grant',
  'rule.override',
  'authority.check',
  'rule.override.asof',
  'ontology.fact.review',
  'ontology.fact.history',
  'ontology.fact.provenance',
  'ontology.fact.review.bulk',
  'ontology.case.open',
  'ontology.case.list',
  'ontology.case.detail',
  'ontology.case.explain',
  'ontology.case.update',
  'ontology.alert.open',
  'ontology.alert.list',
  'ontology.alert.explain',
  'ontology.alert.update',
  'ontology.ops.config.list',
  'ontology.ops.config.upsert',
  'ontology.ops.rules.run',
  'ontology.ops.runs.list',
  'ontology.ops.run.explain',
  'decision.create',
  'decision.get',
  'decision.explain',
  'decision.trace',
  'decision.evidence.attach',
  'snapshot.write',
  'snapshot.latest',
  'search.query',
  'ingest.entities',
  'ingest.artifacts',
  'ingest.events',
  'ingest.text',
  'ingest.property',
  'ingest.edge',
  'memory.record_decision',
  'memory.record_episode_summary',
  'memory.entity.upsert',
  'memory.entity.get',
  'memory.task.context'
]);
const MUTATING_OPS = new Set([
  'event.append',
  'entity.upsert',
  'state.property.upsert',
  'state.edge.upsert',
  'artifact.create',
  'artifact.version.create',
  'rule.upsert',
  'authority.grant',
  'rule.override',
  'ontology.fact.review',
  'ontology.fact.review.bulk',
  'ontology.case.open',
  'ontology.case.update',
  'ontology.alert.open',
  'ontology.alert.update',
  'ontology.ops.config.upsert',
  'ontology.ops.rules.run',
  'decision.create',
  'decision.evidence.attach',
  'snapshot.write',
  'ingest.entities',
  'ingest.artifacts',
  'ingest.events',
  'ingest.text',
  'ingest.property',
  'ingest.edge',
  'memory.record_decision',
  'memory.record_episode_summary',
  'memory.entity.upsert'
]);

export class PlanService {
  constructor(
    private readonly deps: {
      gatewayBackend: GatewayBackendClient;
    }
  ) {}

  validate(plan: PlanExecuteRequest): PlanValidateResponse {
    return buildPlanAnalysis(plan);
  }

  explain(plan: PlanExecuteRequest): PlanExplainResponse {
    return {
      plan_id: randomUUID(),
      goal: plan.goal,
      ...buildPlanAnalysis(plan)
    };
  }

  async dryRun(plan: PlanExecuteRequest): Promise<PlanDryRunResponse> {
    const analysis = buildPlanAnalysis(plan);
    const planId = randomUUID();
    const startedAt = new Date();
    if (!analysis.valid) {
      return {
        plan_id: planId,
        success: false,
        execution_mode: analysis.execution_mode,
        started_at: startedAt.toISOString(),
        finished_at: new Date().toISOString(),
        results: [],
        vars: {},
        dry_run: true,
        diagnostics: analysis.diagnostics
      };
    }

    const run = await this.runPlan(plan, {
      skipMutations: true
    });

    const response: PlanDryRunResponse = {
      ...run,
      dry_run: true,
      diagnostics: analysis.diagnostics
    };
    await this.persistPlanRun('dry_run', plan, response, run.trace);
    return response;
  }

  async execute(plan: PlanExecuteRequest): Promise<PlanExecuteResponse> {
    const analysis = buildPlanAnalysis(plan);
    const firstError = analysis.diagnostics.find((item) => item.level === 'error');
    if (firstError) {
      throw diagnosticToError(firstError);
    }

    const response = await this.runPlan(plan, {
      skipMutations: false
    });
    await this.persistPlanRun('execute', plan, response, response.trace);
    return response;
  }

  async replay(plan: PlanExecuteRequest): Promise<PlanReplayResponse> {
    const analysis = buildPlanAnalysis(plan);
    const firstError = analysis.diagnostics.find((item) => item.level === 'error');
    if (firstError) {
      throw diagnosticToError(firstError);
    }

    const run = await this.runPlan(plan, {
      skipMutations: false,
      captureTrace: true
    });

    const response: PlanReplayResponse = {
      ...run,
      replay: true,
      trace: run.trace ?? []
    };
    await this.persistPlanRun('replay', plan, response, run.trace);
    return response;
  }

  async getRun(query: PlanRunGetQuery): Promise<{
    run: {
      plan_id: string;
      execution_kind: 'execute' | 'dry_run' | 'replay';
      replay_of_plan_id?: string;
      goal: string;
      execution_mode: 'safe' | 'best_effort';
      success: boolean;
      started_at: string;
      finished_at: string;
      created_at: string;
    };
    request: PlanExecuteRequest;
    response: unknown;
    trace: PlanStepTrace[];
  }> {
    throw new TdbError('PLAN_RUNS_UNAVAILABLE', 501, `plan run lookup is unavailable: ${query.plan_id}`);
  }

  async listRuns(query: PlanRunListQuery): Promise<{
    execution_kind_filter?: 'execute' | 'dry_run' | 'replay';
    success_filter?: boolean;
    goal_q_filter?: string;
    replay_of_plan_id_filter?: string;
    limit: number;
    count: number;
    runs: Array<{
      plan_id: string;
      execution_kind: 'execute' | 'dry_run' | 'replay';
      replay_of_plan_id?: string;
      goal: string;
      execution_mode: 'safe' | 'best_effort';
      success: boolean;
      started_at: string;
      finished_at: string;
      created_at: string;
    }>;
  }> {
    throw new TdbError(
      'PLAN_RUNS_UNAVAILABLE',
      501,
      'plan run listing is unavailable because gateway no longer persists plan runs locally',
      {
        execution_kind: query.execution_kind,
        success: query.success,
        goal_q: query.goal_q,
        replay_of_plan_id: query.replay_of_plan_id
      }
    );
  }

  async replayById(request: PlanReplayByIdRequest): Promise<PlanReplayResponse> {
    throw new TdbError('PLAN_RUNS_UNAVAILABLE', 501, `plan replay by id is unavailable: ${request.plan_id}`);
  }

  private async runOp(op: string, args: Record<string, unknown>, ctx: OpContext): Promise<unknown> {
    if (op === 'health.get') {
      return {
        status: 'ok',
        service: 'tdb-gateway',
        version: 'v2'
      };
    }

    if (op === 'health.db') {
      throw new TdbError('DB_NOT_CONFIGURED', 500, 'Gateway no longer exposes direct database health');
    }

    const services = ensureServices(ctx.services);

    switch (op) {
      case 'event.append':
        return services.event.appendEvent(args as Parameters<EventService['appendEvent']>[0]);
      case 'event.read':
        return { events: await services.event.readEvents(args as Parameters<EventService['readEvents']>[0]) };
      case 'entity.upsert':
        return services.entity.upsert(args as Parameters<EntityService['upsert']>[0]);
      case 'entity.get':
        return { entity: await services.entity.get(args as Parameters<EntityService['get']>[0]) };
      case 'entity.list':
        return { entities: await services.entity.list(args as Parameters<EntityService['list']>[0]) };
      case 'state.property.upsert':
        return services.state.upsertProperty(args as Parameters<StateService['upsertProperty']>[0]);
      case 'state.property.asof':
        return { property: await services.state.getPropertyAsOf(args as Parameters<StateService['getPropertyAsOf']>[0]) };
      case 'state.property.diff':
        return services.state.diffProperty(args as Parameters<StateService['diffProperty']>[0]);
      case 'state.property.why':
        return services.state.explainProperty(args as Parameters<StateService['explainProperty']>[0]);
      case 'state.edge.upsert':
        return services.state.upsertEdge(args as Parameters<StateService['upsertEdge']>[0]);
      case 'state.edge.asof':
        return { edges: await services.state.getEdgesAsOf(args as Parameters<StateService['getEdgesAsOf']>[0]) };
      case 'state.edge.diff':
        return services.state.diffEdges(args as Parameters<StateService['diffEdges']>[0]);
      case 'artifact.create':
        return services.artifact.createArtifact(args as Parameters<ArtifactService['createArtifact']>[0]);
      case 'artifact.version.create':
        return services.artifact.createArtifactVersion(
          args as Parameters<ArtifactService['createArtifactVersion']>[0]
        );
      case 'artifact.version.asof':
        return { artifact_version: await services.artifact.getArtifactVersionAsOf(args as Parameters<ArtifactService['getArtifactVersionAsOf']>[0]) };
      case 'rule.upsert':
        return services.governance.upsertRule(args as Parameters<GovernanceService['upsertRule']>[0]);
      case 'authority.grant':
        return services.governance.grantAuthority(args as Parameters<GovernanceService['grantAuthority']>[0]);
      case 'rule.override':
        return services.governance.overrideRule(args as Parameters<GovernanceService['overrideRule']>[0]);
      case 'authority.check':
        return services.governance.checkAuthority(
          normalizeAuthorityCheckArgs(args) as Parameters<GovernanceService['checkAuthority']>[0]
        );
      case 'rule.override.asof':
        return { overrides: await services.governance.listOverridesAsOf(args as Parameters<GovernanceService['listOverridesAsOf']>[0]) };
      case 'ontology.fact.review':
        return services.governance.reviewOntologyFact(
          args as Parameters<GovernanceService['reviewOntologyFact']>[0]
        );
      case 'ontology.fact.history':
        return services.governance.getOntologyFactHistory(
          args as Parameters<GovernanceService['getOntologyFactHistory']>[0]
        );
      case 'ontology.fact.provenance':
        return services.governance.getOntologyFactProvenance(
          args as Parameters<GovernanceService['getOntologyFactProvenance']>[0]
        );
      case 'ontology.fact.review.bulk':
        return services.governance.bulkReviewOntologyFacts(
          args as Parameters<GovernanceService['bulkReviewOntologyFacts']>[0]
        );
      case 'ontology.case.open':
        return services.governance.openOntologyCase(
          args as Parameters<GovernanceService['openOntologyCase']>[0]
        );
      case 'ontology.case.list':
        return services.governance.listOntologyCases(
          args as Parameters<GovernanceService['listOntologyCases']>[0]
        );
      case 'ontology.case.detail':
        return services.governance.getOntologyCaseDetail(
          args as Parameters<GovernanceService['getOntologyCaseDetail']>[0]
        );
      case 'ontology.case.explain':
        return services.governance.explainOntologyCase(
          args as Parameters<GovernanceService['explainOntologyCase']>[0]
        );
      case 'ontology.case.update':
        return services.governance.updateOntologyCase(
          args as Parameters<GovernanceService['updateOntologyCase']>[0]
        );
      case 'ontology.alert.open':
        return services.governance.openOntologyAlert(
          args as Parameters<GovernanceService['openOntologyAlert']>[0]
        );
      case 'ontology.alert.list':
        return services.governance.listOntologyAlerts(
          args as Parameters<GovernanceService['listOntologyAlerts']>[0]
        );
      case 'ontology.alert.explain':
        return services.governance.explainOntologyAlert(
          args as Parameters<GovernanceService['explainOntologyAlert']>[0]
        );
      case 'ontology.alert.update':
        return services.governance.updateOntologyAlert(
          args as Parameters<GovernanceService['updateOntologyAlert']>[0]
        );
      case 'ontology.ops.config.list':
        return services.governance.listOntologyOpsRuleConfig(
          args as Parameters<GovernanceService['listOntologyOpsRuleConfig']>[0]
        );
      case 'ontology.ops.config.upsert':
        return services.governance.upsertOntologyOpsRuleConfig(
          args as Parameters<GovernanceService['upsertOntologyOpsRuleConfig']>[0]
        );
      case 'ontology.ops.rules.run':
        return services.governance.runOntologyOpsRules(
          args as Parameters<GovernanceService['runOntologyOpsRules']>[0]
        );
      case 'ontology.ops.runs.list':
        return services.governance.listOntologyOpsRuns(
          args as Parameters<GovernanceService['listOntologyOpsRuns']>[0]
        );
      case 'ontology.ops.run.explain':
        return services.governance.explainOntologyOpsRun(
          args as Parameters<GovernanceService['explainOntologyOpsRun']>[0]
        );
      case 'decision.create':
        return services.decision.createDecision(args as Parameters<DecisionService['createDecision']>[0]);
      case 'decision.get':
        return services.decision.getDecision(args as Parameters<DecisionService['getDecision']>[0]);
      case 'decision.explain':
        return services.decision.explainDecision(args as Parameters<DecisionService['explainDecision']>[0]);
      case 'decision.trace':
        return services.decision.traceDecision(args as Parameters<DecisionService['traceDecision']>[0]);
      case 'decision.evidence.attach':
        return services.decision.attachEvidence(args as Parameters<DecisionService['attachEvidence']>[0]);
      case 'snapshot.write':
        return services.snapshot.writeSnapshot(args as Parameters<SnapshotService['writeSnapshot']>[0]);
      case 'snapshot.latest':
        return { snapshot: await services.snapshot.latestSnapshot(args as Parameters<SnapshotService['latestSnapshot']>[0]) };
      case 'search.query':
        return { query: String(args.query ?? ''), hits: await services.search.query(args as Parameters<SearchService['query']>[0]) };
      case 'ingest.entities':
        return services.ingest.ingestEntities(args as Parameters<IngestService['ingestEntities']>[0]);
      case 'ingest.artifacts':
        return services.ingest.ingestArtifacts(args as Parameters<IngestService['ingestArtifacts']>[0]);
      case 'ingest.events':
        return services.ingest.ingestEvents(args as Parameters<IngestService['ingestEvents']>[0]);
      case 'ingest.text':
        return services.ingest.ingestText(args as Parameters<IngestService['ingestText']>[0]);
      case 'ingest.property':
        return services.ingest.ingestProperty(args as Parameters<IngestService['ingestProperty']>[0]);
      case 'ingest.edge':
        return services.ingest.ingestEdge(args as Parameters<IngestService['ingestEdge']>[0]);
      case 'memory.record_decision':
        return services.memory.recordDecision(args as Parameters<MemoryService['recordDecision']>[0]);
      case 'memory.record_episode_summary':
        return services.memory.recordEpisodeSummary(args as Parameters<MemoryService['recordEpisodeSummary']>[0]);
      case 'memory.entity.upsert':
        return services.memory.upsertEntityState(args as Parameters<MemoryService['upsertEntityState']>[0]);
      case 'memory.entity.get':
        return services.memory.getEntityState(args as Parameters<MemoryService['getEntityState']>[0]);
      case 'memory.task.context':
        return services.memory.getTaskContext(args as Parameters<MemoryService['getTaskContext']>[0]);
      default:
        throw new TdbError('PLAN_OP_UNSUPPORTED', 400, `Unsupported op: ${op}`);
    }
  }

  private async runPlan(
    plan: PlanExecuteRequest,
    options: { skipMutations: boolean; captureTrace?: boolean }
  ): Promise<PlanExecuteResponse & { trace?: PlanStepTrace[] }> {
    const executionMode = normalizeExecutionMode(plan.execution_mode);
    const planId = randomUUID();
    const startedAt = new Date();
    const vars: Record<string, unknown> = {};
    const results: PlanStepResult[] = [];
    const trace: PlanStepTrace[] = [];
    const services = buildServiceBundle(this.deps.gatewayBackend);

    for (const step of plan.steps) {
      const stepStart = Date.now();
      const stepStartedAt = new Date(stepStart).toISOString();
      const varsBefore = cloneJsonRecord(vars);
      let whenResult: boolean | undefined;
      let resolvedArgs: Record<string, unknown> | undefined;
      try {
        whenResult = step.when ? evaluateWhen(step.when, plan.context ?? {}, vars) : undefined;
        if (step.when && !whenResult) {
          results.push({
            id: step.id,
            op: step.op,
            ok: true,
            skipped: true,
            duration_ms: Date.now() - stepStart
          });
          if (options.captureTrace) {
            trace.push({
              id: step.id,
              op: step.op,
              status: 'skipped',
              mutating: isMutatingOp(step.op),
              save_as: step.save_as,
              when: step.when,
              when_result: whenResult,
              vars_before: varsBefore,
              vars_after: cloneJsonRecord(vars),
              duration_ms: Date.now() - stepStart,
              started_at: stepStartedAt,
              finished_at: new Date().toISOString()
            });
          }
          continue;
        }

        resolvedArgs = resolveArgs(step.args ?? {}, plan.context ?? {}, vars);
        const mutating = isMutatingOp(step.op);
        if (options.skipMutations && mutating) {
          const skippedResponse = {
            dry_run: true,
            skipped_write: true,
            op: step.op,
            args: resolvedArgs
          };
          if (step.save_as) {
            vars[step.save_as] = skippedResponse;
          }
          results.push({
            id: step.id,
            op: step.op,
            ok: true,
            dry_run_skipped: true,
            would_mutate: true,
            duration_ms: Date.now() - stepStart,
            args_preview: resolvedArgs,
            response: skippedResponse
          });
          if (options.captureTrace) {
            trace.push({
              id: step.id,
              op: step.op,
              status: 'dry_run_skipped',
              mutating,
              save_as: step.save_as,
              when: step.when,
              when_result: whenResult,
              vars_before: varsBefore,
              vars_after: cloneJsonRecord(vars),
              args_resolved: cloneJsonValue(resolvedArgs),
              saved_value_preview: step.save_as ? cloneJsonValue(skippedResponse) : undefined,
              duration_ms: Date.now() - stepStart,
              started_at: stepStartedAt,
              finished_at: new Date().toISOString()
            });
          }
          continue;
        }

        const response = await runWithTimeout(
          this.runOp(step.op, resolvedArgs, { services }),
          step.timeout_ms
        );

        if (step.save_as) {
          vars[step.save_as] = response;
        }

        results.push({
          id: step.id,
          op: step.op,
          ok: true,
          would_mutate: mutating,
          duration_ms: Date.now() - stepStart,
          args_preview: resolvedArgs,
          response
        });
        if (options.captureTrace) {
          trace.push({
            id: step.id,
            op: step.op,
            status: 'executed',
            mutating,
            save_as: step.save_as,
            when: step.when,
            when_result: whenResult,
            vars_before: varsBefore,
            vars_after: cloneJsonRecord(vars),
            args_resolved: cloneJsonValue(resolvedArgs),
            saved_value_preview: step.save_as ? cloneJsonValue(response) : undefined,
            duration_ms: Date.now() - stepStart,
            started_at: stepStartedAt,
            finished_at: new Date().toISOString()
          });
        }
      } catch (error) {
        const normalized = normalizeError(error);
        results.push({
          id: step.id,
          op: step.op,
          ok: false,
          would_mutate: isMutatingOp(step.op),
          duration_ms: Date.now() - stepStart,
          args_preview: step.args ?? {},
          error: normalized
        });
        if (options.captureTrace) {
          trace.push({
            id: step.id,
            op: step.op,
            status: 'failed',
            mutating: isMutatingOp(step.op),
            save_as: step.save_as,
            when: step.when,
            vars_before: varsBefore,
            vars_after: cloneJsonRecord(vars),
            when_result: whenResult,
            args_resolved: resolvedArgs ? cloneJsonValue(resolvedArgs) : (step.args ? cloneJsonValue(step.args) : undefined),
            duration_ms: Date.now() - stepStart,
            started_at: stepStartedAt,
            finished_at: new Date().toISOString(),
            error: normalized
          });
        }

        if ((step.on_error ?? 'fail') !== CONTINUE) {
          return {
            plan_id: planId,
            success: false,
            execution_mode: executionMode,
            started_at: startedAt.toISOString(),
            finished_at: new Date().toISOString(),
            results,
            vars,
            trace: options.captureTrace ? trace : undefined
          };
        }
      }
    }

    return {
      plan_id: planId,
      success: results.every((item) => item.ok),
      execution_mode: executionMode,
      started_at: startedAt.toISOString(),
      finished_at: new Date().toISOString(),
      results,
      vars,
      trace: options.captureTrace ? trace : undefined
    };
  }

  private async persistPlanRun(
    executionKind: 'execute' | 'dry_run' | 'replay',
    plan: PlanExecuteRequest,
    response: PlanExecuteResponse | PlanDryRunResponse | PlanReplayResponse,
    trace?: PlanStepTrace[],
    replayOfPlanId?: string
  ): Promise<void> {
    void executionKind;
    void plan;
    void response;
    void trace;
    void replayOfPlanId;
  }
}

function buildServiceBundle(gatewayBackend: GatewayBackendClient): ServiceBundle {
  return {
    artifact: new ArtifactService(gatewayBackend),
    decision: new DecisionService(gatewayBackend),
    entity: new EntityService(gatewayBackend),
    event: new EventService(gatewayBackend),
    governance: new GovernanceService(gatewayBackend),
    ingest: new IngestService(gatewayBackend),
    memory: new MemoryService(gatewayBackend),
    search: new SearchService(gatewayBackend),
    snapshot: new SnapshotService(gatewayBackend),
    state: new StateService(gatewayBackend)
  };
}

function ensureServices(services?: ServiceBundle): ServiceBundle {
  if (!services) {
    throw new TdbError('INTERNAL_ERROR', 500, 'Service bundle is not configured');
  }
  return services;
}

function normalizeAuthorityCheckArgs(args: Record<string, unknown>): Record<string, unknown> {
  if (!args.scope || typeof args.scope === 'string') {
    return args;
  }
  return {
    ...args,
    scope: JSON.stringify(args.scope)
  };
}

function normalizeExecutionMode(
  value: PlanExecuteRequest['execution_mode']
): 'safe' | 'best_effort' {
  return value === BEST_EFFORT ? BEST_EFFORT : SAFE;
}

function cloneJsonRecord(value: Record<string, unknown>): Record<string, unknown> {
  return cloneJsonValue(value) as Record<string, unknown>;
}

function cloneJsonValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function validatePlanSafety(
  plan: PlanExecuteRequest,
  executionMode: 'safe' | 'best_effort'
): void {
  if (executionMode !== SAFE) {
    return;
  }

  const mutatingSteps = plan.steps.filter((step) => isMutatingOp(step.op));
  if (mutatingSteps.length > 1) {
    throw new TdbError(
      'PLAN_MUTATION_UNSAFE',
      400,
      'safe execution_mode allows at most one mutating step; use best_effort for multi-step write orchestration',
      {
        execution_mode: executionMode,
        mutating_steps: mutatingSteps.map((step) => step.id)
      }
    );
  }

  const unsafeMutatingStep = mutatingSteps.find(
    (step) => step.on_error === CONTINUE || typeof step.timeout_ms === 'number'
  );
  if (unsafeMutatingStep) {
    throw new TdbError(
      'PLAN_MUTATION_UNSAFE',
      400,
      'safe execution_mode does not allow mutating steps with on_error=continue or timeout_ms',
      {
        execution_mode: executionMode,
        step_id: unsafeMutatingStep.id,
        op: unsafeMutatingStep.op
      }
    );
  }
}

function isMutatingOp(op: string): boolean {
  return MUTATING_OPS.has(op);
}

function isSupportedOp(op: string): boolean {
  return SUPPORTED_OPS.has(op);
}

function buildPlanAnalysis(plan: PlanExecuteRequest): PlanAnalysis {
  const executionMode = normalizeExecutionMode(plan.execution_mode);
  const diagnostics: PlanDiagnostic[] = [];
  const seenStepIds = new Set<string>();
  const seenSaveAs = new Set<string>();
  const availableVars = new Set<string>();
  const steps: PlanStepInspection[] = [];

  for (const step of plan.steps) {
    if (seenStepIds.has(step.id)) {
      diagnostics.push({
        level: 'error',
        code: 'PLAN_DUPLICATE_STEP_ID',
        message: `Duplicate step id: ${step.id}`,
        step_id: step.id,
        op: step.op
      });
    } else {
      seenStepIds.add(step.id);
    }

    const refs = collectTemplateRefs(step.args ?? {});
    const whenRefs = step.when ? collectTemplateRefs(step.when) : [];
    const templateRefs = Array.from(new Set([...refs, ...whenRefs]));
    const contextDependencies = templateRefs.filter((ref) => ref.startsWith('context.'));
    const varRefs = templateRefs.filter((ref) => ref.startsWith('vars.'));
    const varDependencies = Array.from(
      new Set(
        varRefs
          .map((ref) => ref.split('.')[1])
          .filter((value): value is string => Boolean(value))
      )
    );

    const supported = isSupportedOp(step.op);
    if (!supported) {
      diagnostics.push({
        level: 'error',
        code: 'PLAN_OP_UNSUPPORTED',
        message: `Unsupported op: ${step.op}`,
        step_id: step.id,
        op: step.op
      });
    }

    for (const ref of contextDependencies) {
      try {
        lookupPath(ref, plan.context ?? {}, {});
      } catch (error) {
        diagnostics.push({
          level: 'error',
          code: normalizeError(error).code,
          message: normalizeError(error).message,
          step_id: step.id,
          op: step.op,
          details: { ref }
        });
      }
    }

    for (const dependency of varDependencies) {
      if (!availableVars.has(dependency)) {
        diagnostics.push({
          level: 'error',
          code: 'PLAN_TEMPLATE_MISSING',
          message: `Template value not found: vars.${dependency}`,
          step_id: step.id,
          op: step.op,
          details: { ref: `vars.${dependency}` }
        });
      }
    }

    if (step.when) {
      try {
        validateWhenExpression(step.when);
      } catch (error) {
        diagnostics.push({
          level: 'error',
          code: normalizeError(error).code,
          message: normalizeError(error).message,
          step_id: step.id,
          op: step.op
        });
      }
    }

    if (step.save_as) {
      if (seenSaveAs.has(step.save_as)) {
        diagnostics.push({
          level: 'warning',
          code: 'PLAN_SAVE_AS_SHADOWED',
          message: `save_as value is reused and will overwrite prior vars entry: ${step.save_as}`,
          step_id: step.id,
          op: step.op
        });
      }
      seenSaveAs.add(step.save_as);
      availableVars.add(step.save_as);
    }

    steps.push({
      id: step.id,
      op: step.op,
      supported,
      mutating: isMutatingOp(step.op),
      save_as: step.save_as,
      on_error: step.on_error ?? 'fail',
      timeout_ms: step.timeout_ms,
      template_refs: templateRefs,
      context_dependencies: contextDependencies,
      var_dependencies: varDependencies,
      args_preview: previewValue(step.args ?? {}, plan.context ?? {}),
      when_preview: step.when
    });
  }

  try {
    validatePlanSafety(plan, executionMode);
  } catch (error) {
    const normalized = normalizeError(error);
    diagnostics.push({
      level: 'error',
      code: normalized.code,
      message: normalized.message,
      details: normalized.details
    });
  }

  return {
    valid: diagnostics.every((item) => item.level !== 'error'),
    execution_mode: executionMode,
    step_count: plan.steps.length,
    mutating_step_count: steps.filter((step) => step.mutating).length,
    diagnostics,
    steps
  };
}

function diagnosticToError(diagnostic: PlanDiagnostic): TdbError {
  const statusCode =
    diagnostic.code === 'PLAN_OP_UNSUPPORTED' ||
    diagnostic.code.startsWith('PLAN_')
      ? 400
      : 500;
  return new TdbError(diagnostic.code, statusCode, diagnostic.message, diagnostic.details);
}

function collectTemplateRefs(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.flatMap((item) => collectTemplateRefs(item));
  }
  if (value && typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).flatMap((item) => collectTemplateRefs(item));
  }
  if (typeof value !== 'string') {
    return [];
  }

  const refs: string[] = [];
  for (const match of value.matchAll(/\$\{([^}]+)\}/g)) {
    refs.push(match[1].trim());
  }
  return refs;
}

function previewValue(value: unknown, context: Record<string, unknown>): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => previewValue(item, context));
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      out[key] = previewValue(entry, context);
    }
    return out;
  }
  if (typeof value !== 'string') {
    return value;
  }

  const exact = value.match(/^\$\{([^}]+)\}$/);
  if (exact) {
    const ref = exact[1].trim();
    if (!ref.startsWith('context.')) {
      return value;
    }
    try {
      return lookupPath(ref, context, {});
    } catch {
      return value;
    }
  }

  return value.replace(/\$\{([^}]+)\}/g, (match, rawPath: string) => {
    const ref = rawPath.trim();
    if (!ref.startsWith('context.')) {
      return match;
    }
    try {
      const resolved = lookupPath(ref, context, {});
      if (resolved === undefined || resolved === null) {
        return '';
      }
      return typeof resolved === 'string' ? resolved : JSON.stringify(resolved);
    } catch {
      return match;
    }
  });
}

function resolveArgs(
  args: Record<string, unknown>,
  context: Record<string, unknown>,
  vars: Record<string, unknown>
): Record<string, unknown> {
  return resolveValue(args, context, vars) as Record<string, unknown>;
}

function resolveValue(
  value: unknown,
  context: Record<string, unknown>,
  vars: Record<string, unknown>
): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => resolveValue(item, context, vars));
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = resolveValue(v, context, vars);
    }
    return out;
  }
  if (typeof value === 'string') {
    return resolveStringValue(value, context, vars);
  }
  return value;
}

function resolveStringValue(
  value: string,
  context: Record<string, unknown>,
  vars: Record<string, unknown>
): unknown {
  const exact = value.match(/^\$\{([^}]+)\}$/);
  if (exact) {
    return lookupPath(exact[1], context, vars);
  }

  if (!value.includes('${')) {
    return value;
  }

  return value.replace(/\$\{([^}]+)\}/g, (_match, path: string) => {
    const resolved = lookupPath(path, context, vars);
    if (resolved === undefined || resolved === null) {
      return '';
    }
    if (typeof resolved === 'string') {
      return resolved;
    }
    return JSON.stringify(resolved);
  });
}

function lookupPath(
  rawPath: string,
  context: Record<string, unknown>,
  vars: Record<string, unknown>
): unknown {
  const path = rawPath.trim();
  if (!path) {
    throw new TdbError('PLAN_TEMPLATE_INVALID', 400, 'Template path cannot be empty');
  }

  const segments = path.split('.');
  const root = segments.shift();
  if (root !== 'context' && root !== 'vars') {
    throw new TdbError('PLAN_TEMPLATE_INVALID', 400, `Template path must start with context or vars: ${path}`);
  }

  let current: unknown = root === 'context' ? context : vars;
  for (const segment of segments) {
    if (!segment) {
      throw new TdbError('PLAN_TEMPLATE_INVALID', 400, `Invalid template path: ${path}`);
    }
    if (!current || typeof current !== 'object' || !(segment in current)) {
      throw new TdbError('PLAN_TEMPLATE_MISSING', 400, `Template value not found: ${path}`);
    }
    current = (current as Record<string, unknown>)[segment];
  }
  return current;
}

function evaluateWhen(
  expression: string,
  context: Record<string, unknown>,
  vars: Record<string, unknown>
): boolean {
  validateWhenExpression(expression);
  const trimmed = expression.trim();
  if (trimmed === 'true') {
    return true;
  }
  if (trimmed === 'false') {
    return false;
  }
  if (trimmed.startsWith('!${') && trimmed.endsWith('}')) {
    const value = lookupPath(trimmed.slice(3, -1), context, vars);
    return !Boolean(value);
  }
  if (trimmed.startsWith('${') && trimmed.endsWith('}')) {
    const value = lookupPath(trimmed.slice(2, -1), context, vars);
    return Boolean(value);
  }

  throw new TdbError(
    'PLAN_WHEN_UNSUPPORTED',
    400,
    'Unsupported when expression. Use true/false, ${path}, or !${path}'
  );
}

function validateWhenExpression(expression: string): void {
  const trimmed = expression.trim();
  if (
    trimmed === 'true' ||
    trimmed === 'false' ||
    (/^\$\{[^}]+\}$/.test(trimmed)) ||
    (/^!\$\{[^}]+\}$/.test(trimmed))
  ) {
    return;
  }

  throw new TdbError(
    'PLAN_WHEN_UNSUPPORTED',
    400,
    'Unsupported when expression. Use true/false, ${path}, or !${path}'
  );
}

async function runWithTimeout<T>(promise: Promise<T>, timeoutMs?: number): Promise<T> {
  if (!timeoutMs) {
    return promise;
  }

  return Promise.race([
    promise,
    new Promise<T>((_resolve, reject) => {
      setTimeout(() => {
        reject(new TdbError('PLAN_STEP_TIMEOUT', 408, `Step timed out after ${timeoutMs}ms`));
      }, timeoutMs);
    })
  ]);
}

function normalizeError(error: unknown): { code: string; message: string; details?: unknown } {
  if (error instanceof TdbError) {
    return {
      code: error.code,
      message: error.message,
      details: error.details
    };
  }
  if (error instanceof Error) {
    return {
      code: 'INTERNAL_ERROR',
      message: error.message
    };
  }
  return {
    code: 'INTERNAL_ERROR',
    message: 'Unknown error'
  };
}

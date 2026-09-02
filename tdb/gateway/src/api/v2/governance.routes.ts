import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import {
  AssertionPolicyRuleGetRouteSchema,
  AssertionPolicyRuleListRouteSchema,
  AssertionPolicyRuleUpsertRouteSchema,
  AuthorityCheckRouteSchema,
  AuthorityGrantRouteSchema,
  EvidencePolicyRuleGetRouteSchema,
  EvidencePolicyRuleListRouteSchema,
  EvidencePolicyRuleUpsertRouteSchema,
  MethodologyFrameworkBundleRouteSchema,
  MethodologyFrameworkGetRouteSchema,
  MethodologyFrameworkListRouteSchema,
  MethodologyFrameworkUpsertRouteSchema,
  OntologyAlertExplainRouteSchema,
  OntologyAlertListRouteSchema,
  OntologyAlertOpenRouteSchema,
  OntologyAlertUpdateRouteSchema,
  OntologyCaseConflictDraftRouteSchema,
  OntologyCaseDecisionListRouteSchema,
  OntologyCaseDecisionRecordRouteSchema,
  OntologyCaseDetailRouteSchema,
  OntologyCaseExplainRouteSchema,
  OntologyCaseListRouteSchema,
  OntologyCaseOpenRouteSchema,
  OntologyCaseUpdateRouteSchema,
  OntologyFactBulkReviewRouteSchema,
  OntologyFactHistoryRouteSchema,
  OntologyFactProvenanceRouteSchema,
  OntologyFactReviewRouteSchema,
  OntologyOpsRuleConfigListRouteSchema,
  OntologyOpsRuleConfigUpsertRouteSchema,
  OntologyOpsRuleRunExplainRouteSchema,
  OntologyOpsRuleRunListRouteSchema,
  OntologyOpsRuleRunRouteSchema,
  ReviewPolicyGetRouteSchema,
  ReviewPolicyListRouteSchema,
  ReviewPolicyUpsertRouteSchema,
  RuleOverrideAsOfRouteSchema,
  RuleOverrideRouteSchema,
  RuleUpsertRouteSchema,
  TaxonomySchemeGetRouteSchema,
  TaxonomySchemeListRouteSchema,
  TaxonomySchemeUpsertRouteSchema
} from '../../schema/v2/governance.js';
import { GovernanceService } from '../../services/governance.service.js';

const governanceRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): GovernanceService => new GovernanceService(app.gatewayBackend);

  app.post('/rule/upsert', { schema: RuleUpsertRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const rule = await service.upsertRule(req.body);
    reply.status(201).send(rule as never);
  });

  app.post('/authority/grant', { schema: AuthorityGrantRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const grant = await service.grantAuthority(req.body);
    reply.status(201).send(grant as never);
  });

  app.post('/rule/override', { schema: RuleOverrideRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const override = await service.overrideRule(req.body);
    reply.status(201).send(override as never);
  });

  app.get('/authority/check', { schema: AuthorityCheckRouteSchema }, async (req) => {
    const service = ensureService();
    const result = await service.checkAuthority(req.query);
    return {
      allowed: result.allowed,
      authority_grant: result.authorityGrant
    } as never;
  });

  app.get('/rule/override/asof', { schema: RuleOverrideAsOfRouteSchema }, async (req) => {
    const service = ensureService();
    const overrides = await service.listOverridesAsOf(req.query);
    return { overrides } as never;
  });

  app.post('/governance/methodology/framework/upsert', { schema: MethodologyFrameworkUpsertRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const framework = await service.upsertMethodologyFramework(req.body);
    reply.status(201).send(framework as never);
  });

  app.get('/governance/methodology/framework/get', { schema: MethodologyFrameworkGetRouteSchema }, async (req) => {
    const service = ensureService();
    return { framework: await service.getMethodologyFramework(req.query) } as never;
  });

  app.get('/governance/methodology/framework/list', { schema: MethodologyFrameworkListRouteSchema }, async (req) => {
    const service = ensureService();
    return { frameworks: await service.listMethodologyFrameworks(req.query) } as never;
  });

  app.get('/governance/methodology/framework/bundle', { schema: MethodologyFrameworkBundleRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.getMethodologyFrameworkBundle(req.query)) as never;
  });

  app.post('/governance/methodology/taxonomy-scheme/upsert', { schema: TaxonomySchemeUpsertRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const scheme = await service.upsertTaxonomyScheme(req.body);
    reply.status(201).send(scheme as never);
  });

  app.get('/governance/methodology/taxonomy-scheme/get', { schema: TaxonomySchemeGetRouteSchema }, async (req) => {
    const service = ensureService();
    return { scheme: await service.getTaxonomyScheme(req.query) } as never;
  });

  app.get('/governance/methodology/taxonomy-scheme/list', { schema: TaxonomySchemeListRouteSchema }, async (req) => {
    const service = ensureService();
    return { schemes: await service.listTaxonomySchemes(req.query) } as never;
  });

  app.post('/governance/methodology/evidence-policy/upsert', { schema: EvidencePolicyRuleUpsertRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const rule = await service.upsertEvidencePolicyRule(req.body);
    reply.status(201).send(rule as never);
  });

  app.get('/governance/methodology/evidence-policy/get', { schema: EvidencePolicyRuleGetRouteSchema }, async (req) => {
    const service = ensureService();
    return { rule: await service.getEvidencePolicyRule(req.query) } as never;
  });

  app.get('/governance/methodology/evidence-policy/list', { schema: EvidencePolicyRuleListRouteSchema }, async (req) => {
    const service = ensureService();
    return { rules: await service.listEvidencePolicyRules(req.query) } as never;
  });

  app.post('/governance/methodology/assertion-policy/upsert', { schema: AssertionPolicyRuleUpsertRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const rule = await service.upsertAssertionPolicyRule(req.body);
    reply.status(201).send(rule as never);
  });

  app.get('/governance/methodology/assertion-policy/get', { schema: AssertionPolicyRuleGetRouteSchema }, async (req) => {
    const service = ensureService();
    return { rule: await service.getAssertionPolicyRule(req.query) } as never;
  });

  app.get('/governance/methodology/assertion-policy/list', { schema: AssertionPolicyRuleListRouteSchema }, async (req) => {
    const service = ensureService();
    return { rules: await service.listAssertionPolicyRules(req.query) } as never;
  });

  app.post('/governance/methodology/review-policy/upsert', { schema: ReviewPolicyUpsertRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const policy = await service.upsertReviewPolicy(req.body);
    reply.status(201).send(policy as never);
  });

  app.get('/governance/methodology/review-policy/get', { schema: ReviewPolicyGetRouteSchema }, async (req) => {
    const service = ensureService();
    return { policy: await service.getReviewPolicy(req.query) } as never;
  });

  app.get('/governance/methodology/review-policy/list', { schema: ReviewPolicyListRouteSchema }, async (req) => {
    const service = ensureService();
    return { policies: await service.listReviewPolicies(req.query) } as never;
  });

  app.post('/ontology/fact/review', { schema: OntologyFactReviewRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.reviewOntologyFact(req.body)) as never;
  });

  app.get('/ontology/fact/history', { schema: OntologyFactHistoryRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.getOntologyFactHistory(req.query)) as never;
  });

  app.get('/ontology/fact/provenance', { schema: OntologyFactProvenanceRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.getOntologyFactProvenance(req.query)) as never;
  });

  app.post('/ontology/fact/review/bulk', { schema: OntologyFactBulkReviewRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.bulkReviewOntologyFacts(req.body)) as never;
  });

  app.post('/ontology/case/open', { schema: OntologyCaseOpenRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const result = await service.openOntologyCase(req.body);
    reply.status(201).send(result as never);
  });

  app.get('/ontology/case/list', { schema: OntologyCaseListRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.listOntologyCases(req.query)) as never;
  });

  app.post('/ontology/case/decision/record', { schema: OntologyCaseDecisionRecordRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const result = await service.recordOntologyCaseDecision(req.body);
    reply.status(201).send(result as never);
  });

  app.post('/ontology/case/decision/draft/conflict', { schema: OntologyCaseConflictDraftRouteSchema }, async (req) => {
    const service = ensureService() as GovernanceService & {
      createConflictDraftDecision(request: typeof req.body): Promise<unknown>;
    };
    return (await service.createConflictDraftDecision(req.body)) as never;
  });

  app.get('/ontology/case/decision/list', { schema: OntologyCaseDecisionListRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.listOntologyCaseDecisions(req.query)) as never;
  });

  app.get('/ontology/case/detail', { schema: OntologyCaseDetailRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.getOntologyCaseDetail(req.query)) as never;
  });

  app.get('/ontology/case/explain', { schema: OntologyCaseExplainRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.explainOntologyCase(req.query)) as never;
  });

  app.post('/ontology/case/update', { schema: OntologyCaseUpdateRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.updateOntologyCase(req.body)) as never;
  });

  app.post('/ontology/alert/open', { schema: OntologyAlertOpenRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const result = await service.openOntologyAlert(req.body);
    reply.status(201).send(result as never);
  });

  app.get('/ontology/alert/list', { schema: OntologyAlertListRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.listOntologyAlerts(req.query)) as never;
  });

  app.get('/ontology/alert/explain', { schema: OntologyAlertExplainRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.explainOntologyAlert(req.query)) as never;
  });

  app.post('/ontology/alert/update', { schema: OntologyAlertUpdateRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.updateOntologyAlert(req.body)) as never;
  });

  app.get('/ontology/ops/config', { schema: OntologyOpsRuleConfigListRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.listOntologyOpsRuleConfig(req.query)) as never;
  });

  app.post('/ontology/ops/config/upsert', { schema: OntologyOpsRuleConfigUpsertRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.upsertOntologyOpsRuleConfig(req.body)) as never;
  });

  app.post('/ontology/ops/rules/run', { schema: OntologyOpsRuleRunRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.runOntologyOpsRules(req.body)) as never;
  });

  app.get('/ontology/ops/runs', { schema: OntologyOpsRuleRunListRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.listOntologyOpsRuns(req.query)) as never;
  });

  app.get('/ontology/ops/run/explain', { schema: OntologyOpsRuleRunExplainRouteSchema }, async (req) => {
    const service = ensureService();
    return (await service.explainOntologyOpsRun(req.query)) as never;
  });
};

export default governanceRoutes;

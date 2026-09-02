import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import {
  OntologyConceptEvidenceRouteSchema,
  ConceptAliasSearchRouteSchema,
  ConceptAliasListRouteSchema,
  ConceptAliasUpsertRouteSchema,
  EventConceptLinkListRouteSchema,
  EventConceptLinkUpsertRouteSchema,
  OntologyConceptGetRouteSchema,
  OntologyConceptListRouteSchema,
  OntologyConceptNeighborsRouteSchema,
  OntologyConceptSearchRouteSchema,
  OntologyConceptTypeAssignmentListRouteSchema,
  OntologyConceptTypeAssignmentUpsertRouteSchema,
  OntologyConceptUpsertRouteSchema,
  OntologyEdgeListRouteSchema,
  OntologyEdgeUpsertRouteSchema,
  OntologyFactArchiveRouteSchema,
  OntologyFactGetRouteSchema,
  OntologyFactListRouteSchema,
  OntologyFactSearchRouteSchema,
  OntologyFactUpsertWithEvidenceRouteSchema,
  SemanticStatementGetRouteSchema,
  SemanticStatementListRouteSchema,
  SemanticStatementStatusRouteSchema,
  SemanticStatementProvenanceRouteSchema,
  SemanticBatchUpsertRouteSchema,
  OntologyObjectTypeGetRouteSchema,
  OntologyObjectTypeListRouteSchema,
  OntologyObjectTypeUpsertRouteSchema,
  OntologyClusterMemberListRouteSchema,
  OntologyClusterMemberUpsertRouteSchema,
  OntologyNormalizedTermGetRouteSchema,
  OntologyNormalizedTermSearchRouteSchema,
  OntologyNormalizedTermUpsertRouteSchema,
  OntologyRawTermCandidateListRouteSchema,
  OntologyRawTermCandidateUpsertRouteSchema,
  OntologyRawTermGetRouteSchema,
  OntologyRelationCandidateListRouteSchema,
  OntologyRelationCandidateUpsertRouteSchema,
  OntologyRawTermNormalizationListRouteSchema,
  OntologyRawTermNormalizationUpsertRouteSchema,
  OntologyRawTermSearchRouteSchema,
  OntologyRawTermUpsertRouteSchema,
  OntologyRelationTypeGetRouteSchema,
  OntologyRelationTypeListRouteSchema,
  OntologyRelationTypeUpsertRouteSchema,
  OntologyTermClusterGetRouteSchema,
  OntologyTermClusterListRouteSchema,
  OntologyTermClusterUpsertRouteSchema,
  TermMappingInterpretBatchRouteSchema,
  TermMappingInterpretRouteSchema,
  TermMappingRegistryGetRouteSchema,
  TermMappingRegistryListRouteSchema,
  TermMappingRegistryUpsertRouteSchema,
  TermMappingRuleEvidenceListRouteSchema,
  TermMappingRuleEvidenceUpsertRouteSchema,
  TermMappingRuleGetRouteSchema,
  TermMappingRuleSearchRouteSchema,
  TermMappingRuleUpsertRouteSchema
} from '../../schema/v2/ontology.js';
import { OntologyEvidenceService } from '../../services/ontology_evidence.service.js';
import { OntologyService } from '../../services/ontology.service.js';

const ontologyRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): OntologyService => new OntologyService(app.gatewayBackend);

  app.post('/ontology/concept/upsert', { schema: OntologyConceptUpsertRouteSchema }, async (req, reply) => {
    const concept = await ensureService().upsertConcept(req.body);
    reply.status(201).send(concept);
  });
  app.get('/ontology/concept/get', { schema: OntologyConceptGetRouteSchema }, async (req) => ({ concept: await ensureService().getConcept(req.query) }));
  app.get('/ontology/concept/evidence', { schema: OntologyConceptEvidenceRouteSchema }, async (req) => {
    const service = new OntologyEvidenceService(app.gatewayBackend);
    return (await service.getConceptEvidence(req.query)) as never;
  });
  app.get('/ontology/concept/list', { schema: OntologyConceptListRouteSchema }, async (req) => ({ concepts: await ensureService().listConcepts(req.query) }));
  app.get('/ontology/concept/search', { schema: OntologyConceptSearchRouteSchema }, async (req) => ({ concepts: await ensureService().searchConcepts(req.query) }));
  app.get('/ontology/concept/neighbors', { schema: OntologyConceptNeighborsRouteSchema }, async (req) => ({ neighbors: await ensureService().getConceptNeighbors(req.query) }));

  app.post('/ontology/alias/upsert', { schema: ConceptAliasUpsertRouteSchema }, async (req, reply) => {
    const alias = await ensureService().upsertAlias(req.body);
    reply.status(201).send(alias);
  });
  app.get('/ontology/alias/list', { schema: ConceptAliasListRouteSchema }, async (req) => ({ aliases: await ensureService().listAliases(req.query) }));
  app.get('/ontology/alias/search', { schema: ConceptAliasSearchRouteSchema }, async (req) => ({ aliases: await ensureService().searchAliases(req.query) }));

  app.post('/ontology/edge/upsert', { schema: OntologyEdgeUpsertRouteSchema }, async (req, reply) => {
    const edge = await ensureService().upsertEdge(req.body);
    reply.status(201).send(edge);
  });
  app.get('/ontology/edge/list', { schema: OntologyEdgeListRouteSchema }, async (req) => ({ edges: await ensureService().listEdges(req.query) }));

  app.post('/ontology/event-link/upsert', { schema: EventConceptLinkUpsertRouteSchema }, async (req, reply) => {
    const link = await ensureService().upsertEventLink(req.body);
    reply.status(201).send(link);
  });
  app.get('/ontology/event-link/list', { schema: EventConceptLinkListRouteSchema }, async (req) => ({ links: await ensureService().listEventLinks(req.query) }));

  app.post('/ontology/object-type/upsert', { schema: OntologyObjectTypeUpsertRouteSchema }, async (req, reply) => {
    const object_type = await ensureService().upsertObjectType(req.body);
    reply.status(201).send(object_type);
  });
  app.get('/ontology/object-type/get', { schema: OntologyObjectTypeGetRouteSchema }, async (req) => ({ object_type: await ensureService().getObjectType(req.query) }));
  app.get('/ontology/object-type/list', { schema: OntologyObjectTypeListRouteSchema }, async (req) => ({ object_types: await ensureService().listObjectTypes(req.query) }));
  app.post('/ontology/concept-type-assignment/upsert', { schema: OntologyConceptTypeAssignmentUpsertRouteSchema }, async (req, reply) => {
    const assignment = await ensureService().upsertConceptTypeAssignment(req.body);
    reply.status(201).send(assignment);
  });
  app.get('/ontology/concept-type-assignment/list', { schema: OntologyConceptTypeAssignmentListRouteSchema }, async (req) => ({ assignments: await ensureService().listConceptTypeAssignments(req.query) }));

  app.post('/ontology/relation-type/upsert', { schema: OntologyRelationTypeUpsertRouteSchema }, async (req, reply) => {
    const relation_type = await ensureService().upsertRelationType(req.body);
    reply.status(201).send(relation_type);
  });
  app.get('/ontology/relation-type/get', { schema: OntologyRelationTypeGetRouteSchema }, async (req) => ({ relation_type: await ensureService().getRelationType(req.query) }));
  app.get('/ontology/relation-type/list', { schema: OntologyRelationTypeListRouteSchema }, async (req) => ({ relation_types: await ensureService().listRelationTypes(req.query) }));

  app.post('/ontology/fact/upsert-with-evidence', { schema: OntologyFactUpsertWithEvidenceRouteSchema }, async (req, reply) => {
    const response = await ensureService().upsertFactWithEvidence(req.body);
    reply.status(201).send(response);
  });
  app.post('/ontology/semantic/upsert-batch', { schema: SemanticBatchUpsertRouteSchema }, async (req, reply) => {
    const response = await ensureService().upsertSemanticBatch(req.body);
    reply.status(201).send(response);
  });
  app.get('/ontology/statement/get', { schema: SemanticStatementGetRouteSchema }, async (req) => {
    return ensureService().getSemanticStatement(req.query);
  });
  app.get('/ontology/statement/list', { schema: SemanticStatementListRouteSchema }, async (req) => {
    return ensureService().listSemanticStatements(req.query);
  });
  app.post('/ontology/statement/status', { schema: SemanticStatementStatusRouteSchema }, async (req) => {
    return ensureService().setSemanticStatementStatus(req.body);
  });
  app.get('/ontology/statement/provenance', { schema: SemanticStatementProvenanceRouteSchema }, async (req) => {
    return ensureService().getSemanticStatementProvenance(req.query);
  });
  app.get('/ontology/fact/get', { schema: OntologyFactGetRouteSchema }, async (req) => ({ fact: await ensureService().getFact((req.query as { fact_id: number }).fact_id) }));
  app.get('/ontology/fact/list', { schema: OntologyFactListRouteSchema }, async (req) => ({ facts: await ensureService().listFacts(req.query) }));
  app.get('/ontology/fact/search', { schema: OntologyFactSearchRouteSchema }, async (req) => ({ facts: await ensureService().searchFacts(req.query) }));
  app.post('/ontology/fact/archive', { schema: OntologyFactArchiveRouteSchema }, async (req) => ({ fact_id: await ensureService().archiveFact(req.body) }));

  app.post('/ontology/term-mapping/registry/upsert', { schema: TermMappingRegistryUpsertRouteSchema }, async (req, reply) => {
    const registry = await ensureService().upsertTermMappingRegistry(req.body);
    reply.status(201).send(registry);
  });
  app.get('/ontology/term-mapping/registry/get', { schema: TermMappingRegistryGetRouteSchema }, async (req) => ({ registry: await ensureService().getTermMappingRegistry(req.query) }));
  app.get('/ontology/term-mapping/registry/list', { schema: TermMappingRegistryListRouteSchema }, async (req) => ({ registries: await ensureService().listTermMappingRegistries(req.query) }));

  app.post('/ontology/normalized-term/upsert', { schema: OntologyNormalizedTermUpsertRouteSchema }, async (req, reply) => {
    const normalized_term = await ensureService().upsertNormalizedTerm(req.body);
    reply.status(201).send(normalized_term);
  });
  app.get('/ontology/normalized-term/get', { schema: OntologyNormalizedTermGetRouteSchema }, async (req) => ({ normalized_term: await ensureService().getNormalizedTerm(req.query) }));
  app.get('/ontology/normalized-term/search', { schema: OntologyNormalizedTermSearchRouteSchema }, async (req) => ({ normalized_terms: await ensureService().searchNormalizedTerms(req.query) }));
  app.post('/ontology/normalized-term/cluster/upsert', { schema: OntologyTermClusterUpsertRouteSchema }, async (req, reply) => {
    const cluster = await ensureService().upsertTermCluster(req.body);
    reply.status(201).send(cluster);
  });
  app.get('/ontology/normalized-term/cluster/get', { schema: OntologyTermClusterGetRouteSchema }, async (req) => ({ cluster: await ensureService().getTermCluster(req.query) }));
  app.get('/ontology/normalized-term/cluster/list', { schema: OntologyTermClusterListRouteSchema }, async (req) => ({ clusters: await ensureService().listTermClusters(req.query) }));
  app.post('/ontology/normalized-term/cluster-member/upsert', { schema: OntologyClusterMemberUpsertRouteSchema }, async (req, reply) => {
    const member = await ensureService().upsertClusterMember(req.body);
    reply.status(201).send(member);
  });
  app.get('/ontology/normalized-term/cluster-member/list', { schema: OntologyClusterMemberListRouteSchema }, async (req) => ({ members: await ensureService().listClusterMembers(req.query) }));
  app.post('/ontology/relation-candidate/upsert', { schema: OntologyRelationCandidateUpsertRouteSchema }, async (req, reply) => {
    const relation_candidate = await ensureService().upsertRelationCandidate(req.body);
    reply.status(201).send(relation_candidate);
  });
  app.get('/ontology/relation-candidate/list', { schema: OntologyRelationCandidateListRouteSchema }, async (req) => ({ relation_candidates: await ensureService().listRelationCandidates(req.query) }));

  app.post('/ontology/raw-term/upsert', { schema: OntologyRawTermUpsertRouteSchema }, async (req, reply) => {
    const raw_term = await ensureService().upsertRawTerm(req.body);
    reply.status(201).send(raw_term);
  });
  app.get('/ontology/raw-term/get', { schema: OntologyRawTermGetRouteSchema }, async (req) => ({ raw_term: await ensureService().getRawTerm(req.query) }));
  app.get('/ontology/raw-term/search', { schema: OntologyRawTermSearchRouteSchema }, async (req) => ({ raw_terms: await ensureService().searchRawTerms(req.query) }));
  app.post('/ontology/raw-term/candidate/upsert', { schema: OntologyRawTermCandidateUpsertRouteSchema }, async (req, reply) => {
    const candidate = await ensureService().upsertRawTermCandidate(req.body);
    reply.status(201).send(candidate);
  });
  app.get('/ontology/raw-term/candidate/list', { schema: OntologyRawTermCandidateListRouteSchema }, async (req) => ({ candidates: await ensureService().listRawTermCandidates(req.query) }));
  app.post('/ontology/normalized-term/raw-term-mapping/upsert', { schema: OntologyRawTermNormalizationUpsertRouteSchema }, async (req, reply) => {
    const mapping = await ensureService().upsertRawTermNormalization(req.body);
    reply.status(201).send(mapping);
  });
  app.get('/ontology/normalized-term/raw-term-mapping/list', { schema: OntologyRawTermNormalizationListRouteSchema }, async (req) => ({ mappings: await ensureService().listRawTermNormalizations(req.query) }));

  app.post('/ontology/term-mapping/rule/upsert', { schema: TermMappingRuleUpsertRouteSchema }, async (req, reply) => {
    const rule = await ensureService().upsertTermMappingRule(req.body);
    reply.status(201).send(rule);
  });
  app.get('/ontology/term-mapping/rule/get', { schema: TermMappingRuleGetRouteSchema }, async (req) => ({ rule: await ensureService().getTermMappingRule(req.query) }));
  app.get('/ontology/term-mapping/rule/search', { schema: TermMappingRuleSearchRouteSchema }, async (req) => ({ rules: await ensureService().searchTermMappingRules(req.query) }));

  app.post('/ontology/term-mapping/rule-evidence/upsert', { schema: TermMappingRuleEvidenceUpsertRouteSchema }, async (req, reply) => {
    const evidence = await ensureService().upsertTermMappingRuleEvidence(req.body);
    reply.status(201).send(evidence);
  });
  app.get('/ontology/term-mapping/rule-evidence/list', { schema: TermMappingRuleEvidenceListRouteSchema }, async (req) => ({ evidence: await ensureService().listTermMappingRuleEvidence(req.query) }));

  app.get('/ontology/term-mapping/interpret', { schema: TermMappingInterpretRouteSchema }, async (req) => ({ interpretation: await ensureService().interpretTerm(req.query) }));
  app.post('/ontology/term-mapping/interpret-batch', { schema: TermMappingInterpretBatchRouteSchema }, async (req) => ({ interpretations: await ensureService().interpretTermBatch(req.body) }));
};

export default ontologyRoutes;

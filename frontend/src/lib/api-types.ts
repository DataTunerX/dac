/**
 * API response types aligned with dac-apiserver handler DTOs.
 * Go returns envelope { code, message, data }; @/lib/api response interceptor
 * unwraps so res.data is the payload below. Use these types with api.get() / apiFetcher.
 *
 * 对接说明：字段与 Go internal/handler/dto/*.go 的 json tag 一致。
 * 详见仓库 docs/api-contract-go-frontend.md。
 */

// ----- Semantic groups (internal/handler/dto/semantic_group.go) -----

export type SemanticGroupResponse = {
  id: string
  group_name: string
  description?: string
  agent_card?: string
  version?: string
  parent_id?: string | null
  created_at?: string
  /** Optional counts from list/roots API when backend supports */
  child_count?: number
  member_count?: number
  /** Optional member labels/abbreviations for list display (badges); when backend provides */
  member_labels?: string[]
}

export type DDGroupRelationResponse = {
  id: number
  sd_id: string
  group_id: string
  association_reason?: string
}

export type SemanticDomainResponse = {
  semantic_domain_id?: string
  semantic_domain?: string
  agent_card?: string
  dd_namespace: string
  dd_name: string
  created_at?: string
  updated_at?: string
}

export type SemanticGroupMemberDetailResponse = {
  relation: DDGroupRelationResponse
  semantic_domain?: SemanticDomainResponse | null
}

export type SemanticGroupInfoResponse = {
  id: string
  group_name: string
  description?: string
  agent_card?: string
}

/** GET /semantic-groups/:id/with-members payload (after interceptor unwrap) */
export type SemanticGroupWithMembersResponse = {
  group: SemanticGroupResponse
  members: SemanticGroupMemberDetailResponse[]
  child_groups: SemanticGroupInfoResponse[]
}

/** GET /semantic-groups?limit=&offset= payload */
export type SemanticGroupListResponse = {
  items: SemanticGroupResponse[]
  totalCount: number
  limit?: number
  offset?: number
}

// ----- Agent containers (internal/handler/dto/agent_container.go) -----

export type DataPolicyResponse = {
  dataSourceType?: string
  semanticGroupID?: string
  sourceNameSelector?: string[]
}

/** Skill-hub package ref for a dedicated skill DAC or a local DAC attachment. */
export type SkillRef = {
  namespace: string
  name: string
  /** Empty / omitted = always pull latest. */
  version?: string
}

/** Package bindings: dedicated skill DAC execution or local orchestrator attachments. */
export type SkillPolicy = {
  skills?: SkillRef[]
}

export type AgentSkillResponse = {
  id: string
  name: string
  description: string
  tags?: string[]
  examples?: string[]
}

export type AgentCardResponse = {
  name: string
  description: string
  skills?: AgentSkillResponse[]
}

export type ModelSpecResponse = {
  embedding?: string
  expertLLM: string
  plannerLLM: string
}

export type ActiveDataDescriptorResponse = {
  name: string
  namespace: string
  lastSynced: string
}

export type EndpointResponse = {
  address: string
  port: number
  protocol: string
}

export type ConditionResponse = {
  type: string
  status: string
  lastTransitionTime: string
  reason?: string
  message?: string
}

export type AgentContainerResponse = {
  name: string
  namespace: string
  labels?: Record<string, string>
  dacType?: string
  dataPolicy: DataPolicyResponse
  /** Present for dedicated skill DACs or normal/DS DACs with local attachments. */
  skillPolicy?: SkillPolicy
  agentCard: AgentCardResponse
  model: ModelSpecResponse
  expertAgentMaxSteps?: string
  orchestratorAgentMaxLoops?: string
  activeDataDescriptors?: ActiveDataDescriptorResponse[]
  endpoint?: EndpointResponse
  conditions?: ConditionResponse[]
  createdAt: string
  updatedAt: string
}

/** POST /namespaces/:ns/agents create body (aligned with CreateAgentContainerRequest). */
export type CreateAgentContainerRequest = {
  name: string
  labels?: Record<string, string>
  dacType?: string
  dataPolicy: DataPolicyResponse
  skillPolicy?: SkillPolicy
  agentCard: AgentCardResponse
  model: ModelSpecResponse
  expertAgentMaxSteps?: string
  orchestratorAgentMaxLoops?: string
}

/** PATCH/PUT agent update body (aligned with UpdateAgentContainerRequest). */
export type UpdateAgentContainerRequest = {
  labels?: Record<string, string>
  dacType?: string
  dataPolicy?: DataPolicyResponse
  skillPolicy?: SkillPolicy
  agentCard?: AgentCardResponse
  model?: ModelSpecResponse
  expertAgentMaxSteps?: string
  orchestratorAgentMaxLoops?: string
}

/** GET /namespaces/:ns/agents or GET /agents list payload (after unwrap) */
export type AgentContainerListResponse = {
  items: AgentContainerResponse[]
  totalCount: number
  limit?: number
  offset?: number
}

// ----- ConfigMaps (internal/handler/dto/configmap.go) -----

export type ConfigMapResponse = {
  name: string
  namespace: string
  labels?: Record<string, string>
  data?: Record<string, string>
  created_at: string
}

/** GET /namespaces/:ns/configmaps list payload (after unwrap) */
export type ConfigMapListResponse = {
  items: ConfigMapResponse[]
  totalCount: number
  limit?: number
  offset?: number
}

// ----- System configuration (internal/handler/dto/system_config.go) -----

export type SystemConfigurationResponse = {
  name: string
  namespace: string
  data: Record<string, string>
  resourceVersion?: string
  exists: boolean
  createdAt?: string
}

export type SystemConfigurationListResponse = {
  items: SystemConfigurationResponse[]
  totalCount: number
}

export type SystemConfigurationVersionResponse = {
  name: string
  version: string
  namespace: string
  data: Record<string, string>
  createdAt: string
}

export type SystemConfigurationVersionListResponse = {
  items: SystemConfigurationVersionResponse[]
  totalCount: number
  limit?: number
  offset?: number
}

export type UpdateSystemConfigurationRequest = {
  data: Record<string, string>
  resourceVersion?: string
}

// ----- Data descriptors (internal/handler/dto/data_descriptor.go) -----

export type CodeRepoConfigResponse = {
  codeRepoType?: string
  codeRepoPath?: string
  codeRepoBranch?: string
  codeRepoToken?: string
}

export type DataSourceResponse = {
  type: string
  name: string
  metadata?: Record<string, string>
  extract?: { tables?: string[]; querys?: string[]; files?: string[] }
  prompts?: { configMapName?: string }
  codeRepo?: CodeRepoConfigResponse
  processing?: { cleaning?: Array<{ rule: string; params?: Record<string, string> }> }
  classification?: Array<{ domain?: string; category?: string; subcategory?: string; tags?: Record<string, string[]> }>
}

export type SourceStatusResponse = {
  name: string
  phase: string
  last_sync_time: string
  records: number
  task_id: string
}

export type ObjectReferenceResponse = {
  name: string
  namespace: string
}

export type DataDescriptorResponse = {
  name: string
  namespace: string
  labels?: Record<string, string>
  descriptor_type: string
  gpuEnabled: "yes" | "no"
  pdfLoader?: "auto" | "ocr" | "text"
  sources: DataSourceResponse[]
  overall_phase?: string
  source_statuses?: SourceStatusResponse[]
  consumed_by?: ObjectReferenceResponse[]
  created_at: string
  updated_at: string
  deleting?: boolean
  deletion_timestamp?: string
}

/** GET /namespaces/:ns/descriptors list payload (after unwrap) */
export type DataDescriptorListResponse = {
  items: DataDescriptorResponse[]
  totalCount: number
  limit?: number
  offset?: number
}

/**
 * After axios envelope unwrap, signature/semantic-domain handlers still return
 * `{ data: T }` (see dac-apiserver dto.DataDescriptorSignatureResponse).
 */
export type NestedDataEnvelope<T> = {
  data?: T | null
}

/** Signature record fields used by the data-source detail UI */
export type DataDescriptorSignature = {
  sig_id?: string
  sig_type?: string
  discovery_mode?: string
  fingerprint?: string
  location_info?: Record<string, unknown>
  metadata_content?: Record<string, unknown>
  dd_namespace?: string
  dd_name?: string
  created_at?: string
  updated_at?: string
}

/** Semantic domain record for a data descriptor */
export type DataDescriptorSemanticDomain = {
  semantic_domain_id?: string
  semantic_domain?: string
  agent_card?: string
  dd_namespace?: string
  dd_name?: string
  created_at?: string
  updated_at?: string
}

// ----- Knowledge graph (internal/handler/dto/knowledge_graph.go + data-services) -----

export type KnowledgeGraphNode = {
  id: string
  name?: string
  labels?: string[]
  properties?: Record<string, unknown>
}

export type KnowledgeGraphRelationship = {
  start: string
  end: string
  type: string
  properties?: Record<string, unknown>
}

/** POST /knowledge-graph/get-graph-by-source response (after unwrap) */
export type KnowledgeGraphBySourceResponse = {
  labels?: string[]
  data_source?: string
  source?: string
  nodes?: KnowledgeGraphNode[]
  relationships?: KnowledgeGraphRelationship[]
}

/** POST /knowledge-graph/get-graph-by-source request body */
export type GetKnowledgeGraphBySourceRequest = {
  source: string
  node_limit?: number
  rel_limit?: number
}

// ----- Namespaces (internal/handler/dto/namespace.go) -----

export type NamespaceResponse = {
  name: string
}

export type NamespaceListResponse = {
  items: NamespaceResponse[]
}

// ----- Chat (dac-apiserver: SSE event "progress", payload from [[DAC_PROGRESS]] JSON) -----

/**
 * Progress event payload: raw JSON sent after `event: progress` in the chat SSE stream.
 * Backend forwards whatever the A2A agent emits after `[[DAC_PROGRESS]]` (no fixed schema).
 *
 * Known optional fields (for display and typing):
 * - `event`, `message`, `agent_id`, `task`, `agent` (display)
 * - `layer`, `status`, `run_id`, etc. (opaque; allow via index signature)
 */
export interface ChatProgressPayload {
  event?: string
  layer?: string
  message?: string
  agent_id?: string
  task?: string
  agent?: string
  [key: string]: unknown
}

export type ConversationResponse = {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export type ListConversationsResponse = {
  items: ConversationResponse[]
  total: number
}

// ----- Skill Hub (internal/handler/dto/skill_hub.go) -----

export type SkillInfoResponse = {
  name: string
  namespace: string
  description: string
  version: string
  filename: string
  availableVersions: string[]
}

export type SkillScriptInfoResponse = {
  scriptName: string
  interpreter: string
}

/** Full skill pack fields from GET /skills/namespaces/:ns/skills/:name. */
export type SkillDetailResponse = {
  name: string
  namespace: string
  description: string
  /** SKILL.md body after frontmatter. */
  detail: string
  version: string
  filename: string
  availableVersions: string[]
  /** Empty means unrestricted (skill_sdk / runner semantics). */
  allowedTools: string[]
  scripts: SkillScriptInfoResponse[]
  resourceDirs: string[]
}

export type SkillListResponse = {
  items: SkillInfoResponse[]
  totalCount: number
  namespace?: string
}

export type SkillNamespaceResponse = {
  id: string
  visibility: string
}

export type SkillNamespaceListResponse = {
  items: SkillNamespaceResponse[]
  totalCount: number
}

export type SkillNamespaceExistsResponse = {
  namespace: string
  exists: boolean
}

/** Create a skill from form fields (skill-hub packs SKILL.md + _meta.json). */
export type CreateSkillRequest = {
  name: string
  description: string
  detail?: string
  version?: string
  allowedTools?: string[]
}

// ----- Agent registry (internal/handler/dto/agent_registry.go) -----

export type AgentRegistrySummaryResponse = {
  name: string
  base_url: string
  agent_count: number
  reachable: boolean
  error?: string
}

export type AgentRegistryListResponse = {
  items: AgentRegistrySummaryResponse[]
  totalCount: number
}

export type RegisteredAgentCardResponse = {
  registry: string
  card: Record<string, unknown>
}

export type RegisteredAgentListResponse = {
  items: RegisteredAgentCardResponse[]
  totalCount: number
  registry: string
}

// ----- TDB pipeline (internal/handler/dto/tdb_pipeline.go) -----

/** One selectable TDB ingestion target. `gateway_url` is the same TDB gateway
 *  the named `skill_agent` queries, so ingestion and Q&A share one database. */
export type TDBPipelineTarget = {
  id: string
  domain: string
  label: string
  gateway_url: string
  domain_profile: string
  skill_agent?: string
  test: boolean
}

export type TDBPipelineDefaults = {
  collection: string
  image: string
  llm_profile: string
  runs_prefix: string
  status_prefix: string
  attempt_status_prefix: string
}

export type TDBPipelineOptionsResponse = {
  targets: TDBPipelineTarget[]
  images: string[]
  llm_profiles: string[]
  defaults: TDBPipelineDefaults
}

export type TDBPipelineCounters = {
  total_jobs: number
  queued: number
  starting: number
  running: number
  uploading: number
  succeeded: number
  failed: number
  canceled: number
}

export type TDBPipelineRun = {
  run_id: string
  status: string
  collection: string
  source_type: string
  source_uri: string
  gateway_url: string
  domain: string
  domain_profile: string
  image: string
  llm_profile: string
  idempotency_key: string
  created_by: string
  created_at: string
  updated_at: string
  counters: TDBPipelineCounters
  metadata?: Record<string, unknown>
  /** Set when the controller could not be reached; the row shows last known values. */
  summary_error?: string
}

export type TDBPipelineRunListResponse = {
  items: TDBPipelineRun[]
  totalCount: number
}

export type TDBPipelineActionResponse = {
  run_id: string
  status: string
  deleted_jobs?: string[]
  retried_jobs?: number
  requested_uploads?: number
}

/** Create-run body. Only `source` and `target.target_id` are required; the
 *  deployment's defaults fill in collection, image, profile and prefixes. */
export type CreateTDBPipelineRunRequest = {
  source: {
    type: "s3" | "pvc"
    uri?: string
    claim_name?: string
    path?: string
  }
  target: {
    target_id?: string
    domain?: string
    gateway_url?: string
    domain_profile?: string
  }
  collection?: string
  image?: string
  options?: {
    llm_profile?: string
    generate_qa?: boolean
    auto_eval?: boolean
    llm_grade?: boolean
    open_layer_predicate_merge_every?: number
    open_layer_predicate_autopromote?: boolean
    /** Accepted and stored by the controller, but not yet enforced. */
    max_concurrent?: number
    /** Accepted and stored by the controller, but not yet enforced. */
    start_stagger_seconds?: number
    /** Accepted and stored by the controller, but not yet enforced. */
    start_stagger_jitter_seconds?: number
    question_workers?: number
    question_repair_timeout_seconds?: number
  }
  artifact_upload?: {
    runs_prefix?: string
    status_prefix?: string
    attempt_status_prefix?: string
    /** Accepted and stored by the controller, but not yet wired to S3_BEST_EFFORT. */
    strict?: boolean
  }
  /** Optional; the controller's callback host allowlist is fail-closed. */
  callback?: {
    url: string
    events?: string[]
  }
  metadata?: Record<string, unknown>
  dataset_id?: string
  source_version?: string
  idempotency_key?: string
}

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

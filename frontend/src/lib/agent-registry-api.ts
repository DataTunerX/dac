/**
 * Agent registry observability API.
 */
import { api } from "@/lib/api"
import type {
  AgentRegistryListResponse,
  RegisteredAgentListResponse,
} from "@/lib/api-types"

export type AgentRegistryName = "orchestrator-registry" | "biz-orchestrator-registry"

export const AGENT_REGISTRY_NAMES: AgentRegistryName[] = [
  "orchestrator-registry",
  "biz-orchestrator-registry",
]

export async function listAgentRegistries(): Promise<AgentRegistryListResponse> {
  const res = await api.get<AgentRegistryListResponse>("/observability/agent-registries")
  return res.data
}

export async function listRegisteredAgents(
  registry: AgentRegistryName
): Promise<RegisteredAgentListResponse> {
  const res = await api.get<RegisteredAgentListResponse>(
    `/observability/agent-registries/${encodeURIComponent(registry)}/agents`
  )
  return res.data
}

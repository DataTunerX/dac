/**
 * Typed API for agents (agent containers). Uses @/lib/api; response interceptor unwraps envelope.
 */
import { api } from "@/lib/api"
import type {
  AgentContainerResponse,
  AgentContainerListResponse,
} from "@/lib/api-types"

export async function listAgentsAll(params?: {
  limit?: number
  offset?: number
}): Promise<AgentContainerListResponse> {
  const res = await api.get<AgentContainerListResponse>("/agents", { params })
  return res.data
}

/** Paginate through all agent containers (cluster-wide list). */
export async function listAllAgentContainers(): Promise<AgentContainerResponse[]> {
  const limit = 200
  let offset = 0
  const out: AgentContainerResponse[] = []

  for (;;) {
    const page = await listAgentsAll({ limit, offset })
    const items = page.items ?? []
    out.push(...items)

    const total = Number(page.totalCount ?? 0)
    if (items.length === 0 || out.length >= total || items.length < limit) {
      return out
    }
    offset += limit
  }
}

export async function listAgentsInNamespace(
  namespace: string,
  params?: { limit?: number; offset?: number; labelSelector?: string; fieldSelector?: string }
): Promise<AgentContainerListResponse> {
  const res = await api.get<AgentContainerListResponse>(
    `/namespaces/${encodeURIComponent(namespace)}/agents`,
    { params }
  )
  return res.data
}

export async function getAgent(
  namespace: string,
  name: string
): Promise<AgentContainerResponse> {
  const res = await api.get<AgentContainerResponse>(
    `/namespaces/${encodeURIComponent(namespace)}/agents/${encodeURIComponent(name)}`
  )
  return res.data
}

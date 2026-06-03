import { api } from "@/lib/api"
import { getDescriptor } from "@/lib/descriptors-api"
import { listAgentsAll } from "@/lib/agents-api"
import type {
  AgentContainerResponse,
  DDGroupRelationResponse,
  SemanticDomainResponse,
  SemanticGroupResponse,
} from "@/lib/api-types"

export type DataDescriptorDependency = {
  kind: "agent" | "group" | "dac"
  name: string
  namespace: string
  id?: string
}

export function getDataDescriptorDependencyKindLabel(kind: DataDescriptorDependency["kind"]) {
  switch (kind) {
    case "agent":
      return "智能体"
    case "group":
      return "语义组"
    case "dac":
      return "DAC"
  }
}

type SemanticDomainSearchResponse = {
  items?: SemanticDomainResponse[]
}

type DDGroupRelationListResponse = {
  items?: DDGroupRelationResponse[]
}

export type DescriptorGroupRelation = {
  relationId: number
  groupId: string
  groupName: string
  sdId: string
}

export async function listDescriptorGroupRelations(
  namespace: string,
  name: string
): Promise<DescriptorGroupRelation[]> {
  const semanticDomainRes = await api.post<SemanticDomainSearchResponse>("/semantic-domains/search/by-dd", {
    dd_namespace: namespace,
    dd_name: name,
  })
  const semanticDomains = semanticDomainRes.data?.items ?? []
  if (semanticDomains.length === 0) return []

  const groupNameCache = new Map<string, string>()
  const out: DescriptorGroupRelation[] = []
  const seen = new Set<number>()

  for (const sd of semanticDomains) {
    const sdId = sd.semantic_domain_id
    if (!sdId) continue
    const res = await api.get<DDGroupRelationListResponse>(
      `/dd-group-relations/sd/${encodeURIComponent(sdId)}`
    )
    for (const relation of res.data?.items ?? []) {
      if (!relation.id || !relation.group_id) continue
      if (seen.has(relation.id)) continue
      seen.add(relation.id)

      let groupName = groupNameCache.get(relation.group_id)
      if (!groupName) {
        try {
          const groupRes = await api.get<SemanticGroupResponse>(
            `/semantic-groups/${encodeURIComponent(relation.group_id)}`
          )
          groupName = groupRes.data?.group_name || relation.group_id
        } catch {
          groupName = relation.group_id
        }
        groupNameCache.set(relation.group_id, groupName)
      }

      out.push({
        relationId: relation.id,
        groupId: relation.group_id,
        groupName,
        sdId,
      })
    }
  }

  return out
}

/** Detach a descriptor from semantic groups by deleting dd_group_relation rows (path D). */
export async function detachDataDescriptorFromSemanticGroups(
  namespace: string,
  name: string,
  options?: { groupIds?: string[] }
): Promise<number> {
  let relations = await listDescriptorGroupRelations(namespace, name)
  if (options?.groupIds?.length) {
    const allowed = new Set(options.groupIds)
    relations = relations.filter((relation) => allowed.has(relation.groupId))
  }

  for (const relation of relations) {
    await api.delete(`/dd-group-relations/${encodeURIComponent(String(relation.relationId))}`)
  }
  return relations.length
}

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

async function listGroupsForDescriptor(namespace: string, name: string): Promise<DataDescriptorDependency[]> {
  const semanticDomainRes = await api.post<SemanticDomainSearchResponse>("/semantic-domains/search/by-dd", {
    dd_namespace: namespace,
    dd_name: name,
  })
  const semanticDomains = semanticDomainRes.data?.items ?? []
  const semanticDomainIds = semanticDomains
    .map((item) => item.semantic_domain_id)
    .filter((id): id is string => Boolean(id))

  if (semanticDomainIds.length === 0) return []

  const relationResults = await Promise.all(
    semanticDomainIds.map(async (semanticDomainId) => {
      const res = await api.get<DDGroupRelationListResponse>(
        `/dd-group-relations/sd/${encodeURIComponent(semanticDomainId)}`
      )
      return res.data?.items ?? []
    })
  )

  const groupIds = Array.from(
    new Set(
      relationResults
        .flat()
        .map((relation) => relation.group_id)
        .filter((id): id is string => Boolean(id))
    )
  )

  const groups = await Promise.all(
    groupIds.map(async (groupId) => {
      try {
        const res = await api.get<SemanticGroupResponse>(`/semantic-groups/${encodeURIComponent(groupId)}`)
        const group = res.data
        return {
          kind: "group" as const,
          name: group.group_name || group.id || groupId,
          namespace: "-",
          id: group.id || groupId,
        }
      } catch {
        return {
          kind: "group" as const,
          name: groupId,
          namespace: "-",
          id: groupId,
        }
      }
    })
  )

  return groups
}

export async function listDataDescriptorDependencies(
  namespace: string,
  name: string
): Promise<DataDescriptorDependency[]> {
  const deps: DataDescriptorDependency[] = []

  // 1) Best-effort: backend may expose direct DAC consumers on descriptor status.
  try {
    const desc = await getDescriptor(namespace, name)
    for (const consumer of desc.consumed_by ?? []) {
      if (!consumer.name) continue
      deps.push({
        kind: "dac",
        name: consumer.name,
        namespace: consumer.namespace ?? "default",
      })
    }
  } catch {
    // Keep dependency checks best-effort so a missing optional surface doesn't block normal deletion.
  }

  // 2) Agents can reference the DD before status.consumed_by catches up.
  try {
    const items = await listAllAgentContainers()
    for (const agent of items) {
      const agentName = agent.name ?? ""
      const agentNamespace = agent.namespace ?? "default"
      if (!agentName) continue

      const selectedSources = agent.dataPolicy?.sourceNameSelector ?? []
      const activeDescriptors = agent.activeDataDescriptors ?? []
      const selected = agentNamespace === namespace && selectedSources.some((source) => source === name)
      const active = activeDescriptors.some(
        (item) => item.name === name && (item.namespace ?? "default") === namespace
      )

      if (selected || active) {
        deps.push({ kind: "agent", name: agentName, namespace: agentNamespace })
      }
    }
  } catch {
    // Ignore agent lookup failures and keep the remaining dependency evidence.
  }

  // 3) Semantic groups depend on DDs through semantic-domain -> dd-group-relation.
  try {
    deps.push(...await listGroupsForDescriptor(namespace, name))
  } catch {
    // Ignore group lookup failures for the same best-effort behavior as agent/DAC checks.
  }

  const unique = new Map<string, DataDescriptorDependency>()
  for (const dep of deps) {
    const key = dep.kind === "group" ? `${dep.kind}/${dep.id ?? dep.name}` : `${dep.kind}/${dep.namespace}/${dep.name}`
    if (!unique.has(key)) unique.set(key, dep)
  }
  return Array.from(unique.values())
}

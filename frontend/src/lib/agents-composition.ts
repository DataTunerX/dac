import type { AgentContainerResponse } from "@/lib/api-types"

export type MemberDescriptorBucket = {
  key: string
  dd_namespace: string
  dd_name: string
  hasDD: boolean
}

export type CompositionDataAgent = {
  key: string
  namespace: string
  name: string
  displayName: string
  coveredDescriptors: Array<{ namespace: string; name: string }>
}

export function isBusinessAgentContainer(a: AgentContainerResponse): boolean {
  const dp = a.dataPolicy
  if (!dp) return false
  const type = dp.dataSourceType ?? ""
  const sgId = dp.semanticGroupID ?? ""
  return type === "SemanticGroup" || (Boolean(sgId) && type !== "SemanticDomain")
}

export function agentCoversDescriptor(
  a: AgentContainerResponse,
  ddNamespace: string,
  ddName: string,
): boolean {
  const ans = a.namespace ?? "default"
  const sel = a.dataPolicy?.sourceNameSelector ?? []
  if (ans === ddNamespace && sel.some((s) => s === ddName)) return true
  return (a.activeDataDescriptors ?? []).some(
    (d) => d.name === ddName && (d.namespace ?? "default") === ddNamespace,
  )
}

export function buildCompositionDataAgents(
  allAgents: AgentContainerResponse[],
  members: MemberDescriptorBucket[],
  exclude: { namespace: string; name: string },
): CompositionDataAgent[] {
  const resolvedMembers = members.filter((m) => m.hasDD)
  if (resolvedMembers.length === 0) return []

  const byKey = new Map<string, CompositionDataAgent>()
  for (const container of allAgents) {
    const an = container.name ?? ""
    const ans = container.namespace ?? "default"
    if (!an || isBusinessAgentContainer(container)) continue
    if (ans === exclude.namespace && an === exclude.name) continue

    const covered: Array<{ namespace: string; name: string }> = []
    for (const m of resolvedMembers) {
      if (agentCoversDescriptor(container, m.dd_namespace, m.dd_name)) {
        covered.push({ namespace: m.dd_namespace, name: m.dd_name })
      }
    }
    if (covered.length === 0) continue

    const key = `${ans}/${an}`
    const displayName =
      (typeof container.agentCard?.name === "string" && container.agentCard.name) || an
    const existing = byKey.get(key)
    if (existing) {
      const seen = new Set(existing.coveredDescriptors.map((d) => `${d.namespace}/${d.name}`))
      for (const d of covered) {
        const dk = `${d.namespace}/${d.name}`
        if (!seen.has(dk)) {
          seen.add(dk)
          existing.coveredDescriptors.push(d)
        }
      }
    } else {
      byKey.set(key, {
        key,
        namespace: ans,
        name: an,
        displayName,
        coveredDescriptors: covered,
      })
    }
  }

  return Array.from(byKey.values()).sort((a, b) => a.displayName.localeCompare(b.displayName))
}

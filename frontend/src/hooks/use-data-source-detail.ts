"use client"

import { useMemo } from "react"
import useSWR from "swr"
import axios from "axios"
import {
  getDescriptor,
  getDescriptorSemanticDomain,
  getDescriptorSignature,
} from "@/lib/descriptors-api"
import { listAllAgentContainers } from "@/lib/agents-api"
import type {
  DataDescriptorResponse,
  DataDescriptorSemanticDomain,
  DataDescriptorSignature,
  ObjectReferenceResponse,
} from "@/lib/api-types"
import {
  AGENTS_LIST_KEY,
  descriptorKey,
  descriptorSemanticDomainKey,
  descriptorSignatureKey,
} from "@/lib/swr-keys"

export type LineageConsumer = {
  kind: "agent" | "unknown"
  name: string
  namespace: string
}

export type UseDataSourceDetailOptions = {
  /** When true, fetch AGENTS_LIST_KEY to enrich lineage (lineage tab). */
  includeAgentLineage?: boolean
}

async function fetchDescriptorOrNull(
  namespace: string,
  name: string,
): Promise<DataDescriptorResponse | null> {
  try {
    return await getDescriptor(namespace, name)
  } catch (e) {
    if (axios.isAxiosError(e) && e.response?.status === 404) return null
    throw e
  }
}

function deriveAgentConsumers(
  items: Awaited<ReturnType<typeof listAllAgentContainers>> | undefined,
  namespace: string,
  name: string,
): LineageConsumer[] {
  if (!items) return []
  const deps: LineageConsumer[] = []
  for (const a of items) {
    const an = a.name ?? ""
    const ans = a.namespace ?? "default"
    if (!an) continue
    let hit = false
    const sel = a.dataPolicy?.sourceNameSelector ?? []
    if (ans === namespace && sel.some((x) => x === name)) hit = true
    const ads = a.activeDataDescriptors ?? []
    if (ads.some((x) => x.name === name && (x.namespace ?? "default") === namespace)) {
      hit = true
    }
    if (hit) deps.push({ kind: "agent", name: an, namespace: ans })
  }
  const uniq = new Map<string, LineageConsumer>()
  for (const d of deps) {
    const k = `${d.kind}/${d.namespace}/${d.name}`
    if (!uniq.has(k)) uniq.set(k, d)
  }
  return Array.from(uniq.values())
}

export function isDescriptorNotFound(
  dd: DataDescriptorResponse | null | undefined,
  error: unknown,
): boolean {
  if (dd !== null) return false
  if (!error) return true
  return axios.isAxiosError(error) && error.response?.status === 404
}

export function useDataSourceDetail(
  namespace: string,
  name: string,
  options: UseDataSourceDetailOptions = {},
) {
  const includeAgentLineage = Boolean(options.includeAgentLineage)
  const enabled = Boolean(namespace && name)

  const {
    data: dd,
    error: descriptorError,
    mutate: mutateDescriptor,
  } = useSWR(
    enabled ? descriptorKey(namespace, name) : null,
    ([, ns, nm]: readonly [string, string, string]) => fetchDescriptorOrNull(ns, nm),
  )

  const {
    data: signature,
    mutate: mutateSignature,
  } = useSWR(
    enabled ? descriptorSignatureKey(namespace, name) : null,
    ([, ns, nm]: readonly [string, string, string]) => getDescriptorSignature(ns, nm),
  )

  const {
    data: semanticDomain,
    mutate: mutateSemanticDomain,
  } = useSWR(
    enabled ? descriptorSemanticDomainKey(namespace, name) : null,
    ([, ns, nm]: readonly [string, string, string]) => getDescriptorSemanticDomain(ns, nm),
  )

  const { data: allAgents, mutate: mutateAgents } = useSWR(
    enabled && includeAgentLineage ? AGENTS_LIST_KEY : null,
    () => listAllAgentContainers(),
  )

  const agentConsumers = useMemo(
    () => deriveAgentConsumers(allAgents, namespace, name),
    [allAgents, namespace, name],
  )

  const lineageConsumers = useMemo(() => {
    const fromConsumedBy: LineageConsumer[] = []
    if (Array.isArray(dd?.consumed_by)) {
      for (const c of dd.consumed_by as ObjectReferenceResponse[]) {
        const nm = c.name ?? ""
        if (!nm) continue
        fromConsumedBy.push({
          kind: "unknown",
          name: nm,
          namespace: c.namespace ?? "default",
        })
      }
    }

    const all = [...fromConsumedBy, ...agentConsumers]
    const uniq = new Map<string, LineageConsumer>()
    for (const d of all) {
      const k = `${d.kind}/${d.namespace}/${d.name}`
      if (!uniq.has(k)) uniq.set(k, d)
    }
    return Array.from(uniq.values())
  }, [dd?.consumed_by, agentConsumers])

  const refreshAll = async () => {
    await Promise.all([
      mutateDescriptor(),
      mutateSignature(),
      mutateSemanticDomain(),
      includeAgentLineage ? mutateAgents() : Promise.resolve(),
    ])
  }

  const isLoading = enabled && dd === undefined && !descriptorError
  const isNotFound = enabled && !isLoading && isDescriptorNotFound(dd, descriptorError)
  const isLoadError =
    enabled &&
    !isLoading &&
    Boolean(descriptorError) &&
    !(axios.isAxiosError(descriptorError) && descriptorError.response?.status === 404)

  return {
    dd: (dd ?? null) as DataDescriptorResponse | null,
    signature: (signature ?? null) as DataDescriptorSignature | null,
    semanticDomain: (semanticDomain ?? null) as DataDescriptorSemanticDomain | null,
    agentConsumers,
    lineageConsumers,
    descriptorError,
    isLoading,
    isNotFound,
    isLoadError,
    isLoadingSignature: enabled && signature === undefined,
    isLoadingSemanticDomain: enabled && semanticDomain === undefined,
    refreshAll,
    mutateDescriptor,
  }
}

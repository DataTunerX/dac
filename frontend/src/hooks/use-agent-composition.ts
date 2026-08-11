"use client"

import { useEffect, useMemo, useState } from "react"
import useSWR from "swr"
import { api } from "@/lib/api"
import { listAllAgentContainers } from "@/lib/agents-api"
import { getSemanticGroupWithMembers } from "@/lib/semantic-groups-api"
import type { DDGroupRelationResponse, SemanticGroupResponse } from "@/lib/api-types"
import {
  buildCompositionDataAgents,
  type CompositionDataAgent,
  type MemberDescriptorBucket,
} from "@/lib/agents-composition"
import { AGENTS_LIST_KEY, semanticGroupKey } from "@/lib/swr-keys"

type SdMetaEntry = { dd_namespace: string; dd_name: string } | "failed"
type SdMeta = Record<string, SdMetaEntry>

export function useAgentComposition(opts: {
  isSemanticGroupAgent: boolean
  semanticGroupID: string
  namespace: string
  name: string
}) {
  const { isSemanticGroupAgent, semanticGroupID, namespace, name } = opts

  const sgKey =
    isSemanticGroupAgent && semanticGroupID ? semanticGroupKey(semanticGroupID) : null
  const {
    data: sgPayload,
    isLoading: isLoadingSg,
    isValidating: isValidatingSg,
  } = useSWR(sgKey, ([, id]: readonly [string, string]) => getSemanticGroupWithMembers(id))

  const agentsKey = isSemanticGroupAgent ? AGENTS_LIST_KEY : null
  const {
    data: allAgents,
    isLoading: isLoadingAgents,
    isValidating: isValidatingAgents,
  } = useSWR(agentsKey, () => listAllAgentContainers())

  const semanticGroup: SemanticGroupResponse | null = sgPayload?.group ?? null

  const relations: DDGroupRelationResponse[] = useMemo(() => {
    const mems = sgPayload?.members ?? []
    return mems
      .map((m) => m.relation)
      .filter((r): r is DDGroupRelationResponse => Boolean(r && Number(r.id) > 0 && r.sd_id))
  }, [sgPayload?.members])

  const membersMeta = useMemo(() => {
    const meta: Record<string, { dd_namespace: string; dd_name: string }> = {}
    for (const m of sgPayload?.members ?? []) {
      const sd = m.semantic_domain
      const sid = m.relation?.sd_id
      if (sid && sd?.dd_namespace != null && sd?.dd_name != null) {
        meta[sid] = { dd_namespace: sd.dd_namespace, dd_name: sd.dd_name }
      }
    }
    return meta
  }, [sgPayload?.members])

  const [fallbackSdMeta, setFallbackSdMeta] = useState<SdMeta>({})

  useEffect(() => {
    if (!isSemanticGroupAgent) {
      setFallbackSdMeta({})
      return
    }
    let cancelled = false
    const missing = relations
      .map((r) => r.sd_id)
      .filter((id) => {
        if (!id || membersMeta[id]) return false
        const prev = fallbackSdMeta[id]
        // Skip ids already resolved successfully; retry "failed" when membership deps change
        return !(prev && typeof prev === "object")
      })
    if (missing.length === 0) return

    void (async () => {
      const results = await Promise.all(
        missing.map(async (id) => {
          try {
            const res = await api.get<{ dd_namespace?: string; dd_name?: string }>(
              `/semantic-domains/${encodeURIComponent(id)}`,
            )
            const r = res.data ?? {}
            const dd_namespace = typeof r.dd_namespace === "string" ? r.dd_namespace : ""
            const dd_name = typeof r.dd_name === "string" ? r.dd_name : ""
            if (!dd_namespace || !dd_name) return { id, entry: "failed" as const }
            return { id, entry: { dd_namespace, dd_name } as const }
          } catch {
            return { id, entry: "failed" as const }
          }
        }),
      )
      if (cancelled) return
      setFallbackSdMeta((prev) => {
        const next = { ...prev }
        for (const { id, entry } of results) next[id] = entry
        return next
      })
    })()

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- retry when membership changes; avoid loop on fallback writes
  }, [relations, isSemanticGroupAgent, membersMeta])

  const sdMeta = useMemo(() => {
    const out: Record<string, { dd_namespace: string; dd_name: string }> = { ...membersMeta }
    for (const [id, entry] of Object.entries(fallbackSdMeta)) {
      if (entry !== "failed" && entry.dd_namespace && entry.dd_name) {
        out[id] = entry
      }
    }
    return out
  }, [fallbackSdMeta, membersMeta])

  const memberDescriptors = useMemo((): MemberDescriptorBucket[] => {
    const map = new Map<string, MemberDescriptorBucket>()
    for (const r of relations) {
      const meta = sdMeta[r.sd_id]
      const hasDD = Boolean(meta?.dd_namespace && meta?.dd_name)
      if (!hasDD || !meta) continue
      const key = `${meta.dd_namespace}/${meta.dd_name}`
      map.set(key, {
        key,
        dd_namespace: meta.dd_namespace,
        dd_name: meta.dd_name,
        hasDD: true,
      })
    }
    return Array.from(map.values()).sort((a, b) => a.key.localeCompare(b.key))
  }, [relations, sdMeta])

  const compositionDataAgents: CompositionDataAgent[] = useMemo(() => {
    if (!isSemanticGroupAgent || !allAgents) return []
    return buildCompositionDataAgents(allAgents, memberDescriptors, { namespace, name })
  }, [isSemanticGroupAgent, allAgents, memberDescriptors, namespace, name])

  return {
    semanticGroup,
    relations,
    sdMeta,
    compositionDataAgents,
    memberDescriptors,
    isLoadingSg: Boolean(sgKey) && (isLoadingSg || isValidatingSg) && !sgPayload,
    isLoadingRelations: Boolean(sgKey) && (isLoadingSg || isValidatingSg) && !sgPayload,
    isLoadingCompositionAgents:
      Boolean(agentsKey) && (isLoadingAgents || isValidatingAgents) && !allAgents,
  }
}

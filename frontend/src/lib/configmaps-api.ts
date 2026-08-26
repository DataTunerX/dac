/**
 * Typed API for configmaps. Uses @/lib/api; response interceptor unwraps envelope.
 *
 * The API is split by type:
 *   - llm     → /api/v1/namespaces/{ns}/llm-configmaps
 *   - prompts → /api/v1/namespaces/{ns}/prompt-configmaps
 */
import { api } from "@/lib/api"
import type {
  ConfigMapResponse,
  ConfigMapListResponse,
} from "@/lib/api-types"

type ConfigMapType = "llm" | "prompts"

function pathForType(ns: string, type: ConfigMapType): string {
  const suffix = type === "llm" ? "llm-configmaps" : "prompt-configmaps"
  return `/namespaces/${encodeURIComponent(ns)}/${suffix}`
}

export async function listConfigMaps(
  namespace: string,
  params?: { limit?: number; offset?: number; type?: string; labelSelector?: string }
): Promise<ConfigMapListResponse> {
  const t = (params?.type === "prompts" ? "prompts" : "llm") as ConfigMapType
  const res = await api.get<ConfigMapListResponse>(
    pathForType(namespace, t),
    { params: { ...params, type: undefined } }
  )
  return res.data
}

export async function getConfigMap(
  namespace: string,
  name: string,
  type?: string
): Promise<ConfigMapResponse> {
  const t = (type === "prompts" ? "prompts" : "llm") as ConfigMapType
  const res = await api.get<ConfigMapResponse>(
    `${pathForType(namespace, t)}/${encodeURIComponent(name)}`
  )
  return res.data
}

/** Paginate through all configmaps in a namespace (for client-side search). */
export async function listAllConfigMaps(
  namespace: string,
  params?: { type?: string }
): Promise<ConfigMapListResponse["items"]> {
  const t = (params?.type === "prompts" ? "prompts" : "llm") as ConfigMapType
  const limit = 200
  let offset = 0
  const out: NonNullable<ConfigMapListResponse["items"]> = []

  for (;;) {
    const page = await listConfigMaps(namespace, { type: t, limit, offset })
    const items = page.items ?? []
    out.push(...items)

    const total = Number(page.totalCount ?? 0)
    if (items.length === 0 || out.length >= total || items.length < limit) {
      return out
    }
    offset += limit
  }
}

/** Fetch all configmaps of a given type across all accessible namespaces. */
export async function listAllConfigMapsAcrossNamespaces(
  namespaces: string[],
  params?: { type?: string }
): Promise<ConfigMapListResponse["items"]> {
  const t = (params?.type === "prompts" ? "prompts" : "llm") as ConfigMapType
  const results = await Promise.all(
    namespaces.map((ns) =>
      listAllConfigMaps(ns, { type: t }).catch(() => [] as ConfigMapListResponse["items"])
    )
  )
  return results.flat()
}
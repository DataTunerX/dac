/**
 * Typed API for configmaps. Uses @/lib/api; response interceptor unwraps envelope.
 */
import { api } from "@/lib/api"
import type {
  ConfigMapResponse,
  ConfigMapListResponse,
} from "@/lib/api-types"

export async function listConfigMaps(
  namespace: string,
  params?: { limit?: number; offset?: number; type?: string; labelSelector?: string }
): Promise<ConfigMapListResponse> {
  const res = await api.get<ConfigMapListResponse>(
    `/namespaces/${encodeURIComponent(namespace)}/configmaps`,
    { params }
  )
  return res.data
}

export async function getConfigMap(
  namespace: string,
  name: string
): Promise<ConfigMapResponse> {
  const res = await api.get<ConfigMapResponse>(
    `/namespaces/${encodeURIComponent(namespace)}/configmaps/${encodeURIComponent(name)}`
  )
  return res.data
}

/** Paginate through all configmaps in a namespace (for client-side search). */
export async function listAllConfigMaps(
  namespace: string,
  params?: { type?: string }
): Promise<ConfigMapListResponse["items"]> {
  const limit = 200
  let offset = 0
  const out: NonNullable<ConfigMapListResponse["items"]> = []

  for (;;) {
    const page = await listConfigMaps(namespace, { ...params, limit, offset })
    const items = page.items ?? []
    out.push(...items)

    const total = Number(page.totalCount ?? 0)
    if (items.length === 0 || out.length >= total || items.length < limit) {
      return out
    }
    offset += limit
  }
}

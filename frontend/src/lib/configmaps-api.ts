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

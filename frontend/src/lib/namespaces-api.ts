/**
 * Typed API for namespaces. Uses @/lib/api; response interceptor unwraps envelope.
 */
import { api } from "@/lib/api"
import type { NamespaceListResponse } from "@/lib/api-types"

export async function listNamespaces(): Promise<NamespaceListResponse> {
  const res = await api.get<NamespaceListResponse>("/namespaces")
  return res.data
}

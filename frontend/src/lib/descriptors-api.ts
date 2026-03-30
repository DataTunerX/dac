/**
 * Typed API for data descriptors. Uses @/lib/api; response interceptor unwraps envelope.
 */
import { api } from "@/lib/api"
import type {
  DataDescriptorResponse,
  DataDescriptorListResponse,
} from "@/lib/api-types"

export async function listDescriptorsAll(params?: {
  limit?: number
  offset?: number
}): Promise<DataDescriptorListResponse> {
  const res = await api.get<DataDescriptorListResponse>("/descriptors", { params })
  return res.data
}

export async function listDescriptorsInNamespace(
  namespace: string,
  params?: { limit?: number; offset?: number }
): Promise<DataDescriptorListResponse> {
  const res = await api.get<DataDescriptorListResponse>(
    `/namespaces/${encodeURIComponent(namespace)}/descriptors`,
    { params }
  )
  return res.data
}

export async function getDescriptor(
  namespace: string,
  name: string
): Promise<DataDescriptorResponse> {
  const res = await api.get<DataDescriptorResponse>(
    `/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}`
  )
  return res.data
}

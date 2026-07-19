/**
 * Typed API for data descriptors. Uses @/lib/api; response interceptor unwraps envelope.
 */
import axios from "axios"
import { api } from "@/lib/api"
import type {
  DataDescriptorResponse,
  DataDescriptorListResponse,
  DataDescriptorSignature,
  DataDescriptorSemanticDomain,
  NestedDataEnvelope,
} from "@/lib/api-types"
import { unwrapNestedData } from "@/lib/unwrap-nested-data"

export async function listDescriptorsAll(params?: {
  limit?: number
  offset?: number
}): Promise<DataDescriptorListResponse> {
  const res = await api.get<DataDescriptorListResponse>("/descriptors", { params })
  return res.data
}

/** Paginate through all data descriptors (cluster-wide list). */
export async function listAllDescriptors(): Promise<DataDescriptorListResponse["items"]> {
  const limit = 200
  let offset = 0
  const out: NonNullable<DataDescriptorListResponse["items"]> = []

  for (;;) {
    const page = await listDescriptorsAll({ limit, offset })
    const items = page.items ?? []
    out.push(...items)

    const total = Number(page.totalCount ?? 0)
    if (items.length === 0 || out.length >= total || items.length < limit) {
      return out
    }
    offset += limit
  }
}

export async function listDescriptorsInNamespace(
  namespace: string,
  params?: { limit?: number; offset?: number },
): Promise<DataDescriptorListResponse> {
  const res = await api.get<DataDescriptorListResponse>(
    `/namespaces/${encodeURIComponent(namespace)}/descriptors`,
    { params },
  )
  return res.data
}

export async function getDescriptor(
  namespace: string,
  name: string,
): Promise<DataDescriptorResponse> {
  const res = await api.get<DataDescriptorResponse>(
    `/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}`,
  )
  return res.data
}

/** GET .../signature — returns null on 404. */
export async function getDescriptorSignature(
  namespace: string,
  name: string,
): Promise<DataDescriptorSignature | null> {
  try {
    const res = await api.get<NestedDataEnvelope<DataDescriptorSignature>>(
      `/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}/signature`,
    )
    return unwrapNestedData<DataDescriptorSignature>(res.data)
  } catch (e) {
    if (axios.isAxiosError(e) && e.response?.status === 404) return null
    throw e
  }
}

/** GET .../semantic-domain — returns null on 404. */
export async function getDescriptorSemanticDomain(
  namespace: string,
  name: string,
): Promise<DataDescriptorSemanticDomain | null> {
  try {
    const res = await api.get<NestedDataEnvelope<DataDescriptorSemanticDomain>>(
      `/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}/semantic-domain`,
    )
    return unwrapNestedData<DataDescriptorSemanticDomain>(res.data)
  } catch (e) {
    if (axios.isAxiosError(e) && e.response?.status === 404) return null
    throw e
  }
}

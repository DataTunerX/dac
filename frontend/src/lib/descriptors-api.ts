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

/** DELETE /namespaces/:ns/descriptors/:name */
export async function deleteDescriptor(namespace: string, name: string): Promise<void> {
  await api.delete(
    `/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}`,
  )
}

/**
 * Poll until the descriptor is gone (404). Needed before recreate-with-same-name
 * because DataDescriptor deletion is async (finalizers / sinker cleanup).
 */
export async function waitUntilDescriptorGone(
  namespace: string,
  name: string,
  opts?: { timeoutMs?: number; intervalMs?: number },
): Promise<void> {
  const timeoutMs = opts?.timeoutMs ?? 90_000
  const intervalMs = opts?.intervalMs ?? 1_000
  const started = Date.now()

  for (;;) {
    try {
      await getDescriptor(namespace, name)
    } catch (e) {
      if (axios.isAxiosError(e) && e.response?.status === 404) return
      throw e
    }
    if (Date.now() - started >= timeoutMs) {
      throw new Error("删除超时：数据源仍未清理完成，请稍后重试")
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

/** PUT /namespaces/:ns/descriptors/:name — replace mutable fields. */
export type UpdateDescriptorRequest = {
  labels?: Record<string, string>
  descriptorType?: string
  gpuEnabled?: string
  pdfLoader?: string
  sources?: Array<{
    name: string
    type: string
    metadata?: Record<string, string>
    prompts?: { configMapName?: string }
    codeRepo?: {
      codeRepoType?: string
      codeRepoPath?: string
      codeRepoBranch?: string
      codeRepoToken?: string
    }
    extract?: { tables?: string[]; querys?: string[]; files?: string[] }
    processing?: { cleaning?: Array<{ rule: string; params?: Record<string, string> }> }
  }>
}

export async function updateDescriptor(
  namespace: string,
  name: string,
  body: UpdateDescriptorRequest,
): Promise<DataDescriptorResponse> {
  const res = await api.put<DataDescriptorResponse>(
    `/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}`,
    body,
  )
  return res.data
}

/**
 * Ask execution-engine to re-run ingestion for a Ready DataDescriptor
 * (sets dac.dac.io/sync-requested-at).
 */
export async function requestDescriptorResync(namespace: string, name: string): Promise<void> {
  await api.post(
    `/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}/resync`,
  )
}

/**
 * Append database sources then trigger resync — no delete/recreate window.
 */
export async function appendDescriptorSourcesAndResync(
  namespace: string,
  name: string,
  sources: NonNullable<UpdateDescriptorRequest["sources"]>,
  opts?: { gpuEnabled?: string; descriptorType?: string },
): Promise<DataDescriptorResponse> {
  const updated = await updateDescriptor(namespace, name, {
    sources,
    ...(opts?.gpuEnabled ? { gpuEnabled: opts.gpuEnabled } : {}),
    ...(opts?.descriptorType ? { descriptorType: opts.descriptorType } : {}),
  })
  await requestDescriptorResync(namespace, name)
  return updated
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

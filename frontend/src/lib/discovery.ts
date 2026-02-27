import { api } from "@/lib/api"

export type DiscoveryJobStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED"

export interface DiscoveredService {
  host: string
  port: number
  protocol: string
  serviceType: string
  product?: string
  version?: string
  tls: boolean
  metadata?: Record<string, string>
}

export interface StartDiscoveryScanRequest {
  target: string
  portsSpec?: string
  timeoutMs?: number
  concurrency?: number
}

export interface StartDiscoveryScanResponse {
  id: string
  status: DiscoveryJobStatus
}

export interface DiscoveryJobResponse {
  id: string
  name?: string
  target: string
  portsSpec?: string
  status: DiscoveryJobStatus
  error?: string
  startedAt?: number
  finishedAt?: number
  services?: DiscoveredService[]
}

export interface ListDiscoveryScansResponse {
  items: DiscoveryJobResponse[]
  totalCount: number
}

export interface ListDiscoveryScansRequest {
  target?: string
  status?: DiscoveryJobStatus
  limit?: number
  offset?: number
}

// NOTE: The api interceptor in @/lib/api.ts automatically unwraps the "data" field from the response envelope.
// So res.data is already the inner data object (e.g. ListDiscoveryScansResponse), not ApiEnvelope.

export async function startDiscoveryScan(req: StartDiscoveryScanRequest): Promise<StartDiscoveryScanResponse> {
  const res = await api.post<StartDiscoveryScanResponse>("/discovery/scans", req)
  return res.data
}

export async function getDiscoveryScan(id: string): Promise<DiscoveryJobResponse> {
  const res = await api.get<DiscoveryJobResponse>(`/discovery/scans/${encodeURIComponent(id)}`)
  return res.data
}

export async function listDiscoveryScans(req: ListDiscoveryScansRequest = {}): Promise<ListDiscoveryScansResponse> {
  const res = await api.get<ListDiscoveryScansResponse>("/discovery/scans", { params: req })
  return res.data
}

export async function updateDiscoveryScan(id: string, name: string): Promise<DiscoveryJobResponse> {
  const res = await api.patch<DiscoveryJobResponse>(`/discovery/scans/${encodeURIComponent(id)}`, { name })
  return res.data
}

export async function deleteDiscoveryScan(id: string): Promise<void> {
  await api.delete(`/discovery/scans/${encodeURIComponent(id)}`)
}

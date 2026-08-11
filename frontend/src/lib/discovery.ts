import { api } from "@/lib/api"
import type { DataSourceResponse } from "@/lib/api-types"

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

const CODE_REPO_TYPES = new Set(["gitlab", "github", "gitee", "git", "coderepo"])

const normalize = (s?: string) => (s || "").trim().toLowerCase()

/** Split "host:port" (IPv4 / hostname) into parts. Leaves host untouched when no port. */
export function splitHostPort(
  hostRaw: string,
  portRaw?: string
): { host: string; port: string } | null {
  const hostStr = String(hostRaw ?? "").trim()
  const portStr = String(portRaw ?? "").trim()
  if (!hostStr) return null

  if (portStr) {
    return { host: hostStr, port: portStr }
  }

  // Combined host:port (MinIO). Avoid treating bare IPv6 as host:port.
  const colonIdx = hostStr.lastIndexOf(":")
  if (colonIdx > 0 && !hostStr.includes("]")) {
    const host = hostStr.slice(0, colonIdx).trim()
    const port = hostStr.slice(colonIdx + 1).trim()
    if (host && port && /^\d+$/.test(port)) {
      return { host, port }
    }
  }
  return null
}

/** Parse hostname + port from a codeRepoPath URL or host:port string. */
export function parseEndpointFromCodeRepoPath(
  path: string
): { host: string; port: string } | null {
  const raw = String(path ?? "").trim()
  if (!raw) return null

  const candidates = [raw]
  if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(raw)) {
    candidates.push(`http://${raw}`)
  }

  for (const candidate of candidates) {
    try {
      const u = new URL(candidate)
      const host = u.hostname
      if (!host) continue
      let port = u.port
      if (!port) {
        port = u.protocol === "https:" ? "443" : "80"
      }
      return { host, port }
    } catch {
      // try next candidate
    }
  }

  return splitHostPort(raw)
}

export type DataSourceEndpoint = {
  /** Canonical type used in connection identity (coderepo for git providers). */
  matchType: string
  host: string
  port: string
}

/** Extract a matchable endpoint from a persisted DataSource. */
export function extractDataSourceEndpoint(
  source: Pick<DataSourceResponse, "type" | "metadata" | "codeRepo">
): DataSourceEndpoint | null {
  const type = normalize(source.type)
  const meta = source.metadata ?? {}

  if (CODE_REPO_TYPES.has(type)) {
    const path =
      meta.codeRepoPath ||
      (typeof source.codeRepo?.codeRepoPath === "string" ? source.codeRepo.codeRepoPath : "") ||
      ""
    const ep = parseEndpointFromCodeRepoPath(path)
    if (!ep) return null
    return { matchType: "coderepo", host: ep.host, port: ep.port }
  }

  if (type === "minio") {
    const ep = splitHostPort(String(meta.host ?? ""), meta.port)
    if (!ep) return null
    return { matchType: "minio", host: ep.host, port: ep.port }
  }

  if (type === "mysql" || type === "mariadb" || type === "postgres" || type === "fileserver") {
    const ep = splitHostPort(String(meta.host ?? ""), meta.port)
    if (!ep) return null
    const matchType = type === "mariadb" ? "mysql" : type
    return { matchType, host: ep.host, port: ep.port }
  }

  // Fallback: require explicit host + port
  const ep = splitHostPort(String(meta.host ?? ""), meta.port)
  if (!ep) return null
  return { matchType: type || "unknown", host: ep.host, port: ep.port }
}

/** Connection identity: "type://host:port" (code repos use matchType coderepo). */
export function getConnectionIdentity(
  type: string,
  host: string,
  port: string | number
): string {
  let t = normalize(type)
  if (t === "mariadb") t = "mysql"
  if (CODE_REPO_TYPES.has(t)) t = "coderepo"

  const h = normalize(host)
  const p = String(port).trim()
  return `${t}://${h}:${p}`
}

/** True when the discovered service is MinIO Console (not the S3 API). */
export function isMinioConsole(s: DiscoveredService): boolean {
  const product = normalize(s.product)
  if (!product.includes("minio")) return false

  const server = normalize(s.metadata?.["http.server"] ?? s.metadata?.server)
  if (server.includes("console")) return true

  // Sandbox / common default: API 9000, Console 9001
  if (Number(s.port) === 9001) return true
  return false
}

export type DiscoveryCreateType = "mysql" | "postgres" | "minio" | "coderepo" | "fileserver"

/** Map a discovered service to the create-datasource form type, or null if unsupported. */
export function detectCreateType(s: DiscoveredService): DiscoveryCreateType | null {
  const st = normalize(s.serviceType)
  const product = normalize(s.product)

  if (st === "mysql" || product.includes("mysql") || product.includes("mariadb")) {
    return "mysql"
  }
  if (st === "postgres" || product.includes("postgres")) {
    return "postgres"
  }
  if (product.includes("minio")) {
    if (isMinioConsole(s)) return null
    return "minio"
  }
  if (
    product.includes("gitlab") ||
    product.includes("github") ||
    product.includes("gitee") ||
    (st === "http" && Number(s.port) === 8929)
  ) {
    return "coderepo"
  }
  if (product.includes("fileserver") || (product.includes("nginx") && Number(s.port) === 8000)) {
    return "fileserver"
  }
  return null
}

/** Canonical match type for a discovered service (aligned with extractDataSourceEndpoint). */
export function discoveryMatchType(s: DiscoveredService): string {
  const createType = detectCreateType(s)
  if (createType) return createType

  const st = normalize(s.serviceType)
  const product = normalize(s.product)
  // Console still matches as minio for identity if someone created against 9001 historically;
  // create is blocked separately via detectCreateType.
  if (product.includes("minio")) return "minio"
  if (product.includes("gitlab") || product.includes("github") || product.includes("gitee")) {
    return "coderepo"
  }
  if (st === "mariadb") return "mysql"
  return st || "unknown"
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

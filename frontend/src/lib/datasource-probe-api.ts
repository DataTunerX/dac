import { api } from "@/lib/api"

// ProbeRequest is the wire-format input mirroring the backend
// `dto.ProbeDataSourceRequest` (POST /api/v1/datasources/probe).
//
// We deliberately keep a 1:1 mapping with the backend DTO so a
// schema change on either side breaks loud and early during typecheck.
export type ProbeRequest = {
  type: string
  host: string
  port: number
  user?: string
  password?: string
}

export type ProbeResponse = {
  databases: string[]
  version?: string
  latencyMs: number
}

export type SupportedTypesResponse = {
  types: string[]
}

// probeDataSource synchronously asks the API server to open a short-lived
// connection to the target and report which catalogs/databases are reachable.
//
// Errors are surfaced as thrown axios errors; the caller decides how to
// translate them into UI state (toast, inline message, etc.). Treat the
// returned payload as authoritative — the backend already filters out
// system schemas.
export async function probeDataSource(req: ProbeRequest): Promise<ProbeResponse> {
  const res = await api.post<ProbeResponse>("/datasources/probe", req)
  return res.data
}

// listSupportedProbeTypes lets the UI render a probe-aware control without
// hard-coding the supported set; it stays in lockstep with the backend
// `ProberRegistry`.
export async function listSupportedProbeTypes(): Promise<string[]> {
  const res = await api.get<SupportedTypesResponse>("/datasources/probe/types")
  return res.data.types ?? []
}

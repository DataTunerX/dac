/**
 * TDB pipeline API. DAC submits ingestion runs to the TDB pipeline controller
 * through dac-apiserver; the controller creates the Kubernetes jobs, writes into
 * the selected TDB gateway and uploads artifacts to S3.
 *
 * Uses @/lib/api (its response interceptor unwraps { code, message, data }, so
 * res.data is already the payload — do not unwrap twice).
 */
import { api } from "@/lib/api"
import type {
  CreateTDBPipelineRunRequest,
  TDBPipelineActionResponse,
  TDBPipelineOptionsResponse,
  TDBPipelineRun,
  TDBPipelineRunListResponse,
} from "@/lib/api-types"

/** Run statuses that will not change again. */
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "canceled"])

export function isTerminalRunStatus(status: string): boolean {
  return TERMINAL_STATUSES.has(status.trim().toLowerCase())
}

/** Form options: allowlisted targets and images plus submission defaults. */
export async function getTDBPipelineOptions(): Promise<TDBPipelineOptionsResponse> {
  const res = await api.get<TDBPipelineOptionsResponse>("/tdb-pipeline/options")
  return res.data
}

export async function listTDBPipelineRuns(params: {
  limit: number
  offset: number
  domain?: string
  status?: string
}): Promise<TDBPipelineRunListResponse> {
  const res = await api.get<TDBPipelineRunListResponse>("/tdb-pipeline/runs", { params })
  return res.data
}

export async function getTDBPipelineRun(runId: string): Promise<TDBPipelineRun> {
  const res = await api.get<TDBPipelineRun>(`/tdb-pipeline/runs/${encodeURIComponent(runId)}`)
  return res.data
}

/** Submit a run. The controller answers 202; the run then executes asynchronously. */
export async function createTDBPipelineRun(
  body: CreateTDBPipelineRunRequest
): Promise<TDBPipelineRun> {
  const res = await api.post<TDBPipelineRun>("/tdb-pipeline/runs", body)
  return res.data
}

export async function pauseTDBPipelineRun(runId: string): Promise<TDBPipelineActionResponse> {
  const res = await api.post<TDBPipelineActionResponse>(
    `/tdb-pipeline/runs/${encodeURIComponent(runId)}/pause`
  )
  return res.data
}

export async function resumeTDBPipelineRun(runId: string): Promise<TDBPipelineActionResponse> {
  const res = await api.post<TDBPipelineActionResponse>(
    `/tdb-pipeline/runs/${encodeURIComponent(runId)}/resume`
  )
  return res.data
}

export async function cancelTDBPipelineRun(runId: string): Promise<TDBPipelineActionResponse> {
  const res = await api.post<TDBPipelineActionResponse>(
    `/tdb-pipeline/runs/${encodeURIComponent(runId)}/cancel`
  )
  return res.data
}

/** Retry failed jobs with a full rerun. `failedStage` narrows it to one stage;
 *  s3_upload failures must use retryTDBPipelineS3Upload instead. */
export async function retryTDBPipelineFailed(
  runId: string,
  failedStage?: string
): Promise<TDBPipelineActionResponse> {
  const res = await api.post<TDBPipelineActionResponse>(
    `/tdb-pipeline/runs/${encodeURIComponent(runId)}/retry-failed`,
    failedStage ? { failed_stage: failedStage } : {}
  )
  return res.data
}

/** Retry only the artifact upload of jobs whose pipeline already succeeded. */
export async function retryTDBPipelineS3Upload(
  runId: string
): Promise<TDBPipelineActionResponse> {
  const res = await api.post<TDBPipelineActionResponse>(
    `/tdb-pipeline/runs/${encodeURIComponent(runId)}/retry-s3-upload`
  )
  return res.data
}

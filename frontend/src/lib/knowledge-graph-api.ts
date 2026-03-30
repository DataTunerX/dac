/**
 * Typed API for knowledge graph. Uses @/lib/api; response interceptor unwraps envelope.
 */
import { api } from "@/lib/api"
import type {
  KnowledgeGraphBySourceResponse,
  GetKnowledgeGraphBySourceRequest,
} from "@/lib/api-types"

export async function getGraphBySource(
  request: GetKnowledgeGraphBySourceRequest
): Promise<KnowledgeGraphBySourceResponse> {
  const res = await api.post<KnowledgeGraphBySourceResponse>(
    "/knowledge-graph/get-graph-by-source",
    request
  )
  return res.data
}

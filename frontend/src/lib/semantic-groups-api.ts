/**
 * Typed API for semantic groups. Uses @/lib/api (response interceptor unwraps
 * { code, message, data } so res.data is the payload). Follows api-contract: no double unwrap.
 */
import { api } from "@/lib/api"
import type {
  SemanticGroupWithMembersResponse,
  SemanticGroupListResponse,
} from "@/lib/api-types"

export async function getSemanticGroupWithMembers(
  id: string
): Promise<SemanticGroupWithMembersResponse | null> {
  const res = await api.get<SemanticGroupWithMembersResponse>(
    `/semantic-groups/${encodeURIComponent(id)}/with-members`
  )
  const data = res.data
  if (!data?.group) return null
  return data
}

export async function listSemanticGroups(params: {
  limit: number
  offset: number
}): Promise<SemanticGroupListResponse> {
  const res = await api.get<SemanticGroupListResponse>("/semantic-groups", { params })
  return res.data
}

export async function listSemanticGroupRoots(): Promise<SemanticGroupListResponse> {
  const res = await api.get<SemanticGroupListResponse>("/semantic-groups/roots")
  return res.data
}

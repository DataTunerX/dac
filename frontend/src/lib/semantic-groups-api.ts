/**
 * Typed API for semantic groups. Uses @/lib/api (response interceptor unwraps
 * { code, message, data } so res.data is the payload). Follows api-contract: no double unwrap.
 */
import { api } from "@/lib/api"
import type {
  SemanticGroupWithMembersResponse,
  SemanticGroupListResponse,
  SemanticGroupResponse,
  DDGroupRelationResponse,
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

/** Fields accepted by PUT /semantic-groups/:id. Omitted keys are left unchanged. */
export type UpdateSemanticGroupRequest = {
  group_name?: string
  description?: string
  agent_card?: string
  version?: string
}

export async function updateSemanticGroup(
  id: string,
  body: UpdateSemanticGroupRequest
): Promise<SemanticGroupResponse> {
  const res = await api.put<SemanticGroupResponse>(
    `/semantic-groups/${encodeURIComponent(id)}`,
    body
  )
  return res.data
}

/** Manual add-member: writes dd_group_relation without semantic-grouper consolidation. */
export type CreateDDGroupRelationRequest = {
  sd_id: string
  group_id: string
  association_reason?: string
}

export async function createDDGroupRelation(
  body: CreateDDGroupRelationRequest
): Promise<DDGroupRelationResponse> {
  const res = await api.post<DDGroupRelationResponse>("/dd-group-relations", body)
  return res.data
}

export async function deleteDDGroupRelation(id: number): Promise<void> {
  await api.delete(`/dd-group-relations/${encodeURIComponent(String(id))}`)
}

export type SemanticGroupMemberTaskStatus = {
  task_id: string
  status: string
  result?: Record<string, unknown>
  error?: string
}

export type AddSemanticGroupMemberRequest = {
  dd_namespace: string
  dd_name: string
  association_reason?: string
}

export type RemoveSemanticGroupMemberRequest = {
  sd_id: string
}

export type WaitForMemberTaskOptions = {
  timeoutMs?: number
  intervalMs?: number
}

export async function getSemanticGroupMemberTask(
  taskId: string
): Promise<SemanticGroupMemberTaskStatus> {
  const res = await api.get<SemanticGroupMemberTaskStatus>(
    `/semantic-groups/member-tasks/${encodeURIComponent(taskId)}`
  )
  return res.data
}

export async function waitForSemanticGroupMemberTask(
  taskId: string,
  options: WaitForMemberTaskOptions = {}
): Promise<SemanticGroupMemberTaskStatus> {
  const timeoutMs = options.timeoutMs ?? 180_000
  const intervalMs = options.intervalMs ?? 2_000
  const deadline = Date.now() + timeoutMs
  while (true) {
    const status = await getSemanticGroupMemberTask(taskId)
    if (status.status === "SUCCESS") return status
    if (status.status === "FAILURE" || status.status === "REVOKED") {
      throw new Error(status.error || "语义组任务失败")
    }
    if (Date.now() >= deadline) {
      throw new Error("等待组描述刷新超时，请稍后刷新页面查看结果")
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}

function memberTaskMessage(status: SemanticGroupMemberTaskStatus, fallback: string): string {
  const message = status.result?.message
  return typeof message === "string" && message.trim() ? message : fallback
}

/** Submit add-member task only — fire-and-forget; returns task_id for background polling. */
export async function submitAddSemanticGroupMember(
  groupId: string,
  body: AddSemanticGroupMemberRequest
): Promise<string> {
  const submit = await api.post<{ task_id: string }>(
    `/semantic-groups/${encodeURIComponent(groupId)}/members`,
    body
  )
  const taskId = submit.data?.task_id
  if (!taskId) {
    throw new Error("语义组添加成员任务未返回 task_id")
  }
  return taskId
}

/** Submit remove-member task only — fire-and-forget; returns task_id for background polling. */
export async function submitRemoveSemanticGroupMember(
  groupId: string,
  body: RemoveSemanticGroupMemberRequest
): Promise<string> {
  const submit = await api.post<{ task_id: string }>(
    `/semantic-groups/${encodeURIComponent(groupId)}/members/remove`,
    body
  )
  const taskId = submit.data?.task_id
  if (!taskId) {
    throw new Error("语义组移除成员任务未返回 task_id")
  }
  return taskId
}

export async function addSemanticGroupMember(
  groupId: string,
  body: AddSemanticGroupMemberRequest,
  options: WaitForMemberTaskOptions = {}
): Promise<SemanticGroupMemberTaskStatus> {
  const submit = await api.post<{ task_id: string }>(
    `/semantic-groups/${encodeURIComponent(groupId)}/members`,
    body
  )
  const taskId = submit.data?.task_id
  if (!taskId) {
    throw new Error("语义组添加成员任务未返回 task_id")
  }
  const status = await waitForSemanticGroupMemberTask(taskId, options)
  if (status.result?.action === "SKIPPED") {
    throw new Error(memberTaskMessage(status, "所选数据源已是该语义组成员"))
  }
  return status
}

export async function removeSemanticGroupMember(
  groupId: string,
  body: RemoveSemanticGroupMemberRequest,
  options: WaitForMemberTaskOptions = {}
): Promise<SemanticGroupMemberTaskStatus> {
  const submit = await api.post<{ task_id: string }>(
    `/semantic-groups/${encodeURIComponent(groupId)}/members/remove`,
    body
  )
  const taskId = submit.data?.task_id
  if (!taskId) {
    throw new Error("语义组移除成员任务未返回 task_id")
  }
  return waitForSemanticGroupMemberTask(taskId, options)
}

/**
 * Skill Hub BFF API (via dac-apiserver → skill-hub).
 */
import { api } from "@/lib/api"
import type {
  CreateSkillRequest,
  SkillDetailResponse,
  SkillInfoResponse,
  SkillListResponse,
  SkillNamespaceExistsResponse,
  SkillNamespaceListResponse,
  SkillNamespaceResponse,
} from "@/lib/api-types"

/** Shared SWR cache key for skill namespaces (marketplace + namespaces page). */
export const SKILL_NAMESPACES_KEY = "skill-namespaces"

export async function listSkillNamespaces(): Promise<SkillNamespaceListResponse> {
  const res = await api.get<SkillNamespaceListResponse>("/skills/namespaces")
  return res.data
}

export async function createSkillNamespace(name: string): Promise<SkillNamespaceResponse> {
  const res = await api.post<SkillNamespaceResponse>("/skills/namespaces", { name })
  return res.data
}

export async function deleteSkillNamespace(namespace: string): Promise<void> {
  await api.delete(`/skills/namespaces/${encodeURIComponent(namespace)}`)
}

export async function skillNamespaceExists(
  namespace: string
): Promise<SkillNamespaceExistsResponse> {
  const res = await api.get<SkillNamespaceExistsResponse>(
    `/skills/namespaces/${encodeURIComponent(namespace)}/exists`
  )
  return res.data
}

export async function listSkills(namespace: string): Promise<SkillListResponse> {
  const res = await api.get<SkillListResponse>(
    `/skills/namespaces/${encodeURIComponent(namespace)}/skills`
  )
  return res.data
}

/**
 * Load full skill pack metadata from skill-hub (via BFF).
 * Includes SKILL.md `detail` and `_meta.json` `allowed_tools`.
 */
export async function getSkill(
  namespace: string,
  name: string,
  version?: string
): Promise<SkillDetailResponse> {
  const res = await api.get<SkillDetailResponse>(
    `/skills/namespaces/${encodeURIComponent(namespace)}/skills/${encodeURIComponent(name)}`,
    { params: version ? { version } : undefined }
  )
  return res.data
}

export async function createSkill(
  namespace: string,
  body: CreateSkillRequest
): Promise<SkillInfoResponse> {
  const res = await api.post<SkillInfoResponse>(
    `/skills/namespaces/${encodeURIComponent(namespace)}/skills/create`,
    body
  )
  return res.data
}

/**
 * Update skill metadata while preserving scripts / resource dirs in the zip.
 * `sourceVersion` selects which pack to edit (omit = latest).
 */
export async function updateSkill(
  namespace: string,
  name: string,
  body: CreateSkillRequest,
  sourceVersion?: string
): Promise<SkillInfoResponse> {
  const res = await api.post<SkillInfoResponse>(
    `/skills/namespaces/${encodeURIComponent(namespace)}/skills/${encodeURIComponent(name)}/update`,
    body,
    { params: sourceVersion ? { version: sourceVersion } : undefined }
  )
  return res.data
}

export async function uploadSkill(
  namespace: string,
  file: File
): Promise<SkillInfoResponse> {
  const form = new FormData()
  form.append("file", file)
  const res = await api.post<SkillInfoResponse>(
    `/skills/namespaces/${encodeURIComponent(namespace)}/skills`,
    form
  )
  return res.data
}

export async function deleteSkill(
  namespace: string,
  name: string,
  version?: string
): Promise<void> {
  await api.delete(
    `/skills/namespaces/${encodeURIComponent(namespace)}/skills/${encodeURIComponent(name)}`,
    { params: version ? { version } : undefined }
  )
}

export async function reloadSkills(): Promise<SkillListResponse> {
  const res = await api.post<SkillListResponse>("/skills/reload")
  return res.data
}

/** Trigger browser download for a skill zip (cookie auth). */
export async function downloadSkill(
  namespace: string,
  name: string,
  version?: string
): Promise<void> {
  const params = version ? `?version=${encodeURIComponent(version)}` : ""
  const url =
    `/api/v1/skills/namespaces/${encodeURIComponent(namespace)}/skills/${encodeURIComponent(name)}/download${params}`

  const res = await fetch(url, { credentials: "include" })
  if (!res.ok) {
    let message = `下载失败 (${res.status})`
    try {
      const body = (await res.json()) as { message?: string }
      if (body.message) message = body.message
    } catch {
      // ignore non-JSON error bodies
    }
    throw new Error(message)
  }

  const blob = await res.blob()
  const disposition = res.headers.get("Content-Disposition") || ""
  let filename = `${name}.zip`
  const match = /filename="?([^"]+)"?/i.exec(disposition)
  if (match?.[1]) filename = match[1]

  const objectUrl = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = objectUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(objectUrl)
}

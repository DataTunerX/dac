/**
 * Typed API for RBAC management (dac-apiserver /api/v1/rbac/**).
 * Uses @/lib/api (response interceptor unwraps { code, message, data } so
 * res.data is the payload). All types aligned with internal/handler/dto/rbac.go.
 */
import { api } from "@/lib/api"
import { revalidateAuthSession } from "@/lib/auth-store"
import type {
  AddTenantMemberRequest,
  CreateRoleRequest,
  CreateTenantRequest,
  GrantPlatformRoleRequest,
  PlatformRoleUser,
  RbacMyTenant,
  RbacPermission,
  RbacPlatformRole,
  RbacTenant,
  RbacTenantListResponse,
  RbacTenantMember,
  RbacTenantMemberListResponse,
  RbacTenantRole,
  SetRolePermissionsRequest,
  UpdateRoleRequest,
  UpdateTenantRequest,
  UserListResponse,
  UserResponse,
} from "@/lib/api-types"

// ----- 租户 -----

export async function listTenants(params?: {
  page?: number
  page_size?: number
}): Promise<RbacTenantListResponse> {
  const res = await api.get<RbacTenantListResponse>("/rbac/tenants", { params })
  return res.data
}

export async function createTenant(payload: CreateTenantRequest): Promise<RbacTenant> {
  const res = await api.post<RbacTenant>("/rbac/tenants", payload)
  return res.data
}

export async function updateTenant(
  id: string,
  payload: UpdateTenantRequest
): Promise<RbacTenant> {
  const res = await api.put<RbacTenant>(`/rbac/tenants/${encodeURIComponent(id)}`, payload)
  return res.data
}

export async function deleteTenant(id: string): Promise<void> {
  await api.delete(`/rbac/tenants/${encodeURIComponent(id)}`)
}

export async function setTenantStatus(id: string, status: "active" | "disabled"): Promise<RbacTenant> {
  const res = await api.post<RbacTenant>(
    `/rbac/tenants/${encodeURIComponent(id)}/${status === "disabled" ? "disable" : "enable"}`
  )
  return res.data
}

export async function listTenantNamespaces(id: string): Promise<string[]> {
  const res = await api.get<string[]>(`/rbac/tenants/${encodeURIComponent(id)}/namespaces`)
  return res.data ?? []
}

export async function addTenantNamespace(id: string, namespace: string): Promise<void> {
  await api.post(`/rbac/tenants/${encodeURIComponent(id)}/namespaces`, { namespace })
}

export async function removeTenantNamespace(id: string, namespace: string): Promise<void> {
  await api.delete(
    `/rbac/tenants/${encodeURIComponent(id)}/namespaces/${encodeURIComponent(namespace)}`
  )
}

// ----- 租户角色 -----

export async function listTenantRoles(tenantId: string): Promise<RbacTenantRole[]> {
  const res = await api.get<RbacTenantRole[]>(
    `/rbac/tenants/${encodeURIComponent(tenantId)}/roles`
  )
  return res.data ?? []
}

export async function createTenantRole(
  tenantId: string,
  payload: CreateRoleRequest
): Promise<RbacTenantRole> {
  const res = await api.post<RbacTenantRole>(
    `/rbac/tenants/${encodeURIComponent(tenantId)}/roles`,
    payload
  )
  return res.data
}

export async function updateTenantRole(
  tenantId: string,
  roleId: string,
  payload: UpdateRoleRequest
): Promise<RbacTenantRole> {
  const res = await api.put<RbacTenantRole>(
    `/rbac/tenants/${encodeURIComponent(tenantId)}/roles/${encodeURIComponent(roleId)}`,
    payload
  )
  return res.data
}

export async function deleteTenantRole(tenantId: string, roleId: string): Promise<void> {
  await api.delete(
    `/rbac/tenants/${encodeURIComponent(tenantId)}/roles/${encodeURIComponent(roleId)}`
  )
}

export async function setTenantRolePermissions(
  tenantId: string,
  roleId: string,
  permissionCodes: string[]
): Promise<void> {
  const body: SetRolePermissionsRequest = { permissionCodes }
  await api.put(
    `/rbac/tenants/${encodeURIComponent(tenantId)}/roles/${encodeURIComponent(roleId)}/permissions`,
    body
  )
  refreshMyPermsAfterMutation()
}

export async function getTenantRolePermissionCodes(
  tenantId: string,
  roleId: string
): Promise<string[]> {
  const res = await api.get<{ permissionCodes: string[] }>(
    `/rbac/tenants/${encodeURIComponent(tenantId)}/roles/${encodeURIComponent(roleId)}/permissions`
  )
  return res.data.permissionCodes ?? []
}

// ----- 租户成员 -----

export async function listTenantMembers(
  tenantId: string,
  params?: { page?: number; page_size?: number }
): Promise<RbacTenantMemberListResponse> {
  const res = await api.get<RbacTenantMemberListResponse>(
    `/rbac/tenants/${encodeURIComponent(tenantId)}/users`,
    { params }
  )
  return res.data
}

export async function addTenantMember(
  tenantId: string,
  payload: AddTenantMemberRequest
): Promise<void> {
  await api.post(`/rbac/tenants/${encodeURIComponent(tenantId)}/users`, payload)
  refreshMyPermsAfterMutation()
}

export async function changeTenantMemberRole(
  tenantId: string,
  userId: string,
  roleId: string
): Promise<void> {
  await api.put(
    `/rbac/tenants/${encodeURIComponent(tenantId)}/users/${encodeURIComponent(userId)}/role`,
    { roleId }
  )
  refreshMyPermsAfterMutation()
}

export async function removeTenantMember(tenantId: string, userId: string): Promise<void> {
  await api.delete(
    `/rbac/tenants/${encodeURIComponent(tenantId)}/users/${encodeURIComponent(userId)}`
  )
  refreshMyPermsAfterMutation()
}

// ----- 平台角色 -----

export async function listPlatformRoles(): Promise<RbacPlatformRole[]> {
  const res = await api.get<RbacPlatformRole[]>("/rbac/platform/roles")
  return res.data ?? []
}

export async function createPlatformRole(payload: CreateRoleRequest): Promise<RbacPlatformRole> {
  const res = await api.post<RbacPlatformRole>("/rbac/platform/roles", payload)
  return res.data
}

export async function updatePlatformRole(
  roleId: string,
  payload: UpdateRoleRequest
): Promise<RbacPlatformRole> {
  const res = await api.put<RbacPlatformRole>(
    `/rbac/platform/roles/${encodeURIComponent(roleId)}`,
    payload
  )
  return res.data
}

export async function deletePlatformRole(roleId: string): Promise<void> {
  await api.delete(`/rbac/platform/roles/${encodeURIComponent(roleId)}`)
}

export async function setPlatformRolePermissions(
  roleId: string,
  permissionCodes: string[]
): Promise<void> {
  const body: SetRolePermissionsRequest = { permissionCodes }
  await api.put(
    `/rbac/platform/roles/${encodeURIComponent(roleId)}/permissions`,
    body
  )
  refreshMyPermsAfterMutation()
}

export async function getPlatformRolePermissionCodes(roleId: string): Promise<string[]> {
  const res = await api.get<{ permissionCodes: string[] }>(
    `/rbac/platform/roles/${encodeURIComponent(roleId)}/permissions`
  )
  return res.data.permissionCodes ?? []
}

export async function listPlatformRoleUsers(roleId: string): Promise<PlatformRoleUser[]> {
  const res = await api.get<PlatformRoleUser[]>(
    `/rbac/platform/roles/${encodeURIComponent(roleId)}/users`
  )
  return res.data ?? []
}

export async function grantPlatformRole(userId: string, roleId: string): Promise<void> {
  const body: GrantPlatformRoleRequest = { userId, roleId }
  await api.post("/rbac/platform/users", body)
  refreshMyPermsAfterMutation()
}

export async function revokePlatformRole(userId: string, roleId: string): Promise<void> {
  await api.delete(
    `/rbac/platform/users/${encodeURIComponent(userId)}/roles/${encodeURIComponent(roleId)}`
  )
  refreshMyPermsAfterMutation()
}

// ----- 权限点 -----

export async function listPermissions(): Promise<RbacPermission[]> {
  const res = await api.get<RbacPermission[]>("/rbac/permissions")
  return res.data ?? []
}

// ----- 我的租户 -----

export async function listMyTenants(): Promise<RbacMyTenant[]> {
  const res = await api.get<RbacMyTenant[]>("/rbac/me/tenants")
  return res.data ?? []
}

// ----- 全局用户 -----

export async function listUsers(params?: {
  page?: number
  page_size?: number
}): Promise<UserListResponse> {
  const res = await api.get<UserListResponse>("/users", { params })
  return res.data
}

/** Returns user IDs who are not yet assigned to any tenant. */
export async function listAvailableUsers(): Promise<string[]> {
  const res = await api.get<string[]>("/rbac/available-users")
  return res.data ?? []
}

export async function deleteUser(userId: string): Promise<void> {
  await api.delete(`/users/${encodeURIComponent(userId)}`)
}

export async function updateUser(
  userId: string,
  body: { email?: string; password?: string },
): Promise<UserResponse> {
  const res = await api.put(`/users/${encodeURIComponent(userId)}`, body)
  return res.data
}

/**
 * After an RBAC mutation the current user's own permission snapshot may have
 * changed (e.g. a platform role was granted/revoked or role permissions were
 * edited). Trigger a background session re-hydration so buttons and the sidebar
 * reflect the new codes immediately instead of waiting for the next focus event.
 */
function refreshMyPermsAfterMutation(): void {
  revalidateAuthSession()
}
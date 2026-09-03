"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import useSWR from "swr"
import { toast } from "sonner"
import { Plus, RefreshCw, Trash2, Users, UserCog, ShieldCheck, Loader2, Search, Building2, Eye, UserPlus, Pencil } from "lucide-react"

import { PageContainer } from "@/components/ui/page-container"
import { PageHeader } from "@/components/ui/page-header"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { TableWrapper } from "@/components/ui/table-wrapper"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { EmptyState } from "@/components/ui/empty-state"
import { RbacWrapper } from "@/components/rbac"
import { PaginationBar } from "@/components/pagination-bar"
import { SegmentedTabs } from "@/components/segmented-tabs"
import { TenantFilter } from "@/components/tenant-filter"
import { SearchSelect } from "@/components/search-select"
import { useAllUsers } from "@/hooks/use-all-users"
import { useAllTenants } from "@/hooks/use-all-tenants"

import {
  listTenantMembers,
  addTenantMember,
  changeTenantMemberRole,
  removeTenantMember,
  listTenantRoles,
  deleteUser,
  updateUser,
  listPlatformRoles,
  listPlatformRoleUsers,
  grantPlatformRole,
  revokePlatformRole,
  listAvailableUsers,
} from "@/lib/rbac-api"
import type {
  RbacTenant,
  RbacTenantMember,
  RbacTenantRole,
  RbacPlatformRole,
  PlatformRoleUser,
  UserResponse,
} from "@/lib/api-types"
import { api } from "@/lib/api"

type View = "users" | "members"

type Membership = { tenantId: string; tenantName: string; tenantCode: string; roleCode: string }

const AUTO_MEMBERSHIP_TENANT_CAP = 300 // above this, resolve memberships on demand

function fmtTime(s?: string) {
  if (!s) return "-"
  if (s.includes("T")) return s.replace("T", " ").slice(0, 19)
  return s.slice(0, 19)
}

async function fetchAllMembers(tenantId: string): Promise<RbacTenantMember[]> {
  const out: RbacTenantMember[] = []
  let page = 1
  for (;;) {
    const res = await listTenantMembers(tenantId, { page, page_size: 100 })
    out.push(...(res.items ?? []))
    if (out.length >= (res.totalCount ?? out.length) || (res.items ?? []).length === 0) break
    page += 1
    if (page > 100) break
  }
  return out
}

/** Build userId -> memberships map by walking every tenant's member list. */
async function buildMembershipsMap(tenants: RbacTenant[]): Promise<Map<string, Membership[]>> {
  const map = new Map<string, Membership[]>()
  const queue = [...tenants]
  const workers = Array.from({ length: 8 }, async () => {
    for (;;) {
      const t = queue.shift()
      if (!t) return
      try {
        const members = await fetchAllMembers(t.id)
        for (const m of members) {
          const arr = map.get(m.userId) ?? []
          arr.push({ tenantId: t.id, tenantName: t.name, tenantCode: t.code, roleCode: m.roleCode })
          map.set(m.userId, arr)
        }
      } catch {
        // skip tenants that fail to load
      }
    }
  })
  await Promise.all(workers)
  return map
}

/** Memberships of a single user, resolved on demand (large deployments). */
async function fetchMembershipsForUser(tenants: RbacTenant[], userId: string): Promise<Membership[]> {
  const out: Membership[] = []
  const queue = [...tenants]
  const workers = Array.from({ length: 8 }, async () => {
    for (;;) {
      const t = queue.shift()
      if (!t) return
      try {
        const members = await fetchAllMembers(t.id)
        for (const m of members) {
          if (m.userId === userId) {
            out.push({ tenantId: t.id, tenantName: t.name, tenantCode: t.code, roleCode: m.roleCode })
          }
        }
      } catch {
        // skip
      }
    }
  })
  await Promise.all(workers)
  return out
}

export default function UsersPage() {
  const [reloadKey, setReloadKey] = useState(0)
  const refresh = useCallback(() => setReloadKey((k) => k + 1), [])

  const [view, setView] = useState<View>("users")

  // ----- 全局用户（用户视角） -----
  const [userQuery, setUserQuery] = useState("")
  const [userPage, setUserPage] = useState(1)
  const [userPageSize, setUserPageSize] = useState(20)
  const { users: allUsers, isLoading: loadingUsers } = useAllUsers(reloadKey)

  const filteredUsers = useMemo(() => {
    const q = userQuery.trim().toLowerCase()
    if (!q) return allUsers
    return allUsers.filter((u) => u.username.toLowerCase().includes(q))
  }, [allUsers, userQuery])

  const pagedUsers = useMemo(
    () => filteredUsers.slice((userPage - 1) * userPageSize, userPage * userPageSize),
    [filteredUsers, userPage, userPageSize],
  )

  const usernameById = useMemo(() => {
    const m = new Map<string, string>()
    for (const u of allUsers) m.set(u.id, u.username)
    return m
  }, [allUsers])

  // ----- 租户成员（租户作为过滤字段） -----
  const [tenantId, setTenantId] = useState<string | null>(null)
  const [memberPage, setMemberPage] = useState(1)
  const [memberPageSize, setMemberPageSize] = useState(20)
  const { data: memberData, isLoading: loadingMembers } = useSWR(
    view === "members" && tenantId
      ? ["rbac-tenant-members", tenantId, memberPage, memberPageSize, reloadKey]
      : null,
    () => listTenantMembers(tenantId!, { page: memberPage, page_size: memberPageSize }),
  )
  const members = memberData?.items ?? []
  const memberTotal = memberData?.totalCount ?? 0

  // ----- 平台角色授予 -----
  const { data: platformRoles = [] } = useSWR(
    ["rbac-platform-roles", reloadKey],
    () => listPlatformRoles(),
    { keepPreviousData: true, revalidateOnFocus: false },
  )
  const { data: platformRoleUsers = [], mutate: mutatePlatformRoleUsers } = useSWR(
    ["rbac-platform-role-users", reloadKey],
    async () => {
      const roles = await listPlatformRoles()
      const results = await Promise.all(
        roles.map(async (r) => {
          try {
            return await listPlatformRoleUsers(r.id)
          } catch {
            return []
          }
        })
      )
      return results.flat()
    },
    { keepPreviousData: true, revalidateOnFocus: false },
  )
  const nonSuperRoles = useMemo(() => platformRoles.filter((r) => !r.isSuper), [platformRoles])
  const roleNameByCode = useMemo(() => {
    const m = new Map<string, string>()
    for (const r of platformRoles) m.set(r.code, r.name)
    return m
  }, [platformRoles])

  // ----- 租户归属（用户属性） -----
  const { tenants, isLoading: loadingTenants } = useAllTenants(reloadKey)
  const autoMembershipsEnabled = tenants.length > 0 && tenants.length <= AUTO_MEMBERSHIP_TENANT_CAP
  const { data: membershipsMap, isLoading: loadingMemberships } = useSWR(
    view === "users" && autoMembershipsEnabled ? ["rbac-memberships-all", reloadKey] : null,
    () => buildMembershipsMap(tenants),
  )

  // ----- 弹窗状态 -----
  const [addMemberOpen, setAddMemberOpen] = useState(false)
  const [createUserOpen, setCreateUserOpen] = useState(false)
  const [roleFor, setRoleFor] = useState<{ member: RbacTenantMember; username: string } | null>(null)
  const [grantFor, setGrantFor] = useState<UserResponse | null>(null)
  const [detailFor, setDetailFor] = useState<UserResponse | null>(null)
  const [removeFor, setRemoveFor] = useState<{ tenant: RbacTenant; member: RbacTenantMember; username: string } | null>(null)
  const [deleteUserFor, setDeleteUserFor] = useState<UserResponse | null>(null)
  const [editUserFor, setEditUserFor] = useState<UserResponse | null>(null)
  const [busy, setBusy] = useState(false)

  const tenantById = useMemo(() => {
    const m = new Map<string, RbacTenant>()
    for (const t of tenants) m.set(t.id, t)
    return m
  }, [tenants])

  const membershipsOf = (userId: string): Membership[] | undefined => membershipsMap?.get(userId)

  return (
    <PageContainer compact>
      <PageHeader
        title="用户管理"
        compact
        actions={undefined}
      />

      {/* 视角切换 + 过滤 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedTabs<View>
          tabs={[
            { value: "users", label: "全局用户", count: allUsers.length },
            { value: "members", label: "租户成员" },
          ]}
          value={view}
          onChange={(v) => setView(v)}
        />
        <div className="flex flex-wrap items-center gap-2">
          {view === "users" ? (
            <>
              <div className="relative w-64">
                <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-content-muted" />
                <input
                  value={userQuery}
                  onChange={(e) => {
                    setUserQuery(e.target.value)
                    setUserPage(1)
                  }}
                  placeholder="搜索用户名"
                  className="h-9 w-full rounded-md border border-line bg-surface pl-8 pr-2 text-sm text-content placeholder:text-content-muted focus:outline-none focus:ring-2 focus:ring-cta/30"
                />
              </div>
              <RbacWrapper requiredPermission="user:manage">
                <Button onClick={() => setCreateUserOpen(true)}>
                  <UserPlus className="w-4 h-4" /> 创建用户
                </Button>
              </RbacWrapper>
            </>
          ) : (
            <>
              <TenantFilter
                value={tenantId}
                onChange={(id) => {
                  setTenantId(id)
                  setMemberPage(1)
                }}
                reloadKey={reloadKey}
                placeholder="选择租户"
                showStatus
              />
              <RbacWrapper requiredPermission="tenant:member:manage">
                <Button
                  disabled={!tenantId}
                  title={tenantId ? undefined : "请先选择租户"}
                  onClick={() => setAddMemberOpen(true)}
                >
                  <Plus className="w-4 h-4" /> 添加成员
                </Button>
              </RbacWrapper>
            </>
          )}
          <Button variant="outline" size="icon" onClick={refresh} title="刷新" aria-label="刷新">
            <RefreshCw className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {view === "users" ? (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between border-b border-line px-4 py-2.5">
            <div className="flex items-center gap-2">
              <Users className="w-4 h-4 text-brand" />
              <CardTitle className="text-sm">全局用户</CardTitle>
            </div>
            <span className="text-xs text-content-muted">
              平台所有已注册用户；租户归属与平台角色是用户的属性
            </span>
          </CardHeader>
          <CardContent className="p-0">
            <TableWrapper noBorder>
              <Table storageKey="rbac-users-list-v2" className="text-xs">
                <TableHeader>
                  <TableRow className="bg-surface-muted">
                    <TableHead className="py-2 w-[100px]">用户名</TableHead>
                    <TableHead className="py-2 w-[120px]">邮箱</TableHead>
                    <TableHead className="py-2 w-[130px]">平台角色</TableHead>
                    <TableHead className="py-2 w-[150px]">租户归属</TableHead>
                    <TableHead className="py-2 w-[110px]">注册时间</TableHead>
                    <TableHead className="text-right py-2 w-[90px]">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {loadingUsers && allUsers.length === 0 ? (
                    <TableRow><TableCell colSpan={6} className="h-16 text-center text-content-muted text-xs">加载中…</TableCell></TableRow>
                  ) : pagedUsers.length === 0 ? (
                    <TableRow><TableCell colSpan={6} className="text-center text-content-muted py-6 text-xs">{userQuery ? "无匹配用户" : "暂无用户"}</TableCell></TableRow>
                  ) : (
                    pagedUsers.map((u) => {
                      const grants = platformRoleUsers.filter((g) => g.userId === u.id)
                      const memberships = membershipsOf(u.id)
                      const builtin = Boolean(u.is_builtin)
                      return (
                        <TableRow key={u.id}>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand/10 text-brand">
                                <UserCog className="h-3.5 w-3.5" />
                              </div>
                              <div className="min-w-0">
                                <div className="font-medium truncate text-sm">{u.username}</div>
                              </div>
                            </div>
                          </TableCell>
                          <TableCell>
                            <span className="text-sm text-content-muted">{u.email || "—"}</span>
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap items-center gap-1">
                              {grants.length === 0 ? (
                                <span className="text-xs text-content-muted">—</span>
                              ) : (
                                grants.map((g) => (
                                  <Badge key={g.roleCode} variant="secondary">{roleNameByCode.get(g.roleCode) ?? g.roleCode}</Badge>
                                ))
                              )}
                            </div>
                          </TableCell>
                          <TableCell>
                            {autoMembershipsEnabled ? (
                              loadingMemberships && !membershipsMap ? (
                                <Loader2 className="h-4 w-4 animate-spin text-content-muted" />
                              ) : (memberships?.length ?? 0) === 0 ? (
                                <span className="text-xs text-content-muted">未加入租户</span>
                              ) : (
                                <div className="flex flex-wrap gap-1">
                                  {(memberships ?? []).slice(0, 3).map((m) => (
                                    <Badge key={m.tenantId} variant="outline" title={`${m.tenantName}（${m.tenantCode}）`} className="text-xs h-5 px-1.5">
                                      {m.tenantName} · {m.roleCode}
                                    </Badge>
                                  ))}
                                  {(memberships?.length ?? 0) > 3 && (
                                    <Button variant="ghost" size="sm" className="h-6 px-1.5 text-cta" onClick={() => setDetailFor(u)}>
                                      +{memberships!.length - 3}
                                    </Button>
                                  )}
                                </div>
                              )
                            ) : (
                              <Button variant="ghost" size="sm" className="h-6 px-1.5 text-cta" onClick={() => setDetailFor(u)}>
                                <Eye className="w-3.5 h-3.5" /> 查看归属
                              </Button>
                            )}
                          </TableCell>
                          <TableCell className="whitespace-nowrap tabular-nums text-xs text-content-muted">
                            {fmtTime(u.created_at)}
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="inline-flex items-center gap-1">
                              {!builtin && (
                                <RbacWrapper requiredPermission="platform:role:manage">
                                  <Button variant="ghost" size="sm" className="h-6 px-1.5 text-cta" onClick={() => setGrantFor(u)}>
                                    <Plus className="w-3.5 h-3.5" /> 授权
                                  </Button>
                                </RbacWrapper>
                              )}
                              <RbacWrapper requiredPermission="user:manage">
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  title="编辑用户"
                                  aria-label="编辑用户"
                                  onClick={() => setEditUserFor(u)}
                                >
                                  <Pencil className="w-4 h-4" />
                                </Button>
                                {!builtin && (
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    title="删除用户"
                                    aria-label="删除用户"
                                    onClick={() => setDeleteUserFor(u)}
                                    className="text-red-600 hover:text-red-700"
                                  >
                                    <Trash2 className="w-4 h-4" />
                                  </Button>
                                )}
                              </RbacWrapper>
                            </div>
                          </TableCell>
                        </TableRow>
                      )
                    })
                  )}
                </TableBody>
              </Table>
            </TableWrapper>
            <div className="mt-4">
              <PaginationBar
                total={filteredUsers.length}
                page={userPage}
                pageSize={userPageSize}
                onPageChange={setUserPage}
                onPageSizeChange={(s) => {
                  setUserPageSize(s)
                  setUserPage(1)
                }}
              />
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between border-b border-line px-4 py-2.5">
            <div className="flex items-center gap-2">
              <Users className="w-4 h-4 text-brand" />
              <CardTitle className="text-sm">租户成员</CardTitle>
            </div>
            <span className="text-xs text-content-muted">租户是过滤字段：先选择租户，再查看其成员</span>
          </CardHeader>
          <CardContent className="p-0">
            {!tenantId ? (
              <EmptyState
                icon={Building2}
                message="请先选择租户"
                subMessage="在上方租户过滤器中搜索并选择一个租户，即可查看和管理该租户下的所有成员。"
              />
            ) : (
              <>
                <TableWrapper noBorder>
                  <Table storageKey="rbac-tenant-members-v2" className="text-xs">
                    <TableHeader>
                      <TableRow className="bg-surface-muted">
                        <TableHead className="py-2 w-[180px]">用户</TableHead>
                        <TableHead className="py-2 w-[160px]">角色</TableHead>
                        <TableHead className="py-2 w-[150px]">加入时间</TableHead>
                        <TableHead className="text-right py-2 w-[100px]">操作</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {loadingMembers && members.length === 0 ? (
                        <TableRow><TableCell colSpan={4} className="h-16 text-center text-content-muted text-xs">加载中…</TableCell></TableRow>
                      ) : members.length === 0 ? (
                        <TableRow><TableCell colSpan={4} className="text-center text-content-muted py-6 text-xs">该租户暂无成员</TableCell></TableRow>
                      ) : (
                        members.map((m) => (
                          <TableRow key={m.id}>
                            <TableCell>
                              <div className="font-medium truncate">{usernameById.get(m.userId) ?? "（加载中）"}</div>
                            </TableCell>
                            <TableCell>
                              <Badge variant="secondary">{m.roleCode}</Badge>
                            </TableCell>
                            <TableCell className="whitespace-nowrap tabular-nums text-xs text-content-muted">
                              {fmtTime(m.createdAt)}
                            </TableCell>
                            <TableCell className="text-right">
                              <div className="inline-flex items-center gap-1">
                                <RbacWrapper requiredPermission="tenant:member:manage">
                                  <>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      title="变更角色"
                                      aria-label="变更角色"
                                      onClick={() => setRoleFor({ member: m, username: usernameById.get(m.userId) ?? m.userId })}
                                    >
                                      <UserCog className="w-4 h-4" />
                                    </Button>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      title="移除"
                                      aria-label="移除"
                                      onClick={() => {
                                        const t = tenantById.get(tenantId)
                                        if (!t) return
                                        setRemoveFor({
                                          tenant: t,
                                          member: m,
                                          username: usernameById.get(m.userId) ?? m.userId,
                                        })
                                      }}
                                      className="text-red-600 hover:text-red-700"
                                    >
                                      <Trash2 className="w-4 h-4" />
                                    </Button>
                                  </>
                                </RbacWrapper>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </TableWrapper>
                <div className="mt-4">
                  <PaginationBar
                    total={memberTotal}
                    page={memberPage}
                    pageSize={memberPageSize}
                    onPageChange={setMemberPage}
                    onPageSizeChange={(s) => {
                      setMemberPageSize(s)
                      setMemberPage(1)
                    }}
                  />
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {/* 添加成员弹窗 */}
      <AddMemberDialog
        tenant={tenantId ? (tenantById.get(tenantId) ?? null) : null}
        open={addMemberOpen}
        reloadKey={reloadKey}
        onClose={() => setAddMemberOpen(false)}
        onDone={() => {
          setAddMemberOpen(false)
          refresh()
        }}
      />

      {/* 创建用户弹窗 */}
      <CreateUserDialog
        open={createUserOpen}
        onClose={() => setCreateUserOpen(false)}
        onDone={() => {
          setCreateUserOpen(false)
          refresh()
        }}
      />

      {/* 编辑用户弹窗 */}
      <EditUserDialog
        user={editUserFor}
        onClose={() => setEditUserFor(null)}
        onDone={() => {
          setEditUserFor(null)
          refresh()
        }}
      />

      {/* 变更角色弹窗 */}
      <ChangeRoleDialog
        member={roleFor?.member ?? null}
        username={roleFor?.username}
        onClose={() => setRoleFor(null)}
        onDone={() => {
          setRoleFor(null)
          refresh()
        }}
      />

      {/* 平台角色授予弹窗 */}
      <GrantRoleDialog
        user={grantFor}
        roles={nonSuperRoles}
        platformRoleUsers={platformRoleUsers}
        roleNameByCode={roleNameByCode}
        onClose={() => setGrantFor(null)}
        onDone={() => {
          setGrantFor(null)
        }}
        mutatePlatformRoleUsers={mutatePlatformRoleUsers}
      />

      {/* 用户归属详情弹窗 */}
      <UserMembershipsDialog
        user={detailFor}
        tenants={tenants}
        membershipsMap={membershipsMap}
        platformRoleUsers={platformRoleUsers}
        roleNameByCode={roleNameByCode}
        onClose={() => setDetailFor(null)}
      />

      {/* 移除成员确认 */}
      <AlertDialog open={Boolean(removeFor)} onOpenChange={(v) => !v && setRemoveFor(null)}>
        <AlertDialogContent className="w-[min(96vw,28rem)] max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>确认移除租户成员？</AlertDialogTitle>
            <AlertDialogDescription>
              将把用户 <span className="font-medium text-content">{removeFor?.username}</span> 从租户「{removeFor?.tenant.name}」移除，其在该租户下的访问权限即刻失效。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>取消</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700"
              disabled={busy}
              onClick={async () => {
                if (!removeFor) return
                setBusy(true)
                try {
                  await removeTenantMember(removeFor.tenant.id, removeFor.member.userId)
                  toast.success("成员已移除")
                  setRemoveFor(null)
                  refresh()
                } catch (e) {
                  const err = e as { response?: { data?: { message?: string } } }
                  toast.error(err.response?.data?.message || "移除失败")
                } finally {
                  setBusy(false)
                }
              }}
            >
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "移除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 删除全局用户确认 */}
      <AlertDialog open={Boolean(deleteUserFor)} onOpenChange={(v) => !v && setDeleteUserFor(null)}>
        <AlertDialogContent className="w-[min(96vw,28rem)] max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除用户？</AlertDialogTitle>
            <AlertDialogDescription>
              将永久删除用户 <span className="font-medium text-content">{deleteUserFor?.username || "-"}</span>，
              该用户的租户成员关系与平台角色授予将一并移除。此操作不可撤销。
              {deleteUserFor ? (
                <>
                  <br />
                  <span className="text-xs text-content-muted">用户名：{deleteUserFor.username}</span>
                </>
              ) : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>取消</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700"
              disabled={busy}
              onClick={async () => {
                if (!deleteUserFor) return
                setBusy(true)
                try {
                  await deleteUser(deleteUserFor.id)
                  toast.success("用户已删除")
                  setDeleteUserFor(null)
                  refresh()
                } catch (e) {
                  const err = e as { response?: { data?: { message?: string } } }
                  toast.error(err.response?.data?.message || "删除失败")
                } finally {
                  setBusy(false)
                }
              }}
            >
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  )
}

function AddMemberDialog({
  tenant,
  open,
  reloadKey,
  onClose,
  onDone,
}: {
  tenant: RbacTenant | null
  open: boolean
  reloadKey: number
  onClose: () => void
  onDone: () => void
}) {
  const { data: roles = [] } = useSWR(
    open && tenant ? ["rbac-roles-for-member", tenant.id, reloadKey] : null,
    () => listTenantRoles(tenant!.id),
  )
  // Share the same cache key as the page-level user list so both stay in sync.
  const { users, refresh: refreshUsers } = useAllUsers(reloadKey)

  // Fetch the set of users who are NOT yet assigned to any tenant.
  const { data: availableIds = [] } = useSWR(
    open ? ["rbac-available-users", reloadKey] : null,
    listAvailableUsers,
  )
  const availableSet = useMemo(() => new Set(availableIds), [availableIds])

  // Revalidate on every open so users created elsewhere (or in another tab)
  // show up without requiring a manual page refresh.
  useEffect(() => {
    if (open) refreshUsers()
  }, [open, refreshUsers])

  // Only show users who are not yet assigned to any tenant.
  const userOptions = useMemo(
    () =>
      users
        .filter((u) => availableSet.has(u.id))
        .map((u) => ({ value: u.id, label: u.username })),
    [users, availableSet],
  )
  const [userId, setUserId] = useState("")
  const [roleId, setRoleId] = useState("")
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    if (!tenant || !userId || !roleId) {
      toast.error("请选择用户与角色")
      return
    }
    setSaving(true)
    try {
      await addTenantMember(tenant.id, { userId, roleId })
      toast.success("成员已添加")
      setUserId("")
      setRoleId("")
      onDone()
    } catch (e) {
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "添加失败")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-[600px] p-0 gap-0">
        <div className="px-6 py-4 border-b border-line bg-surface-muted/50">
          <DialogTitle>添加成员 · {tenant?.name ?? ""}</DialogTitle>
          <DialogDescription className="mt-1">选择要加入该租户的用户及其角色。</DialogDescription>
        </div>
        <div className="space-y-4 px-6 py-4">
          <div className="space-y-1.5">
            <Label>用户</Label>
            <SearchSelect
              options={userOptions}
              value={userId || null}
              onChange={(v) => setUserId(v ?? "")}
              placeholder="选择一个用户"
              searchPlaceholder="搜索用户名"
            />
          </div>
          <div className="space-y-1.5">
            <Label>角色</Label>
            <Select value={roleId || undefined} onValueChange={setRoleId}>
              <SelectTrigger>
                <SelectValue placeholder="选择一个角色" />
              </SelectTrigger>
              <SelectContent>
                {(roles ?? []).map((r: RbacTenantRole) => (
                  <SelectItem key={r.id} value={r.id}>
                    {r.name}（{r.code}）
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-line bg-surface-muted/50">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={() => void submit()} disabled={saving}>
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "添加"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ChangeRoleDialog({
  member,
  username,
  onClose,
  onDone,
}: {
  member: RbacTenantMember | null
  username?: string
  onClose: () => void
  onDone: () => void
}) {
  const { data: roles = [] } = useSWR(
    member ? ["rbac-roles-for-member", member.tenantId] : null,
    () => listTenantRoles(member!.tenantId),
  )
  const [roleId, setRoleId] = useState("")
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    if (!member || !roleId) {
      toast.error("请选择角色")
      return
    }
    setSaving(true)
    try {
      await changeTenantMemberRole(member.tenantId, member.userId, roleId)
      toast.success("角色已变更")
      onDone()
    } catch (e) {
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "变更失败")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={Boolean(member)} onOpenChange={(v) => { if (!v) onClose(); if (v) setRoleId(member?.roleId ?? "") }}>
      <DialogContent className="sm:max-w-[520px] p-0 gap-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-line bg-surface-muted/50">
          <DialogTitle>变更成员角色</DialogTitle>
          <DialogDescription className="mt-1">
            用户 <span className="font-medium text-content">{username ?? "（未知）"}</span> 当前角色编码：{member?.roleCode}
          </DialogDescription>
        </div>
        <div className="space-y-1.5 px-6 py-4">
          <Label>新角色</Label>
          <Select value={roleId || undefined} onValueChange={setRoleId}>
            <SelectTrigger>
              <SelectValue placeholder="选择一个角色" />
            </SelectTrigger>
            <SelectContent>
              {(roles ?? []).map((r: RbacTenantRole) => (
                <SelectItem key={r.id} value={r.id}>
                  {r.name}（{r.code}）
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-line bg-surface-muted/50">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={() => void submit()} disabled={saving}>
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "保存"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function GrantRoleDialog({
  user,
  roles,
  platformRoleUsers,
  roleNameByCode,
  onClose,
  onDone,
  mutatePlatformRoleUsers,
}: {
  user: UserResponse | null
  roles: RbacPlatformRole[]
  platformRoleUsers: PlatformRoleUser[]
  roleNameByCode: Map<string, string>
  onClose: () => void
  onDone: () => void
  mutatePlatformRoleUsers: (
    data?: PlatformRoleUser[] | ((prev: PlatformRoleUser[] | undefined) => PlatformRoleUser[]),
    shouldRevalidate?: boolean
  ) => void
}) {
  const [saving, setSaving] = useState(false)

  const userGrants = useMemo(
    () => (user ? platformRoleUsers.filter((g) => g.userId === user.id) : []),
    [user, platformRoleUsers],
  )
  const grantedRoleCodes = useMemo(
    () => new Set(userGrants.map((g) => g.roleCode)),
    [userGrants],
  )
  // Selection state: codes of roles that the user has toggled to grant/revoke
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // Reset selection when dialog opens for a new user
  const [lastUserId, setLastUserId] = useState<string | null>(null)
  if (user && user.id !== lastUserId) {
    setLastUserId(user.id)
    setSelected(new Set(grantedRoleCodes))
  }
  if (!user && lastUserId !== null) {
    setLastUserId(null)
    setSelected(new Set())
  }

  const toggle = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(code)) {
        next.delete(code)
      } else {
        next.add(code)
      }
      return next
    })
  }

  const confirm = async () => {
    if (!user) return
    setSaving(true)

    // Determine roles to grant (in selected but not granted) and revoke (granted but not in selected)
    const toGrant = roles.filter((r) => selected.has(r.code) && !grantedRoleCodes.has(r.code))
    const toRevoke = roles.filter((r) => !selected.has(r.code) && grantedRoleCodes.has(r.code))

    // Optimistic: apply all changes at once
    mutatePlatformRoleUsers(
      (prev: PlatformRoleUser[] | undefined) => {
        let current = prev ?? []
        for (const r of toRevoke) {
          current = current.filter((g) => !(g.userId === user.id && g.roleCode === r.code))
        }
        for (const r of toGrant) {
          if (!current.some((g) => g.userId === user.id && g.roleCode === r.code)) {
            current = [...current, { userId: user.id, roleCode: r.code }]
          }
        }
        return current
      },
      false,
    )

    let hasError = false
    // Revoke first, then grant
    for (const r of toRevoke) {
      try {
        await revokePlatformRole(user.id, r.id)
      } catch {
        hasError = true
      }
    }
    for (const r of toGrant) {
      try {
        await grantPlatformRole(user.id, r.id)
      } catch {
        hasError = true
      }
    }

    if (hasError) {
      toast.error("部分操作失败，已刷新")
      mutatePlatformRoleUsers()
    } else {
      if (toGrant.length > 0 || toRevoke.length > 0) {
        toast.success("角色授权已更新")
      }
      onDone()
      mutatePlatformRoleUsers()
    }
    setSaving(false)
  }

  return (
    <Dialog open={Boolean(user)} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-[520px] p-0 gap-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-line bg-surface-muted/50">
          <DialogTitle>平台角色授权 · {user?.username ?? ""}</DialogTitle>
          <DialogDescription className="mt-1">选择角色后点击确认按钮完成授权。</DialogDescription>
        </div>
        <div className="px-6 py-4 space-y-4">
          <div className="flex items-center justify-between rounded-lg border border-line px-4 py-3">
            <span className="text-sm text-content-muted">当前已授予</span>
            <div className="flex flex-wrap gap-1">
              {user && userGrants.length > 0 ? (
                userGrants.map((g) => (
                  <Badge key={g.roleCode} variant="secondary">{roleNameByCode.get(g.roleCode) ?? g.roleCode}</Badge>
                ))
              ) : (
                <span className="text-sm text-content-muted">无</span>
              )}
            </div>
          </div>
          <div className="flex items-start justify-between gap-2">
            <ShieldCheck className="w-4 h-4 text-brand shrink-0 mt-1" />
            <div className="flex-1 min-w-0">
              <div className="text-xs text-content-muted mb-2">平台角色操作</div>
              <div className="flex flex-wrap gap-2">
                {roles.length === 0 ? (
                  <div className="flex items-center gap-2 py-2 text-sm text-content-muted">
                    <ShieldCheck className="w-4 h-4 shrink-0" />
                    暂无平台角色，请先在"角色管理"中创建平台角色。
                  </div>
                ) : (
                  roles.map((r) => {
                    const isSelected = selected.has(r.code)
                    return (
                      <Button
                        key={r.id}
                        size="sm"
                        variant={isSelected ? "default" : "outline"}
                        disabled={saving}
                        onClick={() => toggle(r.code)}
                      >
                        {r.name}
                      </Button>
                    )
                  })
                )}
              </div>
            </div>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-line bg-surface-muted/50">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={() => void confirm()} disabled={saving}>
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "确认"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function UserMembershipsDialog({
  user,
  tenants,
  membershipsMap,
  platformRoleUsers,
  roleNameByCode,
  onClose,
}: {
  user: UserResponse | null
  tenants: RbacTenant[]
  membershipsMap?: Map<string, Membership[]>
  platformRoleUsers: PlatformRoleUser[]
  roleNameByCode: Map<string, string>
  onClose: () => void
}) {
  const [ondemand, setOndemand] = useState<Membership[] | null>(null)
  const [loading, setLoading] = useState(false)

  const cached = user ? (membershipsMap?.get(user.id) ?? null) : null

  const loadOndemand = useCallback(async () => {
    if (!user) return
    setLoading(true)
    try {
      const list = await fetchMembershipsForUser(tenants, user.id)
      setOndemand(list)
    } catch {
      toast.error("加载归属失败")
    } finally {
      setLoading(false)
    }
  }, [user, tenants])

  // reset when user changes
  const [lastUserId, setLastUserId] = useState<string | null>(null)
  if (user && user.id !== lastUserId) {
    setLastUserId(user.id)
    setOndemand(null)
  }
  if (!user && lastUserId !== null) {
    setLastUserId(null)
    setOndemand(null)
  }

  const memberships = cached ?? ondemand
  const grants = user ? platformRoleUsers.filter((g) => g.userId === user.id) : []

  return (
    <Dialog open={Boolean(user)} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-[560px] p-0 gap-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-line bg-surface-muted/50">
          <DialogTitle>用户归属 · {user?.username ?? ""}</DialogTitle>
          <DialogDescription className="mt-1">该用户的平台角色与租户成员关系（租户是用户的属性）。</DialogDescription>
        </div>
        <div className="max-h-[60vh] space-y-5 overflow-y-auto px-6 py-4">
          <div className="space-y-1.5">
            <div className="text-xs font-medium text-content-muted">平台角色</div>
            <div className="flex flex-wrap gap-1">
              {grants.length === 0 ? (
                <span className="text-sm text-content-muted">无</span>
              ) : (
                grants.map((g) => (
                  <Badge key={g.roleCode} variant="secondary">{roleNameByCode.get(g.roleCode) ?? g.roleCode}</Badge>
                ))
              )}
            </div>
          </div>
          <div className="space-y-1.5">
            <div className="text-xs font-medium text-content-muted">租户成员关系</div>
            {cached ? (
              memberships!.length === 0 ? (
                <span className="text-sm text-content-muted">未加入任何租户</span>
              ) : (
                <div className="space-y-2">
                  {memberships!.map((m) => (
                    <div key={m.tenantId} className="flex items-center justify-between rounded-lg border border-line px-3 py-2">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-content truncate">{m.tenantName}</div>
                        <div className="font-mono text-xs text-content-muted truncate">{m.tenantCode}</div>
                      </div>
                      <Badge variant="secondary" className="shrink-0">{m.roleCode}</Badge>
                    </div>
                  ))}
                </div>
              )
            ) : loading ? (
              <div className="flex items-center gap-2 py-4 text-sm text-content-muted">
                <Loader2 className="h-4 w-4 animate-spin" /> 正在解析租户归属…
              </div>
            ) : ondemand ? (
              ondemand.length === 0 ? (
                <span className="text-sm text-content-muted">未加入任何租户</span>
              ) : (
                <div className="space-y-2">
                  {ondemand.map((m) => (
                    <div key={m.tenantId} className="flex items-center justify-between rounded-lg border border-line px-3 py-2">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-content truncate">{m.tenantName}</div>
                        <div className="font-mono text-xs text-content-muted truncate">{m.tenantCode}</div>
                      </div>
                      <Badge variant="secondary" className="shrink-0">{m.roleCode}</Badge>
                    </div>
                  ))}
                </div>
              )
            ) : (
              <Button variant="outline" size="sm" onClick={() => void loadOndemand()}>
                加载归属
              </Button>
            )}
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-line bg-surface-muted/50">
          <Button variant="outline" onClick={onClose}>关闭</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function CreateUserDialog({
  open,
  onClose,
  onDone,
}: {
  open: boolean
  onClose: () => void
  onDone: () => void
}) {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [email, setEmail] = useState("")
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    if (!username.trim()) {
      toast.error("请输入用户名")
      return
    }
    if (username.trim().length < 3) {
      toast.error("用户名至少 3 个字符")
      return
    }
    if (!password) {
      toast.error("请输入密码")
      return
    }
    if (password.length < 6) {
      toast.error("密码至少 6 个字符")
      return
    }
    if (password !== confirmPassword) {
      toast.error("两次输入的密码不一致")
      return
    }
    setSaving(true)
    try {
      await api.post("/auth/register", { username: username.trim(), password, email: email.trim() || undefined })
      toast.success("用户创建成功")
      setUsername("")
      setPassword("")
      setConfirmPassword("")
      setEmail("")
      onDone()
    } catch (e) {
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "创建失败")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-[520px] p-0 gap-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-line bg-surface-muted/50">
          <DialogTitle>创建用户</DialogTitle>
          <DialogDescription className="mt-1">新用户注册后即可登录，由管理员为其分配租户和角色。</DialogDescription>
        </div>
        <div className="space-y-4 px-6 py-4">
          <div className="space-y-1.5">
            <Label>用户名</Label>
            <Input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="3-50 个字符"
              maxLength={50}
            />
          </div>
          <div className="space-y-1.5">
            <Label>邮箱（可选）</Label>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="请输入邮箱"
              maxLength={255}
            />
          </div>
          <div className="space-y-1.5">
            <Label>密码</Label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="至少 6 个字符"
              maxLength={72}
            />
          </div>
          <div className="space-y-1.5">
            <Label>确认密码</Label>
            <Input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="再次输入密码"
              maxLength={72}
            />
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-line bg-surface-muted/50">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={() => void submit()} disabled={saving}>
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "创建"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function EditUserDialog({
  user,
  onClose,
  onDone,
}: {
  user: UserResponse | null
  onClose: () => void
  onDone: () => void
}) {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [saving, setSaving] = useState(false)

  // Sync state when user changes
  const [lastUserId, setLastUserId] = useState<string | null>(null)
  if (user && user.id !== lastUserId) {
    setLastUserId(user.id)
    setEmail(user.email ?? "")
    setPassword("")
  }

  const submit = async () => {
    if (!user) return
    setSaving(true)
    try {
      const body: { email?: string; password?: string } = {}
      const trimmed = email.trim()
      if (trimmed) body.email = trimmed
      if (password) body.password = password
      await updateUser(user.id, body)
      toast.success("用户已更新")
      setEmail("")
      setPassword("")
      onDone()
    } catch (e) {
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "更新失败")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={Boolean(user)} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-[520px] p-0 gap-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-line bg-surface-muted/50">
          <DialogTitle>编辑用户 · {user?.username ?? ""}</DialogTitle>
          <DialogDescription className="mt-1">修改用户的邮箱或密码，不填则不更新。</DialogDescription>
        </div>
        <div className="space-y-4 px-6 py-4">
          <div className="space-y-1.5">
            <Label>邮箱（可选）</Label>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="请输入邮箱"
              maxLength={255}
            />
          </div>
          <div className="space-y-1.5">
            <Label>新密码（可选，不填则不修改）</Label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="至少 6 个字符"
              maxLength={72}
            />
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-line bg-surface-muted/50">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={() => void submit()} disabled={saving}>
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "保存"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

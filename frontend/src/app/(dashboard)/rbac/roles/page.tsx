"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import useSWR from "swr"
import { toast } from "sonner"
import { Plus, RefreshCw, ShieldCheck, Trash2, Pencil, KeyRound, Loader2, Building2 } from "lucide-react"

import { PageContainer } from "@/components/ui/page-container"
import { PageHeader } from "@/components/ui/page-header"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { TableWrapper } from "@/components/ui/table-wrapper"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
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
import { SegmentedTabs } from "@/components/segmented-tabs"
import { TenantFilter } from "@/components/tenant-filter"

import {
  listTenantRoles,
  createTenantRole,
  updateTenantRole,
  deleteTenantRole,
  listPlatformRoles,
  createPlatformRole,
  updatePlatformRole,
  deletePlatformRole,
  listPermissions,
  setTenantRolePermissions,
  getTenantRolePermissionCodes,
  setPlatformRolePermissions,
  getPlatformRolePermissionCodes,
} from "@/lib/rbac-api"
import type {
  RbacTenantRole,
  RbacPlatformRole,
  RbacPermission,
} from "@/lib/api-types"

type Scope = { kind: "tenant"; tenantId: string } | { kind: "platform" }
type View = "platform" | "tenant"

const RESOURCE_LABELS: Record<string, string> = {
  tenant: "租户",
  platform_role: "平台角色",
  permission: "权限点",
  rbac_me: "我的租户",
  tenant_role: "租户角色",
  tenant_user: "租户成员",
  agent: "智能体",
  descriptor: "数据描述符",
  llmconfig: "模型管理",
  promptconfig: "提示词",
  system_config: "模版中心",
  environment: "环境",
  namespace: "命名空间",
  observability: "注册中心",
  semantic_group: "语义组",
  discovery: "资产探测",
  datasource: "数据源",
  skill: "技能",
  skill_namespace: "技能命名空间",
  chat: "对话",
  user: "用户",
}

function RoleKindBadge({ isDefault, isSuper }: { isDefault?: boolean; isSuper?: boolean }) {
  if (isDefault || isSuper) {
    return <Badge variant="secondary">默认角色</Badge>
  }
  return <Badge variant="secondary">自定义角色</Badge>
}

function fmtTime(s?: string) {
  if (!s) return "-"
  return s.replace("T", " ").replace(/\.\d+Z$/, "Z").slice(0, 19)
}

/** Group permissions by resource for the checkbox matrix. */
function groupByResource(perms: RbacPermission[]) {
  const map = new Map<string, RbacPermission[]>()
  for (const p of perms) {
    const key = RESOURCE_LABELS[p.resource] || p.resource || "其他"
    const list = map.get(key) ?? []
    list.push(p)
    map.set(key, list)
  }
  return Array.from(map.entries())
}

function RoleFormDialog({
  open,
  onOpenChange,
  title,
  initial,
  onSave,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  title: string
  initial?: { code: string; name: string; description?: string }
  onSave: (payload: { code: string; name: string; description?: string }) => Promise<void>
}) {
  const [code, setCode] = useState(initial?.code ?? "")
  const [name, setName] = useState(initial?.name ?? "")
  const [description, setDescription] = useState(initial?.description ?? "")
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) {
      setCode(initial?.code ?? "")
      setName(initial?.name ?? "")
      setDescription(initial?.description ?? "")
    }
  }, [open, initial])

  const submit = async () => {
    if (!name.trim()) {
      toast.error("请输入角色名称")
      return
    }
    if (!code.trim()) {
      toast.error("请输入角色编码")
      return
    }
    if (!/^[a-zA-Z0-9][a-zA-Z0-9:_-]*$/.test(code.trim())) {
      toast.error("角色编码仅支持字母、数字、中划线、下划线和冒号")
      return
    }
    setSaving(true)
    try {
      await onSave({
        code: code.trim(),
        name: name.trim(),
        description: description.trim() || undefined,
      })
      setSaving(false)
      onOpenChange(false)
    } catch (e) {
      setSaving(false)
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "保存失败")
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px] p-0 gap-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-line bg-surface-muted/50">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="mt-1">角色编码创建后不可修改。</DialogDescription>
        </div>
        <div className="space-y-4 px-6 py-4">
          <div className="space-y-1.5">
            <Label>角色编码</Label>
            <Input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="如：editor"
              disabled={Boolean(initial)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>角色名称</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：编辑者" />
          </div>
          <div className="space-y-1.5">
            <Label>描述</Label>
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="角色用途说明（可选）" rows={3} />
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-line bg-surface-muted/50">
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button onClick={() => void submit()} disabled={saving}>
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "保存"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function PermissionMatrixDialog({
  open,
  onOpenChange,
  title,
  permissions,
  initialCodes,
  onSave,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  title: string
  permissions: RbacPermission[]
  initialCodes: string[]
  onSave: (codes: string[]) => Promise<void>
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) setSelected(new Set(initialCodes))
  }, [open, initialCodes])

  const groups = useMemo(() => groupByResource(permissions), [permissions])

  const toggle = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })
  }

  const toggleGroup = (codes: string[]) => {
    setSelected((prev) => {
      const next = new Set(prev)
      const allSelected = codes.every((c) => next.has(c))
      for (const c of codes) {
        if (allSelected) next.delete(c)
        else next.add(c)
      }
      return next
    })
  }

  const submit = async () => {
    setSaving(true)
    try {
      await onSave(Array.from(selected))
      setSaving(false)
      onOpenChange(false)
      toast.success("权限已更新")
    } catch (e) {
      setSaving(false)
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "保存失败")
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[720px] max-h-[85vh] p-0 gap-0 flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-line bg-surface-muted/50">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="mt-1">勾选该角色可访问的功能点，保存后全量覆盖生效。</DialogDescription>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4 space-y-5">
          {groups.map(([resource, list]) => {
            const allSelected = list.every((p) => selected.has(p.code))
            return (
              <div key={resource} className="rounded-lg border border-line">
                <label className="flex cursor-pointer items-center gap-2 border-b border-line bg-surface-muted/60 px-4 py-3 rounded-t-lg">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => toggleGroup(list.map((p) => p.code))}
                    className="rounded border-line h-4 w-4 text-cta focus:ring-cta"
                  />
                  <span className="text-sm font-semibold text-content">{resource}</span>
                  <span className="text-xs text-content-muted">{list.length} 项</span>
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-5 gap-y-2 p-2">
                  {list.map((p) => (
                    <label
                      key={p.code}
                      className="flex cursor-pointer items-start gap-2.5 rounded-md px-3 py-2.5 hover:bg-surface-muted/50"
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(p.code)}
                        onChange={() => toggle(p.code)}
                        className="mt-0.5 rounded border-line h-4 w-4 text-cta focus:ring-cta"
                      />
                      <span className="min-w-0">
                        <span className="block text-sm text-content truncate leading-5" title={p.name}>{p.name}</span>
                        <span className="block text-xs text-content-muted truncate font-mono mt-0.5 leading-4" title={p.code}>{p.code}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-line bg-surface-muted/50">
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button onClick={() => void submit()} disabled={saving}>
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "保存权限"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default function RolesPage() {
  const [reloadKey, setReloadKey] = useState(0)
  const refresh = useCallback(() => setReloadKey((k) => k + 1), [])

  const [view, setView] = useState<View>("platform")
  const [tenantId, setTenantId] = useState<string | null>(null)

  const { data: platformRoles = [], isLoading: loadingPlatform } = useSWR(
    ["rbac-platform-roles", reloadKey],
    () => listPlatformRoles()
  )
  const { data: permissions = [] } = useSWR(
    ["rbac-permissions", reloadKey],
    () => listPermissions()
  )
  const { data: tenantRoles = [], isLoading: loadingTenantRoles } = useSWR(
    view === "tenant" && tenantId ? ["rbac-tenant-roles", tenantId, reloadKey] : null,
    () => listTenantRoles(tenantId!)
  )

  const [createFor, setCreateFor] = useState<Scope | null>(null)
  const [editRole, setEditRole] = useState<
    | { scope: Scope; role: RbacTenantRole | RbacPlatformRole; initial: { code: string; name: string; description?: string } }
    | null
  >(null)
  const [permFor, setPermFor] = useState<
    | { scope: Scope; roleId: string; roleName: string; currentCodes: string[] }
    | null
  >(null)
  const [deleteFor, setDeleteFor] = useState<
    | { scope: Scope; roleId: string; roleName: string }
    | null
  >(null)
  const [deleting, setDeleting] = useState(false)

  const saveNewRole = async (payload: { code: string; name: string; description?: string }) => {
    if (!createFor) return
    if (createFor.kind === "tenant") {
      await createTenantRole(createFor.tenantId, payload)
      toast.success("租户角色已创建")
    } else {
      await createPlatformRole(payload)
      toast.success("平台角色已创建")
    }
    refresh()
  }

  const saveEditRole = async (payload: { code: string; name: string; description?: string }) => {
    if (!editRole) return
    const { scope, role } = editRole
    if (scope.kind === "tenant") {
      await updateTenantRole(scope.tenantId, role.id, { name: payload.name, description: payload.description })
      toast.success("租户角色已更新")
    } else {
      await updatePlatformRole(role.id, { name: payload.name, description: payload.description })
      toast.success("平台角色已更新")
    }
    refresh()
  }

  const savePerms = async (codes: string[]) => {
    if (!permFor) return
    if (permFor.scope.kind === "tenant") {
      await setTenantRolePermissions(permFor.scope.tenantId, permFor.roleId, codes)
    } else {
      await setPlatformRolePermissions(permFor.roleId, codes)
    }
  }

  const confirmDelete = async () => {
    if (!deleteFor) return
    setDeleting(true)
    try {
      if (deleteFor.scope.kind === "tenant") {
        await deleteTenantRole(deleteFor.scope.tenantId, deleteFor.roleId)
        toast.success("租户角色已删除")
      } else {
        await deletePlatformRole(deleteFor.roleId)
        toast.success("平台角色已删除")
      }
      setDeleteFor(null)
      refresh()
    } catch (e) {
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "删除失败")
    } finally {
      setDeleting(false)
    }
  }

  const openPermDialog = async (scope: Scope, roleId: string, roleName: string) => {
    let currentCodes: string[] = []
    try {
      if (scope.kind === "tenant") {
        currentCodes = await getTenantRolePermissionCodes(scope.tenantId, roleId)
      } else {
        currentCodes = await getPlatformRolePermissionCodes(roleId)
      }
    } catch (e) {
      console.error("fetch role permission codes failed", e)
      toast.error("获取当前权限配置失败")
      return
    }
    setPermFor({ scope, roleId, roleName, currentCodes })
  }

  return (
    <PageContainer compact>
      <PageHeader
        title="角色管理"
        compact
        actions={undefined}
      />

      {/* 视角切换 + 租户过滤 + 新建 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedTabs<View>
          tabs={[
            { value: "platform", label: "平台角色", count: platformRoles.length },
            { value: "tenant", label: "租户角色" },
          ]}
          value={view}
          onChange={setView}
        />
        <div className="flex flex-wrap items-center gap-2">
          {view === "tenant" && (
            <TenantFilter
              value={tenantId}
              onChange={setTenantId}
              reloadKey={reloadKey}
              placeholder="选择租户"
              showStatus
            />
          )}
          {view === "platform" ? (
            <RbacWrapper requiredPermission="platform:role:manage">
              <Button onClick={() => setCreateFor({ kind: "platform" })}>
                <Plus className="w-4 h-4" /> 新建平台角色
              </Button>
            </RbacWrapper>
          ) : (
            <RbacWrapper requiredPermission="tenant:role:manage">
              <Button
                disabled={!tenantId}
                title={tenantId ? undefined : "请先选择租户"}
                onClick={() => tenantId && setCreateFor({ kind: "tenant", tenantId })}
              >
                <Plus className="w-4 h-4" /> 新建租户角色
              </Button>
            </RbacWrapper>
          )}
          <Button variant="outline" size="icon" onClick={refresh} title="刷新" aria-label="刷新">
            <RefreshCw className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {view === "platform" ? (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between border-b border-line px-4 py-2.5">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-brand" />
              <CardTitle className="text-sm">平台角色</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <TableWrapper noBorder>
              <Table storageKey="rbac-platform-roles" className="text-xs">
                <TableHeader>
                  <TableRow className="bg-surface-muted">
                    <TableHead className="py-2">名称</TableHead>
                    <TableHead className="py-2">编码</TableHead>
                    <TableHead className="py-2">类型</TableHead>
                    <TableHead className="py-2">描述</TableHead>
                    <TableHead className="py-2">创建时间</TableHead>
                    <TableHead className="text-right py-2">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {loadingPlatform && platformRoles.length === 0 ? (
                    <TableRow><TableCell colSpan={6} className="h-16 text-center text-content-muted text-xs">加载中…</TableCell></TableRow>
                  ) : platformRoles.length === 0 ? (
                    <TableRow><TableCell colSpan={6} className="text-center text-content-muted py-6 text-xs">暂无平台角色</TableCell></TableRow>
                  ) : (
                    platformRoles.map((r) => (
                      <TableRow key={r.id}>
                        <TableCell className="font-medium">{r.name}</TableCell>
                        <TableCell className="font-mono text-sm text-content-muted">{r.code}</TableCell>
                        <TableCell><RoleKindBadge isSuper={r.isSuper} /></TableCell>
                        <TableCell className="text-content-muted max-w-[280px] truncate" title={r.description}>{r.description || "-"}</TableCell>
                        <TableCell className="whitespace-nowrap tabular-nums text-sm text-content-muted">{fmtTime(r.createdAt)}</TableCell>
                        <TableCell className="text-right">
                          <div className="inline-flex items-center gap-1">
                            <RbacWrapper requiredPermission="platform:role:manage">
                              {r.isSuper ? (
                                <span className="text-xs text-content-muted px-1.5">内置角色</span>
                              ) : (
                                <>
                                  <Button variant="ghost" size="icon" title="配置权限" aria-label="配置权限"
                                    onClick={() => void openPermDialog({ kind: "platform" }, r.id, r.name)}>
                                    <KeyRound className="w-4 h-4" />
                                  </Button>
                                  <Button variant="ghost" size="icon" title="编辑" aria-label="编辑"
                                    onClick={() => setEditRole({ scope: { kind: "platform" }, role: r, initial: { code: r.code, name: r.name, description: r.description } })}>
                                    <Pencil className="w-4 h-4" />
                                  </Button>
                                  <Button variant="ghost" size="icon" title="删除" aria-label="删除"
                                    onClick={() => setDeleteFor({ scope: { kind: "platform" }, roleId: r.id, roleName: r.name })}
                                    className="text-red-600 hover:text-red-700">
                                    <Trash2 className="w-4 h-4" />
                                  </Button>
                                </>
                              )}
                            </RbacWrapper>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </TableWrapper>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between border-b border-line px-4 py-2.5">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-brand" />
              <CardTitle className="text-sm">租户角色</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {!tenantId ? (
              <EmptyState
                icon={Building2}
                message="请先选择租户"
                subMessage="在上方租户过滤器中搜索并选择一个租户，即可查看和管理该租户下的所有角色。"
              />
            ) : (
              <TableWrapper noBorder>
                <Table storageKey="rbac-tenant-roles-single" className="text-xs">
                  <TableHeader>
                    <TableRow className="bg-surface-muted">
                      <TableHead className="py-2">名称</TableHead>
                      <TableHead className="py-2">编码</TableHead>
                      <TableHead className="py-2">类型</TableHead>
                      <TableHead className="py-2">描述</TableHead>
                      <TableHead className="py-2">创建时间</TableHead>
                      <TableHead className="text-right py-2">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {loadingTenantRoles && tenantRoles.length === 0 ? (
                      <TableRow><TableCell colSpan={6} className="h-16 text-center text-content-muted text-xs">加载中…</TableCell></TableRow>
                    ) : tenantRoles.length === 0 ? (
                      <TableRow><TableCell colSpan={6} className="text-center text-content-muted py-6 text-xs">该租户暂无角色</TableCell></TableRow>
                    ) : (
                      tenantRoles.map((r) => (
                        <TableRow key={r.id}>
                          <TableCell className="font-medium">{r.name}</TableCell>
                          <TableCell className="font-mono text-sm text-content-muted">{r.code}</TableCell>
                          <TableCell><RoleKindBadge isDefault={r.isDefault} /></TableCell>
                          <TableCell className="text-content-muted max-w-[260px] truncate" title={r.description}>{r.description || "-"}</TableCell>
                          <TableCell className="whitespace-nowrap tabular-nums text-sm text-content-muted">{fmtTime(r.createdAt)}</TableCell>
                          <TableCell className="text-right">
                            <div className="inline-flex items-center gap-1">
                              <RbacWrapper requiredPermission="tenant:role:manage">
                                <>
                                  <Button variant="ghost" size="icon" title="配置权限" aria-label="配置权限"
                                    onClick={() => void openPermDialog({ kind: "tenant", tenantId }, r.id, r.name)}>
                                    <KeyRound className="w-4 h-4" />
                                  </Button>
                                  <Button variant="ghost" size="icon" title="编辑" aria-label="编辑"
                                    onClick={() => setEditRole({ scope: { kind: "tenant", tenantId }, role: r, initial: { code: r.code, name: r.name, description: r.description } })}>
                                    <Pencil className="w-4 h-4" />
                                  </Button>
                                  <Button variant="ghost" size="icon" title="删除" aria-label="删除" disabled={r.isDefault}
                                    onClick={() => setDeleteFor({ scope: { kind: "tenant", tenantId }, roleId: r.id, roleName: r.name })}
                                    className="text-red-600 hover:text-red-700">
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
            )}
          </CardContent>
        </Card>
      )}

      {createFor && (
        <RoleFormDialog
          open
          onOpenChange={(v) => !v && setCreateFor(null)}
          title={createFor.kind === "tenant" ? "新建租户角色" : "新建平台角色"}
          onSave={saveNewRole}
        />
      )}
      {editRole && (
        <RoleFormDialog
          open
          onOpenChange={(v) => !v && setEditRole(null)}
          title={editRole.scope.kind === "tenant" ? "编辑租户角色" : "编辑平台角色"}
          initial={editRole.initial}
          onSave={saveEditRole}
        />
      )}
      {permFor && (
        <PermissionMatrixDialog
          open
          onOpenChange={(v) => !v && setPermFor(null)}
          title={`${permFor.roleName} · 权限配置`}
          permissions={permissions}
          initialCodes={permFor.currentCodes}
          onSave={(codes) => savePerms(codes)}
        />
      )}

      <AlertDialog open={Boolean(deleteFor)} onOpenChange={(v) => !v && setDeleteFor(null)}>
        <AlertDialogContent className="w-[min(96vw,28rem)] max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除角色？</AlertDialogTitle>
            <AlertDialogDescription>
              将删除角色 <span className="font-medium text-content">{deleteFor?.roleName || "-"}</span>，
              删除后该角色关联的用户将失去对应权限。此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction className="bg-red-600 hover:bg-red-700" disabled={deleting} onClick={() => void confirmDelete()}>
              {deleting ? <Loader2 className="w-4 h-4 animate-spin" /> : "删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  )
}

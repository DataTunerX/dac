"use client"

import { useMemo, useState } from "react"
import useSWR from "swr"
import { RefreshCw, KeyRound, Search, Filter, UserCheck } from "lucide-react"

import { PageContainer } from "@/components/ui/page-container"
import { PageHeader } from "@/components/ui/page-header"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { TableWrapper } from "@/components/ui/table-wrapper"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import {
  listPermissions,
  listPlatformRoles,
  getPlatformRolePermissionCodes,
  listTenants,
  listTenantRoles,
  getTenantRolePermissionCodes,
} from "@/lib/rbac-api"
import type { RbacPermission } from "@/lib/api-types"

const ACTION_LABELS: Record<string, string> = {
  read: "只读",
  write: "读写",
  manage: "管理",
  create: "创建",
  update: "更新",
  delete: "删除",
  use: "使用",
}

function ActionBadge({ action }: { action: string }) {
  const label = ACTION_LABELS[action] ?? action ?? "-"
  const variant =
    action === "read"
      ? "secondary"
      : action === "manage"
        ? "default"
        : action === "use"
          ? "outline"
          : "secondary"
  return <Badge variant={variant}>{label}</Badge>
}

function fmtMethod(method: string) {
  return method || "-"
}

/** A role reference shown in the "按角色查看" dropdown. */
type RoleEntry = {
  key: string
  label: string
  group: string
  roleId: string
  kind: "platform" | "tenant"
  tenantId?: string
}

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

/** Group permissions by resource for the permission catalog. */
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

export default function PermissionsPage() {
  const [reloadKey, setReloadKey] = useState(0)
  const [query, setQuery] = useState("")
  const [roleKey, setRoleKey] = useState("")

  const { data: permissions = [], isLoading } = useSWR(
    ["rbac-permissions-list", reloadKey],
    () => listPermissions()
  )

  // Roles available for "按角色查看权限".
  const { data: platformRoles = [] } = useSWR(
    ["rbac-platform-roles", reloadKey],
    () => listPlatformRoles()
  )
  const { data: tenantsData } = useSWR(
    ["rbac-tenants", reloadKey],
    () => listTenants({ page: 1, page_size: 100 })
  )
  const tenants = tenantsData?.items ?? []

  // Flatten all roles from all tenants into the dropdown options.
  const roleTenantIds = useMemo(() => tenants.map((t) => t.id), [tenants])
  const { data: tenantRoles = [] } = useSWR(
    ["rbac-all-tenant-roles", roleTenantIds, reloadKey],
    async () => {
      if (roleTenantIds.length === 0) return []
      const results = await Promise.all(
        roleTenantIds.map((id) => listTenantRoles(id).catch(() => []))
      )
      return results.flat()
    }
  )

  // Current permission codes for the selected role (only fetched when needed).
  const selectedRole = useMemo<RoleEntry | null>(() => {
    if (!roleKey) return null
    const parts = roleKey.split("|")
    if (parts[0] === "platform") {
      const role = platformRoles.find((r) => r.id === parts[1])
      return role ? { key: roleKey, label: role.name, group: "平台角色", roleId: role.id, kind: "platform" } : null
    }
    if (parts[0] === "tenant") {
      const role = tenantRoles.find((r) => r.id === parts[1])
      const tenant = tenants.find((t) => t.id === role?.tenantId)
      if (!role || !tenant) return null
      return {
        key: roleKey,
        label: `${tenant.name} · ${role.name}`,
        group: "租户角色",
        roleId: role.id,
        kind: "tenant",
        tenantId: tenant.id,
      }
    }
    return null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roleKey, platformRoles, tenantRoles, tenants])

  const { data: roleCodes = [] } = useSWR(
    selectedRole
      ? [
          "rbac-role-permission-codes",
          selectedRole.kind,
          selectedRole.roleId,
          selectedRole.tenantId,
          reloadKey,
        ]
      : null,
    () => {
      if (!selectedRole) return Promise.resolve([])
      if (selectedRole.kind === "platform") {
        return getPlatformRolePermissionCodes(selectedRole.roleId)
      }
      return getTenantRolePermissionCodes(selectedRole.tenantId!, selectedRole.roleId)
    }
  )

  // Flatten all roles from all tenants into the dropdown options.
  const roleOptions = useMemo<RoleEntry[]>(() => {
    const platforms: RoleEntry[] = platformRoles.map((r) => ({
      key: `platform|${r.id}`,
      label: r.name,
      group: "平台角色",
      roleId: r.id,
      kind: "platform",
    }))
    const tenantsEntries: RoleEntry[] = tenantRoles.map((r) => {
      const tenant = tenants.find((t) => t.id === r.tenantId)
      return {
        key: `tenant|${r.id}`,
        label: tenant ? `${tenant.name} · ${r.name}` : r.name,
        group: "租户角色",
        roleId: r.id,
        kind: "tenant",
        tenantId: r.tenantId,
      }
    })
    return [...platforms, ...tenantsEntries]
  }, [platformRoles, tenantRoles, tenants])

  const groups = useMemo(() => groupByResource(permissions), [permissions])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return groups
    return groups
      .map(([resource, list]) => [
        resource,
        list.filter(
          (p) =>
            p.code.toLowerCase().includes(q) ||
            p.name.toLowerCase().includes(q) ||
            (p.description ?? "").toLowerCase().includes(q) ||
            (p.httpPath ?? "").toLowerCase().includes(q)
        ),
      ] as [string, RbacPermission[]])
      .filter(([, list]) => list.length > 0)
  }, [groups, query])

  const grantedSet = useMemo(() => new Set(roleCodes), [roleCodes])

  const totalCodes = useMemo(() => new Set(permissions.map((p) => p.code)).size, [permissions])
  const grantedCount = useMemo(
    () => filtered.reduce((acc, [, list]) => acc + list.filter((p) => grantedSet.has(p.code)).length, 0),
    [filtered, grantedSet]
  )
  const shownCount = useMemo(
    () => filtered.reduce((acc, [, list]) => acc + list.length, 0),
    [filtered]
  )

  return (
    <PageContainer compact>
      <PageHeader
        title="权限点"
        compact
        actions={
          <div className="flex items-center gap-2">
            <span className="hidden sm:inline-flex items-center gap-1.5 text-xs text-content-muted">
              <Filter className="w-3.5 h-3.5" />
              按角色查看
            </span>
            <Select value={roleKey || undefined} onValueChange={setRoleKey}>
              <SelectTrigger className="h-9 w-[min(16rem,60vw)] bg-surface">
                <SelectValue placeholder="选择角色，高亮其拥有的权限" />
              </SelectTrigger>
              <SelectContent position="popper" side="bottom" align="end" sideOffset={6} collisionPadding={10}>
                {roleOptions.map((r) => (
                  <SelectItem key={r.key} value={r.key}>
                    <span className="inline-flex items-center gap-2 text-sm">
                      <span className="text-content-muted">[{r.group}]</span>
                      {r.label}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" size="icon" onClick={() => setReloadKey((k) => k + 1)} title="刷新" aria-label="刷新">
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        }
      />

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 border-b border-line">
          <div className="flex items-center gap-2">
            <KeyRound className="w-4 h-4 text-brand" />
            <CardTitle>权限点清单</CardTitle>
            <span className="text-xs text-content-muted">{totalCodes} 个权限码 / {permissions.length} 条规则</span>
          </div>
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-content-muted" aria-hidden />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索权限码 / 名称 / 路径…"
              className="pl-9"
            />
          </div>
        </CardHeader>
        <CardContent className="pt-4 space-y-6">
          {selectedRole && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-brand/30 bg-brand/5 px-4 py-3">
              <UserCheck className="w-4 h-4 text-brand" aria-hidden />
              <span className="text-sm font-medium text-content">
                正在查看：{selectedRole.label}
              </span>
              <Badge variant="outline" className="font-normal">
                已授权 {grantedCount} / {shownCount} 项
              </Badge>
              <button
                type="button"
                onClick={() => setRoleKey("")}
                className="ml-auto text-xs text-content-muted underline-offset-2 hover:text-content hover:underline"
              >
                清除筛选
              </button>
            </div>
          )}

          {isLoading && permissions.length === 0 ? (
            <div className="text-center text-content-muted py-10">加载中…</div>
          ) : filtered.length === 0 ? (
            <div className="text-center text-content-muted py-10">
              {query ? "未找到匹配的权限点" : "暂无权限点数据"}
            </div>
          ) : (
            filtered.map(([resource, list]) => (
              <div key={resource} className="rounded-lg border border-line overflow-hidden">
                <div className="flex items-center gap-2 border-b border-line bg-surface-muted/60 px-4 py-2.5">
                  <span className="text-sm font-semibold text-content">{resource}</span>
                  <span className="text-xs text-content-muted">{list.length} 条</span>
                </div>
                <TableWrapper noBorder>
                  <Table storageKey={`rbac-permissions-${resource}`}>
                    <TableHeader>
                      <TableRow className="bg-surface-muted">
                        <TableHead className="w-[72px]" aria-label="授权状态"></TableHead>
                        <TableHead>权限码</TableHead>
                        <TableHead>名称</TableHead>
                        <TableHead>动作</TableHead>
                        <TableHead>HTTP 方法</TableHead>
                        <TableHead>路径模板</TableHead>
                        <TableHead>说明</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {list.map((p) => {
                        const granted = grantedSet.has(p.code)
                        return (
                          <TableRow
                            key={p.id}
                            className={granted ? "bg-brand/5" : undefined}
                          >
                            <TableCell>
                              {granted && selectedRole ? (
                                <span
                                  className="inline-flex h-5 items-center gap-1 rounded-full bg-emerald-500/15 px-2 text-[11px] font-medium text-emerald-700 whitespace-nowrap"
                                  title="该角色已授权此权限"
                                >
                                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                                  已授权
                                </span>
                              ) : (
                                <span className="text-xs text-content-muted/50"></span>
                              )}
                            </TableCell>
                            <TableCell className="font-mono text-xs text-content">{p.code}</TableCell>
                            <TableCell className="font-medium whitespace-nowrap">{p.name}</TableCell>
                            <TableCell><ActionBadge action={p.action} /></TableCell>
                            <TableCell className="font-mono text-xs text-content-muted whitespace-nowrap">{fmtMethod(p.httpMethod)}</TableCell>
                            <TableCell className="font-mono text-xs text-content-muted max-w-[360px] truncate" title={p.httpPath}>{p.httpPath || "-"}</TableCell>
                            <TableCell className="text-content-muted max-w-[240px] truncate" title={p.description}>{p.description || "-"}</TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </TableWrapper>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </PageContainer>
  )
}
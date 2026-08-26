"use client"

import { useCallback, useMemo, useState } from "react"
import useSWR from "swr"
import { toast } from "sonner"
import { Plus, RefreshCw, Pencil, Trash2, Globe, FolderOpen, Power, Loader2, ChevronDown } from "lucide-react"

import { PageContainer } from "@/components/ui/page-container"
import { PageHeader } from "@/components/ui/page-header"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { TableWrapper } from "@/components/ui/table-wrapper"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
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
import { RbacWrapper } from "@/components/rbac"

import {
  listTenants,
  createTenant,
  updateTenant,
  deleteTenant,
  setTenantStatus,
  listTenantNamespaces,
  addTenantNamespace,
  removeTenantNamespace,
} from "@/lib/rbac-api"
import type { RbacTenant } from "@/lib/api-types"
import { listNamespaces } from "@/lib/namespaces-api"
import { PaginationBar } from "@/components/pagination-bar"

function fmtTime(s?: string) {
  if (!s) return "-"
  return s.replace("T", " ").replace(/\.\d+Z$/, "Z").slice(0, 19)
}

function TenantStatusBadge({ status }: { status: string }) {
  if (status === "disabled") {
    return <Badge variant="destructive">已禁用</Badge>
  }
  return <Badge variant="secondary">正常</Badge>
}

function TenantFormDialog({
  open,
  onOpenChange,
  mode,
  initial,
  onSave,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  mode: "create" | "edit"
  initial?: RbacTenant
  onSave: (payload: { code: string; name: string; description?: string }) => Promise<void>
}) {
  const [code, setCode] = useState("")
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [saving, setSaving] = useState(false)

  const reset = () => {
    setCode(initial?.code ?? "")
    setName(initial?.name ?? "")
    setDescription(initial?.description ?? "")
  }

  const submit = async () => {
    if (!name.trim()) {
      toast.error("请输入租户名称")
      return
    }
    if (mode === "create" && !code.trim()) {
      toast.error("请输入租户编码")
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
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (v) reset()
        onOpenChange(v)
      }}
    >
      <DialogContent className="sm:max-w-[520px] p-0 gap-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-line bg-surface-muted/50">
          <DialogTitle>{mode === "create" ? "新建租户" : "编辑租户"}</DialogTitle>
          <DialogDescription className="mt-1">租户编码创建后不可修改。</DialogDescription>
        </div>
        <div className="space-y-4 px-6 py-4">
          <div className="space-y-1.5">
            <Label>租户编码</Label>
            <Input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="如：finance"
              disabled={mode === "edit"}
            />
          </div>
          <div className="space-y-1.5">
            <Label>租户名称</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：财务部" />
          </div>
          <div className="space-y-1.5">
            <Label>描述</Label>
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="租户用途说明（可选）" rows={3} />
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

function NamespacesDialog({
  tenant,
  open,
  onOpenChange,
}: {
  tenant: RbacTenant | null
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const { data: nss = [], mutate } = useSWR(
    tenant ? ["rbac-tenant-namespaces", tenant.id] : null,
    () => listTenantNamespaces(tenant!.id),
  )
  const { data: allNs = [] } = useSWR(
    open ? ["all-namespaces"] : null,
    async () => {
      const res = await listNamespaces()
      return (res.items ?? []).map((ns) => ns.name)
    },
  )
  const [selectedNs, setSelectedNs] = useState("")
  const [busy, setBusy] = useState(false)

  const boundSet = new Set(nss)
  const availableNs = allNs.filter((name) => !boundSet.has(name))

  const add = async () => {
    if (!tenant || !selectedNs) return
    setBusy(true)
    try {
      await addTenantNamespace(tenant.id, selectedNs)
      setSelectedNs("")
      await mutate()
    } catch (e) {
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "绑定失败")
    } finally {
      setBusy(false)
    }
  }

  const remove = async (ns: string) => {
    if (!tenant) return
    setBusy(true)
    try {
      await removeTenantNamespace(tenant.id, ns)
      await mutate()
    } catch (e) {
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "解绑失败")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px] p-0 gap-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-line bg-surface-muted/50">
          <DialogTitle>命名空间绑定 · {tenant?.name ?? ""}</DialogTitle>
          <DialogDescription className="mt-1">绑定后该租户可访问对应的命名空间资源。</DialogDescription>
        </div>
        <div className="px-6 py-4 space-y-4">
          <div className="flex gap-2">
            <Select value={selectedNs} onValueChange={setSelectedNs} disabled={busy}>
              <SelectTrigger className="flex-1">
                <SelectValue placeholder="选择命名空间…" />
              </SelectTrigger>
              <SelectContent>
                {availableNs.length === 0 ? (
                  <div className="px-2 py-3 text-sm text-content-muted text-center">
                    {allNs.length === 0 ? "加载中…" : "所有命名空间已绑定"}
                  </div>
                ) : (
                  availableNs.map((name) => (
                    <SelectItem key={name} value={name}>{name}</SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            <Button onClick={() => void add()} disabled={busy || !selectedNs}>
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "绑定"}
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            {nss.length === 0 ? (
              <span className="text-sm text-content-muted">暂未绑定命名空间</span>
            ) : (
              nss.map((ns) => (
                <span
                  key={ns}
                  className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-muted px-3 py-1 text-sm"
                >
                  {ns}
                  <button
                    type="button"
                    aria-label={`解绑 ${ns}`}
                    disabled={busy}
                    onClick={() => void remove(ns)}
                    className="text-content-muted hover:text-red-600 disabled:opacity-50"
                  >
                    ×
                  </button>
                </span>
              ))
            )}
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-line bg-surface-muted/50">
          <Button variant="outline" onClick={() => onOpenChange(false)}>关闭</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default function TenantsPage() {
  const [reloadKey, setReloadKey] = useState(0)
  const refresh = useCallback(() => setReloadKey((k) => k + 1), [])

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const { data, error, isLoading, mutate } = useSWR(
    ["rbac-tenants", page, pageSize, reloadKey],
    () => listTenants({ page, page_size: pageSize })
  )

  const items = data?.items ?? []
  const totalCount = data?.totalCount ?? 0

  // Bound namespaces for every tenant on the current page, fetched in
  // parallel so the table shows them without N+1 waterfall delays.
  const tenantIds = useMemo(() => items.map((t) => t.id), [items])
  const { data: namespacesByTenant = {} } = useSWR<Record<string, string[]>>(
    tenantIds.length > 0 ? ["rbac-tenant-namespaces", tenantIds, reloadKey] : null,
    async () => {
      const results = await Promise.all(
        tenantIds.map((id) => listTenantNamespaces(id).catch(() => [] as string[]))
      )
      const map: Record<string, string[]> = {}
      tenantIds.forEach((id, i) => {
        map[id] = results[i]
      })
      return map
    }
  )

  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<RbacTenant | null>(null)
  const [disableTarget, setDisableTarget] = useState<RbacTenant | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<RbacTenant | null>(null)
  const [nsTarget, setNsTarget] = useState<RbacTenant | null>(null)
  const [busy, setBusy] = useState(false)

  const saveCreate = async (payload: { code: string; name: string; description?: string }) => {
    await createTenant(payload)
    toast.success("租户已创建")
    refresh()
  }

  const saveEdit = async (payload: { code: string; name: string; description?: string }) => {
    if (!editTarget) return
    await updateTenant(editTarget.id, { name: payload.name, description: payload.description })
    toast.success("租户已更新")
    setEditTarget(null)
    refresh()
  }

  const toggleStatus = async (t: RbacTenant) => {
    setBusy(true)
    try {
      await setTenantStatus(t.id, t.status === "disabled" ? "active" : "disabled")
      toast.success(t.status === "disabled" ? "租户已启用" : "租户已禁用")
      refresh()
    } catch (e) {
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "操作失败")
    } finally {
      setBusy(false)
      setDisableTarget(null)
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setBusy(true)
    try {
      // 先解绑所有命名空间，否则后端会返回 409
      const nss = await listTenantNamespaces(deleteTarget.id)
      if (nss.length > 0) {
        await Promise.all(nss.map((ns) => removeTenantNamespace(deleteTarget.id, ns)))
      }
      await deleteTenant(deleteTarget.id)
      toast.success("租户已删除")
      setDeleteTarget(null)
      refresh()
    } catch (e) {
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "删除失败")
    } finally {
      setBusy(false)
    }
  }

  return (
    <PageContainer compact>
      <PageHeader
        title="租户管理"
        compact
        actions={
          <div className="flex items-center gap-2">
            <RbacWrapper requiredPermission="tenant:manage">
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="w-4 h-4" /> 新建租户
              </Button>
            </RbacWrapper>
            <Button variant="outline" size="icon" onClick={() => { refresh(); void mutate() }} title="刷新" aria-label="刷新">
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        }
      />

      <Card>
        <CardContent className="pt-6">
          <TableWrapper>
            <Table storageKey="rbac-tenants-list">
              <TableHeader>
                <TableRow className="bg-surface-muted">
                  <TableHead>名称</TableHead>
                  <TableHead>编码</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>命名空间</TableHead>
                  <TableHead>描述</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && items.length === 0 ? (
                  <TableRow><TableCell colSpan={7} className="h-24 text-center text-content-muted">加载中…</TableCell></TableRow>
                ) : error ? (
                  <TableRow><TableCell colSpan={7} className="text-center text-content-muted py-10">加载失败，请刷新重试</TableCell></TableRow>
                ) : items.length === 0 ? (
                  <TableRow><TableCell colSpan={7} className="text-center text-content-muted py-10">暂无租户</TableCell></TableRow>
                ) : (
                  items.map((t: RbacTenant) => {
                    const isDefault = t.code === "default"
                    return (
                    <TableRow key={t.id}>
                      <TableCell>
                        <div className="flex items-center gap-3">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand/10 text-brand">
                            <Globe className="h-4 w-4" />
                          </div>
                          <span className="font-medium">{t.name}</span>
                          {isDefault && <Badge variant="secondary">内置</Badge>}
                        </div>
                      </TableCell>
                      <TableCell className="font-mono text-sm text-content-muted">{t.code}</TableCell>
                      <TableCell><TenantStatusBadge status={t.status} /></TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1 max-w-[240px]">
                          {(namespacesByTenant[t.id] ?? []).length === 0 ? (
                            <span className="text-content-muted text-sm">-</span>
                          ) : (
                            (namespacesByTenant[t.id] ?? []).map((ns) => (
                              <span
                                key={ns}
                                className="inline-flex items-center rounded-md border border-line bg-surface-muted px-1.5 py-0.5 font-mono text-xs text-content-muted"
                                title={ns}
                              >
                                {ns}
                              </span>
                            ))
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-content-muted max-w-[160px] truncate" title={t.description}>{t.description || "-"}</TableCell>
                      <TableCell className="whitespace-nowrap tabular-nums text-sm text-content-muted">{fmtTime(t.createdAt)}</TableCell>
                      <TableCell className="text-right">
                        <div className="inline-flex items-center gap-1">
                          <RbacWrapper requiredPermission="tenant:manage">
                            {isDefault ? (
                              <span className="text-xs text-content-muted px-1.5">默认租户</span>
                            ) : (
                            <>
                              <Button variant="ghost" size="icon" title="命名空间绑定" aria-label="命名空间绑定"
                                onClick={() => setNsTarget(t)}>
                                <FolderOpen className="w-4 h-4" />
                              </Button>
                              <Button variant="ghost" size="icon" title="编辑" aria-label="编辑"
                                onClick={() => setEditTarget(t)}>
                                <Pencil className="w-4 h-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                title={t.status === "disabled" ? "启用" : "禁用"}
                                aria-label={t.status === "disabled" ? "启用" : "禁用"}
                                onClick={() => setDisableTarget(t)}
                                className={t.status === "disabled" ? "text-emerald-600" : "text-amber-600"}
                              >
                                <Power className="w-4 h-4" />
                              </Button>
                              <Button variant="ghost" size="icon" title="删除" aria-label="删除"
                                onClick={() => setDeleteTarget(t)}
                                className="text-red-600 hover:text-red-700">
                                <Trash2 className="w-4 h-4" />
                              </Button>
                            </>
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
              total={totalCount}
              page={page}
              pageSize={pageSize}
              onPageChange={setPage}
              onPageSizeChange={(s) => { setPageSize(s); setPage(1) }}
            />
          </div>
        </CardContent>
      </Card>

      <TenantFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        mode="create"
        onSave={saveCreate}
      />
      <TenantFormDialog
        open={Boolean(editTarget)}
        onOpenChange={(v) => !v && setEditTarget(null)}
        mode="edit"
        initial={editTarget ?? undefined}
        onSave={saveEdit}
      />

      <NamespacesDialog
        tenant={nsTarget}
        open={Boolean(nsTarget)}
        onOpenChange={(v) => {
          if (!v) {
            setNsTarget(null)
            // The dialog mutates namespace bindings through its own SWR key;
            // bump reloadKey so the table column reflects the latest bindings.
            refresh()
          }
        }}
      />

      <AlertDialog open={Boolean(disableTarget)} onOpenChange={(v) => !v && setDisableTarget(null)}>
        <AlertDialogContent className="w-[min(96vw,28rem)] max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>
              {disableTarget?.status === "disabled" ? "确认启用租户？" : "确认禁用租户？"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {disableTarget?.status === "disabled"
                ? `启用后租户「${disableTarget?.name}」的成员将恢复访问权限。`
                : `禁用后租户「${disableTarget?.name}」的所有成员将立即失去访问权限，此操作可随时恢复。`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>取消</AlertDialogCancel>
            <AlertDialogAction
              className={disableTarget?.status === "disabled" ? "bg-emerald-600 hover:bg-emerald-700" : "bg-amber-600 hover:bg-amber-700"}
              disabled={busy}
              onClick={() => disableTarget && void toggleStatus(disableTarget)}
            >
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "确认"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={Boolean(deleteTarget)} onOpenChange={(v) => !v && setDeleteTarget(null)}>
        <AlertDialogContent className="w-[min(96vw,28rem)] max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除租户？</AlertDialogTitle>
            <AlertDialogDescription>
              将删除租户 <span className="font-medium text-content">{deleteTarget?.name || "-"}</span>，
              其成员关系与角色将一并移除。此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>取消</AlertDialogCancel>
            <AlertDialogAction className="bg-red-600 hover:bg-red-700" disabled={busy} onClick={() => void confirmDelete()}>
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  )
}
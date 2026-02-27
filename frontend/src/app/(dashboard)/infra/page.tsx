"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import axios from "axios"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { RbacButton, RbacWrapper } from "@/components/rbac"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { PaginationBar } from "@/components/pagination-bar"
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
import { Loader2, Plus, RefreshCw, Trash2, Eye, Target } from "lucide-react"
import type { DiscoveryJobResponse, DiscoveryJobStatus } from "@/lib/discovery"
import { deleteDiscoveryScan, listDiscoveryScans, startDiscoveryScan, updateDiscoveryScan } from "@/lib/discovery"

function statusLabel(status: DiscoveryJobStatus) {
  switch (status) {
    case "PENDING":
      return "排队中"
    case "RUNNING":
      return "扫描中"
    case "SUCCEEDED":
      return "已完成"
    case "FAILED":
      return "失败"
    default:
      return status
  }
}

function statusPillClass(status: DiscoveryJobStatus) {
  switch (status) {
    case "SUCCEEDED":
      return "bg-green-100 text-green-800"
    case "RUNNING":
      return "bg-blue-100 text-blue-800"
    case "FAILED":
      return "bg-red-100 text-red-800"
    case "PENDING":
    default:
      return "bg-slate-100 text-slate-800"
  }
}

function fmtTs(sec?: number) {
  if (!sec) return "-"
  const d = new Date(sec * 1000)
  if (!Number.isFinite(d.getTime())) return "-"
  return d.toLocaleString()
}

function getApiErrorMessage(err: unknown): string | null {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data
    if (data && typeof data === "object") {
      const r = data as Record<string, unknown>
      const msg = r.message
      if (typeof msg === "string" && msg.trim()) return msg.trim()
    }
    if (typeof err.message === "string" && err.message.trim()) return err.message.trim()
    return null
  }
  if (err instanceof Error && err.message.trim()) return err.message.trim()
  return null
}

export default function InfraDiscoveryListPage() {
  const router = useRouter()

  const [items, setItems] = useState<DiscoveryJobResponse[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(false)

  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(1)

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [createName, setCreateName] = useState("")
  const [createTarget, setCreateTarget] = useState("127.0.0.1")
  const [createPortsSpec, setCreatePortsSpec] = useState("")
  const [createTimeoutMs, setCreateTimeoutMs] = useState("30000")
  const [createConcurrency, setCreateConcurrency] = useState("256")
  const [isCreating, setIsCreating] = useState(false)

  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  const fetchData = async () => {
    setIsLoading(true)
    try {
      const offset = (page - 1) * pageSize
      const res = await listDiscoveryScans({ limit: pageSize, offset })
      setItems(res.items || [])
      setTotal(res.totalCount || 0)
    } catch (err) {
      console.error("List discovery scans failed", err)
      toast.error("获取扫描记录失败")
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    void fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize])

  // IMPORTANT: do NOT re-sort client-side when using pagination.
  // The backend already returns a stable order (created_at desc), and sorting per-page would
  // make items jump across pages.
  const ordered = useMemo(() => items || [], [items])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const openDetail = (id: string) => {
    router.push(`/infra/${encodeURIComponent(id)}`)
  }

  const onCreate = async () => {
    const target = createTarget.trim()
    if (!target) {
      toast.error("请输入目标（IP / Host / IP 段）")
      return
    }

    setIsCreating(true)
    try {
      const timeout = Number(createTimeoutMs)
      const conc = Number(createConcurrency)
      const res = await startDiscoveryScan({
        target,
        portsSpec: createPortsSpec.trim() || undefined,
        timeoutMs: Number.isFinite(timeout) && timeout > 0 ? timeout : undefined,
        concurrency: Number.isFinite(conc) && conc > 0 ? conc : undefined,
      })

      const name = createName.trim()
      if (name) {
        await updateDiscoveryScan(res.id, name)
      }

      toast.success("已开始扫描")
      setIsCreateOpen(false)
      setCreateName("")
      setPage(1)
      await fetchData()
      openDetail(res.id)
    } catch (err) {
      console.error("Create discovery scan failed", err)
      toast.error(getApiErrorMessage(err) || "启动扫描失败")
    } finally {
      setIsCreating(false)
    }
  }

  const onDelete = async () => {
    if (!deleteId) return
    setIsDeleting(true)
    try {
      await deleteDiscoveryScan(deleteId)
      toast.success("已删除扫描记录")
      setDeleteId(null)
      // If we deleted the last item on the page, go back one page.
      const remaining = Math.max(0, total - 1)
      const nextTotalPages = Math.max(1, Math.ceil(remaining / pageSize))
      if (page > nextTotalPages) setPage(nextTotalPages)
      await fetchData()
    } catch (err) {
      console.error("Delete discovery scan failed", err)
      toast.error("删除失败")
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium text-slate-600">
          <span className="text-slate-900 font-semibold">资产探测</span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" onClick={fetchData} disabled={isLoading}>
            <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
          </Button>
          <RbacButton 
            className="flex items-center gap-2" 
            onClick={() => setIsCreateOpen(true)}
            requiredRole="admin"
            fallbackTitle="无权限：仅管理员可创建"
          >
            <Plus className="w-4 h-4" />
            新建扫描
          </RbacButton>
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-slate-50">
              <TableHead className="w-[220px]">名称</TableHead>
              <TableHead className="w-[200px]">目标</TableHead>
              <TableHead className="w-[120px]">状态</TableHead>
              <TableHead className="w-[200px]">开始时间</TableHead>
              <TableHead className="w-[200px]">结束时间</TableHead>
              <TableHead className="w-[160px] text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && ordered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-24 text-center">
                  <div className="flex items-center justify-center gap-2 text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" /> 加载中...
                  </div>
                </TableCell>
              </TableRow>
            ) : ordered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-slate-500 py-10">
                  暂无扫描记录
                </TableCell>
              </TableRow>
            ) : (
              ordered.map((job) => (
                <TableRow key={job.id} className="cursor-pointer hover:bg-slate-50" onClick={() => openDetail(job.id)}>
                  <TableCell className="text-sm text-slate-900">
                    <div className="flex items-start gap-3 min-w-0">
                      <div className="w-9 h-9 rounded-xl bg-blue-50 flex items-center justify-center text-blue-600 shrink-0 mt-0.5">
                        <Target className="w-4 h-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="font-medium truncate" title={job.name || job.id}>
                          {job.name || "-"}
                        </div>
                        <div className="mt-0.5 text-[11px] text-slate-500 font-mono truncate" title={job.id}>
                          {job.id}
                        </div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{job.target}</TableCell>
                  <TableCell>
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusPillClass(job.status)}`}>
                      {statusLabel(job.status)}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs text-slate-600">{fmtTs(job.startedAt)}</TableCell>
                  <TableCell className="text-xs text-slate-600">{fmtTs(job.finishedAt)}</TableCell>
                  <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-2">
                      <Button variant="ghost" size="icon" onClick={() => openDetail(job.id)}>
                        <Eye className="w-4 h-4 text-slate-500" />
                      </Button>
                      <RbacWrapper requiredRole="admin">
                        <Button variant="ghost" size="icon" onClick={() => setDeleteId(job.id)}>
                          <Trash2 className="w-4 h-4 text-red-500" />
                        </Button>
                      </RbacWrapper>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <PaginationBar
        total={total}
        page={page}
        pageSize={pageSize}
        pageSizeOptions={[10, 20, 50, 100]}
        isLoading={isLoading}
        onPageChange={setPage}
        onPageSizeChange={(n) => {
          setPageSize(n)
          setPage(1)
        }}
      />

      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="sm:max-w-[720px] max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
        <DialogHeader className="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
          <DialogTitle>新建扫描</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 flex-1 min-h-0 overflow-y-auto px-6 py-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2 sm:col-span-2">
              <div className="text-xs font-medium text-slate-600">名称（可选）</div>
              <Input value={createName} onChange={(e) => setCreateName(e.target.value)} placeholder="例如：sandbox 探测" />
            </div>

            <div className="space-y-2 sm:col-span-2">
              <div className="text-xs font-medium text-slate-600">目标（IP / Host / IP 段）</div>
              <Input
                value={createTarget}
                onChange={(e) => setCreateTarget(e.target.value)}
                placeholder="例如：10.0.0.1 / 10.0.0.0/24 / 10.0.0.10-20"
              />
              <div className="text-[11px] text-slate-500">
                支持 CIDR（如 10.0.0.0/24）、范围（如 10.0.0.10-10.0.0.20 或 10.0.0.10-20），多个目标可用逗号或空格分隔。
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-xs font-medium text-slate-600">端口范围（可选）</div>
              <Input
                value={createPortsSpec}
                onChange={(e) => setCreatePortsSpec(e.target.value)}
                placeholder="默认 1-65535"
              />
            </div>
            <div className="space-y-2">
              <div className="text-xs font-medium text-slate-600">并发（可选）</div>
              <Input value={createConcurrency} onChange={(e) => setCreateConcurrency(e.target.value)} placeholder="例如：256" />
            </div>

            <div className="space-y-2">
              <div className="text-xs font-medium text-slate-600">超时（ms，可选）</div>
              <Input value={createTimeoutMs} onChange={(e) => setCreateTimeoutMs(e.target.value)} placeholder="例如：30000" />
            </div>
          </div>

          <div className="text-xs text-slate-500">
            提示：不填端口范围默认扫全端口（1-65535）。如果输入了较大的 IP 段，建议配合填写端口范围以更快完成。
          </div>
        </div>

        <DialogFooter className="px-6 py-4 border-t border-slate-100 bg-slate-50/50 mt-0">
          <Button variant="outline" onClick={() => setIsCreateOpen(false)} disabled={isCreating}>
            取消
          </Button>
          <Button onClick={onCreate} disabled={isCreating}>
            {isCreating ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
            开始扫描
          </Button>
        </DialogFooter>
      </DialogContent>
      </Dialog>

      <AlertDialog open={Boolean(deleteId)} onOpenChange={(open) => (!open ? setDeleteId(null) : null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除？</AlertDialogTitle>
            <AlertDialogDescription>删除后将无法恢复。该操作只删除扫描记录，不影响目标资产。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>取消</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete} disabled={isDeleting} className="bg-red-600 hover:bg-red-700">
              {isDeleting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}


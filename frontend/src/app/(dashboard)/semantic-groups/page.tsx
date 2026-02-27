"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { toast } from "sonner"
import { RbacButton, RbacWrapper } from "@/components/rbac"

import { Button } from "@/components/ui/button"
import { PaginationBar } from "@/components/pagination-bar"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
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
import { Layers, RefreshCw, Trash2, Eye } from "lucide-react"

type UnknownRecord = Record<string, unknown>
function isRecord(v: unknown): v is UnknownRecord {
  return Boolean(v) && typeof v === "object" && !Array.isArray(v)
}

type SemanticGroup = {
  id: string
  group_name: string
  description?: string
  agent_card?: string
  version?: string
  created_at?: string
}

function fmtCreatedAt(input?: string) {
  if (!input) return "-"
  const d = new Date(input)
  if (!Number.isFinite(d.getTime())) return "-"
  try {
    // Keep it compact and stable to avoid wrapping.
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(d)
  } catch {
    return d.toLocaleString()
  }
}

export default function SemanticGroupsPage() {
  const router = useRouter()
  const [items, setItems] = useState<SemanticGroup[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [isLoading, setIsLoading] = useState(false)

  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(1)

  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState<SemanticGroup | null>(null)

  const totalPages = useMemo(() => Math.max(1, Math.ceil(totalCount / pageSize)), [totalCount, pageSize])
  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totalPages])


  const fetchData = async () => {
    setIsLoading(true)
    try {
      const offset = (page - 1) * pageSize
      const res = await api.get("/semantic-groups", { params: { offset, limit: pageSize } })
      const data = res.data as unknown
      const r = isRecord(data) ? data : {}
      const list = Array.isArray(r.items) ? (r.items as unknown[]) : []
      const total = Number(r.totalCount ?? 0)

      const adapted: SemanticGroup[] = list
        .map((x) => (isRecord(x) ? x : {}))
        .map((x) => ({
          id: String(x.id ?? ""),
          group_name: String(x.group_name ?? ""),
          description: typeof x.description === "string" ? x.description : "",
          agent_card: typeof x.agent_card === "string" ? x.agent_card : "",
          version: typeof x.version === "string" ? x.version : "",
          created_at: typeof x.created_at === "string" ? x.created_at : "",
        }))
        .filter((g) => Boolean(g.id))

      setItems(adapted)
      setTotalCount(Number.isFinite(total) && total >= 0 ? total : adapted.length)
    } catch (e) {
      console.error("Failed to fetch semantic groups", e)
      toast.error("获取语义组列表失败")
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    void fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize])

  // Semantic group is currently read-only in UI (no manual create/edit).

  const openDelete = (g: SemanticGroup) => {
    setDeleting(g)
    setDeleteOpen(true)
  }

  const confirmDelete = async () => {
    if (!deleting?.id) return
    try {
      await api.delete(`/semantic-groups/${encodeURIComponent(deleting.id)}`)
      toast.success("删除成功")
      setDeleteOpen(false)
      setDeleting(null)
      await fetchData()
    } catch (e) {
      console.error("delete semantic group failed", e)
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "删除失败")
    }
  }

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium text-slate-600">
          <span className="text-slate-900 font-semibold">语义组</span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" onClick={fetchData} disabled={isLoading} title="刷新">
            <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-slate-50">
              <TableHead>名称</TableHead>
              <TableHead className="whitespace-nowrap w-[100px]">版本</TableHead>
              <TableHead className="whitespace-nowrap w-[180px]">创建时间</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="h-24 text-center text-slate-500">
                  加载中...
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-slate-500 py-10">
                  暂无语义组
                </TableCell>
              </TableRow>
            ) : (
              items.map((g) => (
                <TableRow
                  key={g.id}
                  className="hover:bg-slate-50/60 cursor-pointer"
                  onClick={() => router.push(`/semantic-groups/${encodeURIComponent(g.id)}`)}
                >
                  <TableCell className="font-medium flex items-center gap-3 max-w-[22rem]">
                    <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 shrink-0">
                      <Layers className="w-4 h-4" />
                    </div>
                    <span className="truncate block w-full">{g.group_name}</span>
                  </TableCell>
                  <TableCell className="text-slate-600 whitespace-nowrap">{g.version || "-"}</TableCell>
                  <TableCell className="text-slate-600 whitespace-nowrap">{fmtCreatedAt(g.created_at)}</TableCell>
                  <TableCell className="text-right">
                    <div className="inline-flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={(e) => {
                          e.stopPropagation()
                          router.push(`/semantic-groups/${encodeURIComponent(g.id)}`)
                        }}
                        title="查看"
                      >
                        <Eye className="w-4 h-4" />
                      </Button>
                      <RbacWrapper requiredRole="admin">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={(e) => {
                            e.stopPropagation()
                            openDelete(g)
                          }}
                          title="删除"
                          className="text-red-600 hover:text-red-700"
                        >
                          <Trash2 className="w-4 h-4" />
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
        total={totalCount}
        page={page}
        pageSize={pageSize}
        onPageChange={setPage}
        onPageSizeChange={setPageSize}
      />

      <AlertDialog open={deleteOpen} onOpenChange={(v) => setDeleteOpen(v)}>
        <AlertDialogContent className="w-[min(96vw,36rem)] max-w-xl">
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除语义组？</AlertDialogTitle>
            <AlertDialogDescription>
              将删除语义组 <span className="font-medium text-slate-900">{deleting?.group_name || "-"}</span>。此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeleteOpen(false)}>取消</AlertDialogCancel>
            <AlertDialogAction className="bg-red-600 hover:bg-red-700" onClick={confirmDelete}>
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}


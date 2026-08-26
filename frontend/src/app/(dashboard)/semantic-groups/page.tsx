"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { useRouter } from "next/navigation"
import useSWR from "swr"
import { api } from "@/lib/api"
import {
  listSemanticGroupRoots,
  getSemanticGroupWithMembers,
} from "@/lib/semantic-groups-api"
import type {
  SemanticGroupResponse,
  SemanticGroupWithMembersResponse,
} from "@/lib/api-types"
import { toast } from "sonner"
import { RbacWrapper } from "@/components/rbac"

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
import { TableWrapper } from "@/components/ui/table-wrapper"
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
import { Badge } from "@/components/ui/badge"
import { Layers, RefreshCw, Trash2, Eye, Loader2 } from "lucide-react"
import { listAgentsAll } from "@/lib/agents-api"

const MAX_VISIBLE_MEMBER_BADGES = 2
const MEMBER_BADGE_VARIANTS = [
  "bg-emerald-50 text-emerald-700 border-emerald-100",
  "bg-sky-50 text-sky-700 border-sky-100",
  "bg-slate-100 text-slate-700 border-slate-200",
] as const
const MEMBER_BADGE_BASE = "border text-xs font-medium rounded-full px-2 py-0.5"
const MEMBER_LABEL_MAX = 24

/** Show a readable badge label; full value stays in title/tooltip. */
function displayMemberLabel(label: string): string {
  const trimmed = label.trim()
  const segment = trimmed.includes("/")
    ? (trimmed.split("/").pop() ?? trimmed)
    : trimmed
  if (segment.length <= MEMBER_LABEL_MAX) return segment
  return `${segment.slice(0, MEMBER_LABEL_MAX - 1)}…`
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

const HOVER_DELAY_MS = 180
const TOOLTIP_OFFSET = { x: 12, y: 8 }

/** Member column: badges for member abbreviations; max 2 visible; "+N" opens a portal tooltip that follows the cursor. */
function MemberBadges({ labels }: { labels?: string[] }) {
  const list = labels?.filter(Boolean) ?? []
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState({ left: 0, top: 0 })
  const closeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const visible = list.slice(0, MAX_VISIBLE_MEMBER_BADGES)
  const restCount = list.length - visible.length
  const hasOverflow = restCount > 0

  const scheduleClose = () => {
    if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current)
    closeTimeoutRef.current = setTimeout(() => setOpen(false), HOVER_DELAY_MS)
  }
  const cancelClose = () => {
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current)
      closeTimeoutRef.current = null
    }
    setOpen(true)
  }
  const updatePosition = (e: React.MouseEvent) => {
    setPosition({ left: e.clientX + TOOLTIP_OFFSET.x, top: e.clientY + TOOLTIP_OFFSET.y })
  }

  useEffect(() => {
    if (!open) return
    const onScrollOrResize = () => setOpen(false)
    window.addEventListener("scroll", onScrollOrResize, true)
    window.addEventListener("resize", onScrollOrResize)
    return () => {
      window.removeEventListener("scroll", onScrollOrResize, true)
      window.removeEventListener("resize", onScrollOrResize)
    }
  }, [open])

  useEffect(() => () => { if (closeTimeoutRef.current) clearTimeout(closeTimeoutRef.current) }, [])

  if (list.length === 0) return <span className="text-content-muted">—</span>

  const tooltipEl =
    open &&
    hasOverflow &&
    typeof document !== "undefined" ? (
      createPortal(
        <div
          role="tooltip"
          className="fixed z-[9999] min-w-[12rem] max-w-[20rem] rounded-md border border-line bg-surface px-3 py-2 text-left text-sm text-content shadow-lg"
          style={{ left: position.left, top: position.top }}
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
        >
          <div className="font-medium text-content-muted mb-1.5 text-xs">全部成员</div>
          <ul className="list-inside list-disc space-y-0.5 text-xs">
            {list.map((item, i) => (
              <li key={`${i}-${item}`} className="truncate" title={item}>
                {item}
              </li>
            ))}
          </ul>
        </div>,
        document.body
      )
    ) : null

  return (
    <>
      <span
        className="inline-flex max-w-full flex-wrap items-center gap-1.5 align-middle"
        onMouseEnter={hasOverflow ? (e) => { updatePosition(e); cancelClose() } : undefined}
        onMouseMove={hasOverflow && open ? updatePosition : undefined}
        onMouseLeave={hasOverflow ? scheduleClose : undefined}
      >
        {visible.map((label, i) => (
          <Badge
            key={`${i}-${label}`}
            variant="outline"
            title={label}
            className={`${MEMBER_BADGE_VARIANTS[i % MEMBER_BADGE_VARIANTS.length]} ${MEMBER_BADGE_BASE}`}
          >
            {displayMemberLabel(label)}
          </Badge>
        ))}
        {hasOverflow && (
          <Badge
            variant="outline"
            className={`${MEMBER_BADGE_VARIANTS[2]} ${MEMBER_BADGE_BASE}`}
          >
            +{restCount}
          </Badge>
        )}
      </span>
      {tooltipEl}
    </>
  )
}

/** Derive member labels from with-members API: child group names + data source namespace/name. */
function labelsFromWithMembers(data: SemanticGroupWithMembersResponse | null): string[] {
  if (!data) return []
  const childLabels = data.child_groups.map((c) => c.group_name || c.id).filter(Boolean)
  const memberLabels = data.members.map((m) => {
    if (m.semantic_domain) {
      return `${m.semantic_domain.dd_namespace}/${m.semantic_domain.dd_name}`
    }
    return m.relation.sd_id || ""
  }).filter(Boolean)
  return [...childLabels, ...memberLabels]
}

/** Fetches with-members for one group and renders member badges (from existing API). */
function MemberBadgesFromApi({ groupId }: { groupId: string }) {
  const { data, isLoading } = useSWR(
    ["semantic-group-with-members", groupId],
    () => getSemanticGroupWithMembers(groupId)
  )
  const labels = useMemo(() => labelsFromWithMembers(data ?? null), [data])
  if (isLoading && labels.length === 0) {
    return <span className="text-content-muted">…</span>
  }
  return <MemberBadges labels={labels} />
}

/** SWR fetcher: key is roots URL, returns root-only list (client-side pagination). */
async function rootsFetcher(): Promise<{ items: SemanticGroupResponse[]; totalCount: number }> {
  return listSemanticGroupRoots()
}

const SEMANTIC_GROUPS_COLUMNS = [
  { id: "name", size: 260, minSize: 180, maxSize: 420 },
  { id: "members", size: 280, minSize: 200, maxSize: 480 },
  { id: "created", size: 168, minSize: 152, maxSize: 220 },
  { id: "actions", size: 112, minSize: 96, maxSize: 160 },
] as const

const SEMANTIC_GROUPS_DEPENDENT_COLUMNS = [
  { id: "agent", size: 240 },
  { id: "namespace", size: 112 },
  { id: "actions", size: 176 },
] as const

export default function SemanticGroupsPage() {
  const router = useRouter()
  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(1)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState<SemanticGroupResponse | null>(null)
  const [checkingDependency, setCheckingDependency] = useState(false)
  const [dependentAgents, setDependentAgents] = useState<{ name: string; namespace: string }[]>([])
  const [showDependencyDialog, setShowDependencyDialog] = useState(false)
  const [deletingAgentKey, setDeletingAgentKey] = useState<string | null>(null)
  const [confirmDeleteAgent, setConfirmDeleteAgent] = useState<{ name: string; namespace: string } | null>(null)

  const rootsKey = useMemo(() => ["/semantic-groups/roots"] as const, [])
  const { data: listData, error: listError, isLoading, mutate: mutateList } = useSWR(
    rootsKey,
    rootsFetcher
  )

  const allItems = useMemo(() => listData?.items ?? [], [listData])
  const totalCount = useMemo(() => {
    const n = listData?.totalCount
    return typeof n === "number" && Number.isFinite(n) && n >= 0 ? n : 0
  }, [listData])
  const pageItems = useMemo(
    () => allItems.slice((page - 1) * pageSize, page * pageSize),
    [allItems, page, pageSize]
  )
  const items = pageItems

  useEffect(() => {
    if (listError) toast.error("获取语义组列表失败")
  }, [listError])

  const totalPages = useMemo(() => Math.max(1, Math.ceil(totalCount / pageSize)), [totalCount, pageSize])
  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [totalPages, page])

  const fetchData = () => mutateList()

  // Semantic group is currently read-only in UI (no manual create/edit).

  const openDelete = async (g: SemanticGroupResponse) => {
    setDeleting(g)
    setCheckingDependency(true)
    try {
      const { items } = await listAgentsAll()
      const deps = items.filter(
        (a) => a.dataPolicy?.semanticGroupID === g.id
      ).map((a) => ({ name: a.name, namespace: a.namespace }))
      if (deps.length > 0) {
        setDependentAgents(deps)
        setShowDependencyDialog(true)
        return
      }
    } catch (err) {
      console.error("check group DAC dependencies failed", err)
      // 检查失败时仍允许删除，不阻塞用户
    } finally {
      setCheckingDependency(false)
    }
    setDeleteOpen(true)
  }

  const refreshDeleteDependencies = async () => {
    if (!deleting?.id) return []
    setCheckingDependency(true)
    try {
      const { items } = await listAgentsAll()
      const deps = items.filter(
        (a) => a.dataPolicy?.semanticGroupID === deleting.id
      ).map((a) => ({ name: a.name, namespace: a.namespace }))
      setDependentAgents(deps)
      if (deps.length === 0) {
        setShowDependencyDialog(false)
        setDeleteOpen(true)
      }
      return deps
    } catch (err) {
      console.error("refresh group DAC dependencies failed", err)
      return []
    } finally {
      setCheckingDependency(false)
    }
  }

  const handleDeleteAgent = async () => {
    if (!deleting || !confirmDeleteAgent) return
    const agent = confirmDeleteAgent
    const key = `${agent.namespace}/${agent.name}`
    setDeletingAgentKey(key)
    try {
      await api.delete(`/namespaces/${encodeURIComponent(agent.namespace)}/agents/${encodeURIComponent(agent.name)}`)
      toast.success(`智能体 ${agent.name} 已删除`)
      setConfirmDeleteAgent(null)
      await refreshDeleteDependencies()
    } catch (err) {
      console.error("delete agent failed", err)
      const e = err as { response?: { data?: { message?: string } } }
      toast.error(e.response?.data?.message || "删除智能体失败")
    } finally {
      setDeletingAgentKey(null)
    }
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
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <span className="text-sm font-semibold text-content">语义组</span>
        <Button variant="outline" size="icon" onClick={fetchData} disabled={isLoading} title="刷新" aria-label="刷新">
          <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      <TableWrapper>
        <Table storageKey="semantic-groups-list" columns={[...SEMANTIC_GROUPS_COLUMNS]}>
          <TableHeader>
            <TableRow className="bg-surface-muted">
              <TableHead columnId="name">名称</TableHead>
              <TableHead columnId="members">成员</TableHead>
              <TableHead columnId="created">创建时间</TableHead>
              <TableHead columnId="actions" className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="h-24 text-center text-content-muted">
                  加载中…
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-content-muted py-10">
                  暂无语义组
                </TableCell>
              </TableRow>
            ) : (
              items.map((g) => (
                <TableRow
                  key={g.id}
                  className="align-top hover:bg-surface-muted/60 cursor-pointer"
                  onClick={() => router.push(`/semantic-groups/${encodeURIComponent(g.id)}`)}
                >
                  <TableCell columnId="name" className="align-top font-medium">
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-cta/10 text-cta">
                        <Layers className="h-4 w-4" />
                      </div>
                      <span className="min-w-0 truncate" title={g.group_name}>
                        {g.group_name}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell
                    columnId="members"
                    className="min-w-0 align-top text-content"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <MemberBadgesFromApi groupId={g.id} />
                  </TableCell>
                  <TableCell
                    columnId="created"
                    className="whitespace-nowrap align-top tabular-nums text-sm text-content-muted"
                  >
                    {fmtCreatedAt(g.created_at)}
                  </TableCell>
                  <TableCell columnId="actions" className="align-top text-right">
                    <div className="inline-flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={(e) => {
                          e.stopPropagation()
                          router.push(`/semantic-groups/${encodeURIComponent(g.id)}`)
                        }}
                        title="查看"
                        aria-label="查看"
                      >
                        <Eye className="w-4 h-4" />
                      </Button>
                      <RbacWrapper requiredPermission="semantic-group:manage">
                        <Button
                          variant="ghost"
                          size="icon"
                          disabled={checkingDependency}
                          onClick={(e) => {
                            e.stopPropagation()
                            openDelete(g)
                          }}
                          title="删除"
                          aria-label="删除"
                          className="text-red-600 hover:text-red-700"
                        >
                          {checkingDependency && deleting?.id === g.id
                            ? <Loader2 className="w-4 h-4 animate-spin" />
                            : <Trash2 className="w-4 h-4" />}
                        </Button>
                      </RbacWrapper>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableWrapper>

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
              将删除语义组 <span className="font-medium text-content">{deleting?.group_name || "-"}</span>。此操作不可撤销。
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

      {/* DAC 依赖关系提示弹窗 */}
      <AlertDialog open={showDependencyDialog} onOpenChange={setShowDependencyDialog}>
        <AlertDialogContent className="w-[min(96vw,56rem)] max-w-4xl">
          <AlertDialogHeader>
            <AlertDialogTitle>无法删除 - 存在关联的智能体</AlertDialogTitle>
            <AlertDialogDescription>
              语义组 <span className="font-medium text-content">{deleting?.group_name || "-"}</span> 正在被以下 {dependentAgents.length} 个智能体使用，无法删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="mt-4 space-y-3 px-6">
            <TableWrapper className="max-h-[320px] overflow-auto rounded-md">
              <Table storageKey="semantic-groups-dependent-agents" columns={[...SEMANTIC_GROUPS_DEPENDENT_COLUMNS]}>
                <TableHeader>
                  <TableRow className="bg-surface-muted">
                    <TableHead columnId="agent">智能体名称</TableHead>
                    <TableHead columnId="namespace">命名空间</TableHead>
                    <TableHead columnId="actions" className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dependentAgents.map((a, idx) => (
                    <TableRow key={`${a.namespace}/${a.name}/${idx}`}>
                      <TableCell columnId="agent" className="font-medium whitespace-normal break-all">{a.name}</TableCell>
                      <TableCell columnId="namespace" className="text-content-muted">{a.namespace}</TableCell>
                      <TableCell columnId="actions" className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={Boolean(deletingAgentKey)}
                            onClick={() => setConfirmDeleteAgent(a)}
                            className="text-red-600 hover:text-red-700 whitespace-nowrap cursor-pointer"
                          >
                            {deletingAgentKey === `${a.namespace}/${a.name}` ? "删除中…" : "删除智能体"}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setShowDependencyDialog(false)
                              router.push(`/agents/${encodeURIComponent(a.namespace)}/${encodeURIComponent(a.name)}`)
                            }}
                            className="text-cta hover:text-cta/90 whitespace-nowrap cursor-pointer"
                          >
                            查看详情 →
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableWrapper>
            <div className="text-sm text-content">可直接「删除智能体」解除引用后再删除语义组，也可先修改智能体关联的语义组。</div>
          </div>
          <AlertDialogFooter>
            <AlertDialogAction onClick={() => setShowDependencyDialog(false)}>知道了</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 删除智能体确认弹窗 */}
      <AlertDialog open={!!confirmDeleteAgent} onOpenChange={(open) => !open && setConfirmDeleteAgent(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除智能体？</AlertDialogTitle>
            <AlertDialogDescription>
              此操作将永久删除智能体「{confirmDeleteAgent?.name}」（{confirmDeleteAgent?.namespace}/{confirmDeleteAgent?.name}），
              删除后该智能体对语义组的引用将被解除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={Boolean(deletingAgentKey)}>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void handleDeleteAgent()}
              className="bg-red-600 hover:bg-red-700 text-white"
              disabled={Boolean(deletingAgentKey)}
            >
              {deletingAgentKey ? "删除中..." : "确认删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}


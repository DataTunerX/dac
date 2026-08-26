"use client"

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"
import useSWR from "swr"
import { api } from "@/lib/api"
import { listAgentsAll } from "@/lib/agents-api"
import { getSemanticGroupWithMembers } from "@/lib/semantic-groups-api"
import { semanticGroupKey } from "@/lib/swr-keys"
import type {
  SemanticGroupResponse,
  SemanticGroupInfoResponse,
  DDGroupRelationResponse,
} from "@/lib/api-types"
import { toast } from "sonner"
import { Markdown, defaultMarkdownComponents } from "@/components/markdown"
import { RbacWrapper } from "@/components/rbac"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
import { ArrowLeft, ChevronRight, Database, Layers, Link2, RefreshCw, Trash2, X, FileText, Maximize2, Scan, Loader2 } from "lucide-react"
import { RelationGraph, REL_GRAPH } from "@/components/relation-graph"

function shortID(id: string) {
  const s = String(id || "")
  if (s.length <= 18) return s
  return `${s.slice(0, 8)}…${s.slice(-6)}`
}

/** First segment of description before the first comma (ASCII or Chinese ，); empty if absent. */
function descriptionLead(description?: string): string {
  const s = String(description ?? "").trim()
  if (!s) return ""
  const commaAscii = s.indexOf(",")
  const commaZh = s.indexOf("，")
  const comma =
    commaAscii === -1 && commaZh === -1
      ? -1
      : commaAscii === -1
        ? commaZh
        : commaZh === -1
          ? commaAscii
          : Math.min(commaAscii, commaZh)
  return comma === -1 ? s : s.slice(0, comma).trim()
}

async function fetcherGroupWithMembers(id: string) {
  const data = await getSemanticGroupWithMembers(id)
  if (!data?.group) return null
  return data
}

/** Parse hierarchy path from query; last segment must match current id. */
function parsePathQuery(pathQuery: string | null, currentId: string): string[] {
  if (!currentId) return []
  if (!pathQuery?.trim()) return [currentId]
  const segments = pathQuery.split(",").map((s) => s.trim()).filter(Boolean)
  if (segments.length === 0) return [currentId]
  if (segments[segments.length - 1] !== currentId) return [currentId]
  return segments
}

/** Build path query for a given path array (no leading/trailing comma). */
function pathQueryFromIds(ids: string[]): string {
  return ids.filter(Boolean).join(",")
}

export default function SemanticGroupDetailPage() {
  const router = useRouter()
  const params = useParams<{ id: string }>()
  const searchParams = useSearchParams()
  const groupId = String(params?.id ?? "")
  const pathQuery = searchParams.get("path")
  const pathIds = useMemo(() => parsePathQuery(pathQuery, groupId), [pathQuery, groupId])
  const parentId = pathIds.length > 1 ? pathIds[pathIds.length - 2]! : null
  const backHref = parentId
    ? `/semantic-groups/${parentId}?path=${pathQueryFromIds(pathIds.slice(0, -1))}`
    : "/semantic-groups"
  const hrefForChild = (childId: string) =>
    `/semantic-groups/${encodeURIComponent(childId)}?path=${pathQueryFromIds([...pathIds, childId])}`

  const swrKey = groupId ? semanticGroupKey(groupId) : null
  const { data: swrData, error: swrError, isLoading, mutate } = useSWR(
    swrKey,
    ([, id]) => fetcherGroupWithMembers(id)
  )

  const group = useMemo(() => swrData?.group ?? null, [swrData])
  const childGroups = useMemo(() => swrData?.child_groups ?? [], [swrData])
  const relations = useMemo(() => {
    const mems = swrData?.members ?? []
    return mems
      .map((m) => m.relation)
      .filter((r): r is DDGroupRelationResponse => Boolean(r && Number(r.id) > 0))
  }, [swrData])
  const sdMeta = useMemo(() => {
    const meta: Record<string, { dd_namespace: string; dd_name: string }> = {}
    const mems = swrData?.members ?? []
    for (const m of mems) {
      const sd = m.semantic_domain
      const sid = m.relation?.sd_id
      if (sid && sd?.dd_namespace != null && sd?.dd_name != null) {
        meta[sid] = { dd_namespace: sd.dd_namespace, dd_name: sd.dd_name }
      }
    }
    return meta
  }, [swrData])

  const [deleteRelOpen, setDeleteRelOpen] = useState(false)
  const [deletingRel, setDeletingRel] = useState<DDGroupRelationResponse | null>(null)
  const [reasonOpen, setReasonOpen] = useState(false)
  const [reasonRel, setReasonRel] = useState<DDGroupRelationResponse | null>(null)
  const [deleteGroupOpen, setDeleteGroupOpen] = useState(false)
  const [showDependencyDialog, setShowDependencyDialog] = useState(false)
  const [checkingDependency, setCheckingDependency] = useState(false)
  const [isDeletingGroup, setIsDeletingGroup] = useState(false)
  const [dependentAgents, setDependentAgents] = useState<Array<{ name: string; namespace: string }>>([])
  const [graphMaxHeight, setGraphMaxHeight] = useState<number>(REL_GRAPH.maxHeight)
  const [graphFullscreenOpen, setGraphFullscreenOpen] = useState(false)
  const [fullscreenScale, setFullscreenScale] = useState(1)

  // Graph interactions: fullscreen + drag-to-pan (mouse).
  const graphViewportInlineRef = useRef<HTMLDivElement | null>(null)
  const graphViewportFullscreenRef = useRef<HTMLDivElement | null>(null)
  const [isPanning, setIsPanning] = useState(false)
  const panRef = useRef<{
    active: boolean
    pointerId: number | null
    startClientX: number
    startClientY: number
    startScrollLeft: number
    startScrollTop: number
  }>({
    active: false,
    pointerId: null,
    startClientX: 0,
    startClientY: 0,
    startScrollLeft: 0,
    startScrollTop: 0,
  })

  const isInteractiveTarget = (t: EventTarget | null) => {
    // Note: lucide icons render as SVGElement; Element covers both HTML + SVG.
    const el = t instanceof Element ? t : null
    if (!el) return false
    return Boolean(el.closest('button,a,input,textarea,select,[role="button"],[data-no-pan="true"]'))
  }

  const attachPanHandlers = (kind: "inline" | "fullscreen") => {
    const getEl = () => (kind === "fullscreen" ? graphViewportFullscreenRef.current : graphViewportInlineRef.current)
    return {
      onPointerDown: (e: ReactPointerEvent<HTMLDivElement>) => {
        if (e.pointerType !== "mouse") return
        if (e.button !== 0) return
        if (isInteractiveTarget(e.target)) return
        const el = getEl()
        if (!el) return
        panRef.current.active = true
        panRef.current.pointerId = e.pointerId
        panRef.current.startClientX = e.clientX
        panRef.current.startClientY = e.clientY
        panRef.current.startScrollLeft = el.scrollLeft
        panRef.current.startScrollTop = el.scrollTop
        setIsPanning(true)
        try {
          el.setPointerCapture(e.pointerId)
        } catch {
          // ignore
        }
        e.preventDefault()
      },
      onPointerMove: (e: ReactPointerEvent<HTMLDivElement>) => {
        if (!panRef.current.active) return
        if (panRef.current.pointerId !== e.pointerId) return
        const el = getEl()
        if (!el) return
        const dx = e.clientX - panRef.current.startClientX
        const dy = e.clientY - panRef.current.startClientY
        el.scrollLeft = panRef.current.startScrollLeft - dx
        el.scrollTop = panRef.current.startScrollTop - dy
        e.preventDefault()
      },
      onPointerUp: (e: ReactPointerEvent<HTMLDivElement>) => {
        if (panRef.current.pointerId !== e.pointerId) return
        panRef.current.active = false
        panRef.current.pointerId = null
        setIsPanning(false)
      },
      onPointerCancel: (e: ReactPointerEvent<HTMLDivElement>) => {
        if (panRef.current.pointerId !== e.pointerId) return
        panRef.current.active = false
        panRef.current.pointerId = null
        setIsPanning(false)
      },
    }
  }

  const ddBuckets = useMemo(() => {
    type Bucket = {
      key: string
      dd_namespace: string
      dd_name: string
      items: DDGroupRelationResponse[]
      hasDD: boolean
      isLoading: boolean
    }
    const map = new Map<string, Bucket>()
    for (const r of relations) {
      const meta = sdMeta[r.sd_id]
      const isLoading = !meta
      const hasDD = Boolean(meta?.dd_namespace && meta?.dd_name)
      const dd_namespace = meta?.dd_namespace || ""
      const dd_name = meta?.dd_name || ""
      const key = hasDD ? `${dd_namespace}/${dd_name}` : "__unknown__"
      
      let b = map.get(key)
      if (!b) {
        b = { key, dd_namespace, dd_name, items: [], hasDD, isLoading: false }
      }
      
      b.items.push(r)
      if (isLoading) b.isLoading = true
      
      // keep latest meta once loaded
      if (hasDD && (!b.dd_namespace || !b.dd_name)) {
        b.dd_namespace = dd_namespace
        b.dd_name = dd_name
        b.hasDD = true
      }
      map.set(key, b)
    }

    const arr = Array.from(map.values())
    // Put unknown/loading to the end.
    arr.sort((a, b) => {
      if (a.key === "__unknown__" && b.key !== "__unknown__") return 1
      if (b.key === "__unknown__" && a.key !== "__unknown__") return -1
      return a.key.localeCompare(b.key)
    })
    return arr
  }, [relations, sdMeta])

  useEffect(() => {
    const calc = () => {
      // Avoid hard-coded height: adapt to viewport while keeping a reasonable cap.
      // Reserve space for page chrome; the graph container itself can scroll.
      const vh = typeof window !== "undefined" ? window.innerHeight : 900
      const reserved = 360
      const next = Math.max(320, Math.min(REL_GRAPH.maxHeight, vh - reserved))
      setGraphMaxHeight(next)
    }
    calc()
    window.addEventListener("resize", calc)
    return () => window.removeEventListener("resize", calc)
  }, [])

  const graphHeight = useMemo(() => {
    const topPad = 56
    const bottomPad = 56
    const gapY = 22
    const headerH = 88
    const rowH = 76
    const childBlockH =
      childGroups.length > 0
        ? childGroups.length * REL_GRAPH.nodeH + (childGroups.length - 1) * gapY
        : 0
    const ddHeights = ddBuckets.map((b) => Math.max(REL_GRAPH.nodeH, headerH + b.items.length * rowH))
    const ddTotal = ddHeights.reduce((a, x) => a + x, 0) + Math.max(0, ddHeights.length - 1) * gapY
    const midGap = childBlockH > 0 && ddTotal > 0 ? gapY : 0
    const contentH = childBlockH + midGap + ddTotal
    return Math.max(REL_GRAPH.minHeight, topPad + contentH + bottomPad)
  }, [ddBuckets, childGroups.length])

  // Fullscreen zoom helpers (industry standard: zoom +/- + fit + reset).
  const clampScale = (v: number) => Math.max(0.25, Math.min(2.5, v))
  const setFsScale = (v: number) => setFullscreenScale(clampScale(v))

  const fitFsAll = () => {
    const el = graphViewportFullscreenRef.current
    if (!el) return
    const w = Math.max(1, el.clientWidth)
    const h = Math.max(1, el.clientHeight)
    setFsScale(Math.min(w / REL_GRAPH.width, h / graphHeight) * 0.98)
  }

  useEffect(() => {
    if (swrError) toast.error("加载语义组失败")
  }, [swrError])

  // Optional: correct path when API parent_id disagrees with path (e.g. direct visit with wrong path)
  useEffect(() => {
    if (!group || pathIds.length < 2 || groupId !== group.id) return
    const expectedParent = group.parent_id
    if (expectedParent == null) return
    const pathParent = pathIds[pathIds.length - 2]
    if (pathParent === expectedParent) return
    const corrected = [expectedParent, groupId]
    router.replace(`/semantic-groups/${encodeURIComponent(groupId)}?path=${pathQueryFromIds(corrected)}`, { scroll: false })
  }, [group, groupId, pathIds, router])

  const refreshData = () => mutate()

  const openDeleteRel = (r: DDGroupRelationResponse) => {
    setDeletingRel(r)
    setDeleteRelOpen(true)
  }

  const openReason = (r: DDGroupRelationResponse) => {
    setReasonRel(r)
    setReasonOpen(true)
  }

  const closeReason = () => {
    setReasonOpen(false)
    setReasonRel(null)
  }

  const confirmDeleteRel = async () => {
    if (!deletingRel?.id) return
    try {
      await api.delete(`/dd-group-relations/${encodeURIComponent(String(deletingRel.id))}`)
      toast.success("已解除关联")
      setDeleteRelOpen(false)
      setDeletingRel(null)
      await mutate()
    } catch (e) {
      console.error("delete relation failed", e)
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "解除关联失败")
    }
  }

  const openDeleteGroup = async () => {
    if (!group?.id || checkingDependency) return
    setCheckingDependency(true)
    try {
      const { items } = await listAgentsAll()
      const deps = items
        .filter((agent) => agent.dataPolicy?.semanticGroupID === group.id)
        .map((agent) => ({
          name: agent.name,
          namespace: agent.namespace,
        }))

      if (deps.length > 0) {
        setDependentAgents(deps)
        setShowDependencyDialog(true)
        return
      }

      setDeleteGroupOpen(true)
    } catch (err) {
      console.error("check group DAC dependencies failed", err)
      toast.error("检查依赖关系失败")
    } finally {
      setCheckingDependency(false)
    }
  }

  const confirmDeleteGroup = async () => {
    if (!group?.id || isDeletingGroup) return
    setIsDeletingGroup(true)
    try {
      await api.delete(`/semantic-groups/${encodeURIComponent(group.id)}`)
      toast.success("删除成功")
      router.push(backHref)
    } catch (e) {
      console.error("delete semantic group failed", e)
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "删除失败")
    } finally {
      setIsDeletingGroup(false)
      setDeleteGroupOpen(false)
    }
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <Link
              href={backHref}
              className="inline-flex items-center -ml-2 h-8 px-2 text-content-muted hover:text-content text-sm"
            >
              <ArrowLeft className="w-4 h-4 mr-1" />
              返回
            </Link>
            <nav className="flex items-center text-sm text-content-muted min-w-0 flex-wrap gap-y-1" aria-label="Breadcrumb">
              <Link href="/semantic-groups" className="hover:text-content">
                语义组
              </Link>
              {pathIds.slice(0, -1).map((pid, i) => (
                <span key={pid} className="flex items-center shrink-0">
                  <ChevronRight className="w-4 h-4 mx-1 text-content-muted" />
                  <Link
                    href={`/semantic-groups/${encodeURIComponent(pid)}?path=${pathQueryFromIds(pathIds.slice(0, i + 1))}`}
                    className="hover:text-content truncate max-w-[120px] inline-block"
                  >
                    {shortID(pid)}
                  </Link>
                </span>
              ))}
              <ChevronRight className="w-4 h-4 mx-2 text-content-muted shrink-0" />
              <span className="font-medium text-content truncate">{group?.group_name || groupId}</span>
            </nav>
          </div>

          <div className="flex items-center gap-2">
            <Button variant="outline" size="icon" onClick={() => void refreshData()} title="刷新" aria-label="刷新">
              <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
            </Button>
            <RbacWrapper requiredPermission="semantic-group:manage">
              <Button
                variant="outline"
                onClick={() => void openDeleteGroup()}
                disabled={!group?.id || checkingDependency || isDeletingGroup}
                className="bg-surface hover:bg-red-50 hover:text-red-600 hover:border-red-200"
              >
                {checkingDependency || isDeletingGroup
                  ? <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  : <Trash2 className="w-4 h-4 mr-2" />}
                删除
              </Button>
            </RbacWrapper>
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm font-medium text-content">
          <Layers className="w-4 h-4 text-content-muted" />
          基本信息
        </div>
        <Card className="p-6 border-line">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <div className="space-y-1 min-w-0">
              <div className="text-xs text-content-muted">名称</div>
              <div className="text-sm text-content truncate">{group?.group_name || "-"}</div>
            </div>
            <div className="space-y-1 min-w-0">
              <div className="text-xs text-content-muted">版本</div>
              <div className="text-sm text-content truncate">{group?.version || "-"}</div>
            </div>
            <div className="space-y-1 min-w-0">
              <div className="text-xs text-content-muted">创建时间</div>
              <div className="text-sm text-content truncate">
                {group?.created_at ? new Date(group.created_at).toLocaleString() : "-"}
              </div>
            </div>
          </div>
        </Card>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm font-medium text-content">
          <FileText className="w-4 h-4 text-content-muted" />
          描述
        </div>
        <Card className="p-6 border-line">
          {group?.description ? (
            <Markdown>{group.description}</Markdown>
          ) : (
            <div className="text-sm text-content-muted">-</div>
          )}
        </Card>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm font-medium text-content">
          <Layers className="w-4 h-4 text-content-muted" />
          层级成员列表
        </div>
        <Card className="border-line overflow-hidden">
          {isLoading && !group ? (
            <div className="px-4 py-6 text-sm text-content-muted">加载中…</div>
          ) : !group?.parent_id && childGroups.length > 0 ? (
            <ul className="list-none divide-y divide-[var(--color-line)]" role="list">
              {childGroups.map((cg) => (
                <li key={cg.id}>
                  <Link
                    href={hrefForChild(cg.id)}
                    className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-surface-muted/60 transition-colors min-w-0"
                  >
                    <span className="flex items-center gap-3 min-w-0">
                      <span className="w-8 h-8 rounded-full bg-surface-muted flex items-center justify-center text-content-muted shrink-0">
                        <Layers className="w-4 h-4" />
                      </span>
                      <span className="font-medium text-content truncate">{cg.group_name || cg.id}</span>
                      <span className="text-xs text-content-muted truncate hidden sm:inline">{descriptionLead(cg.description) || "—"}</span>
                    </span>
                    <ChevronRight className="w-4 h-4 text-content-muted shrink-0" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          ) : ddBuckets.length > 0 ? (
            <ul className="list-none divide-y divide-[var(--color-line)]" role="list">
              {ddBuckets.map((b) => {
                const href = b.hasDD
                  ? `/datasources/${encodeURIComponent(b.dd_namespace)}/${encodeURIComponent(b.dd_name)}`
                  : "#"
                const isClickable = b.hasDD
                return (
                  <li key={b.key}>
                    <Link
                      href={href}
                      className={`flex items-center justify-between gap-3 px-4 py-3 border-l-2 border-l-transparent min-w-0 ${
                        isClickable
                          ? "hover:bg-surface-muted/60 transition-colors"
                          : "bg-surface-muted/40 cursor-not-allowed opacity-70"
                      }`}
                      onClick={isClickable ? undefined : (e) => e.preventDefault()}
                      aria-disabled={!isClickable}
                    >
                      <span className="flex items-center gap-3 min-w-0">
                        <span className="w-8 h-8 rounded-full bg-surface-muted flex items-center justify-center text-content-muted shrink-0">
                          <Database className="w-4 h-4" />
                        </span>
                        <span className="font-medium text-content truncate">
                          {b.hasDD ? `${b.dd_namespace} / ${b.dd_name}` : "加载中…"}
                        </span>
                        <span className="text-xs text-content-muted shrink-0">{b.items.length} 个关联</span>
                      </span>
                      {isClickable && <ChevronRight className="w-4 h-4 text-content-muted shrink-0" aria-hidden />}
                    </Link>
                  </li>
                )
              })}
            </ul>
          ) : (
            <div className="px-4 py-6 text-sm text-content-muted">暂无成员</div>
          )}
        </Card>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-medium text-content">
            <Link2 className="w-4 h-4 text-content-muted" />
            组成员
          </div>
        </div>

        <Card className="border-line">
          <div
            className={[
              "relative overflow-auto bg-surface-muted/40",
              isPanning ? "cursor-grabbing" : "cursor-grab",
            ].join(" ")}
            ref={graphViewportInlineRef}
            style={{
              maxHeight: graphMaxHeight,
              backgroundImage:
                `radial-gradient(circle at 1px 1px, rgba(148,163,184,${REL_GRAPH.gridDotOpacity}) 1px, transparent 0)`,
              backgroundSize: `${REL_GRAPH.gridDotSize}px ${REL_GRAPH.gridDotSize}px`,
            }}
            {...attachPanHandlers("inline")}
          >
            {/* Single action: fullscreen */}
            <div className="sticky top-0 z-20 flex justify-end p-2 pointer-events-none">
              <Button
                variant="outline"
                size="icon"
                className="pointer-events-auto h-8 w-8 border border-line bg-surface/90 backdrop-blur shadow-sm"
                title="Fullscreen"
                onClick={() => setGraphFullscreenOpen(true)}
                aria-label="Fullscreen"
              >
                <Maximize2 className="w-4 h-4" />
              </Button>
            </div>

            <RelationGraph
              group={group}
              groupId={groupId}
              childGroups={childGroups}
              ddBuckets={ddBuckets}
              graphHeight={graphHeight}
              isLoading={isLoading}
              markerId="arrow"
              onOpenReason={openReason}
              onDeleteRel={openDeleteRel}
              onNavigateToGroup={(id) => router.push(hrefForChild(id))}
              onNavigateToDataSource={(ns, name) => router.push(`/datasources/${encodeURIComponent(ns)}/${encodeURIComponent(name)}`)}
            />
          </div>
        </Card>
      </div>

      {/* Fullscreen graph */}
      <Dialog
        open={graphFullscreenOpen}
        onOpenChange={(v) => {
          if (v) {
            // Default to "fit" when opening fullscreen.
            setTimeout(() => fitFsAll(), 0)
          } else {
            setFullscreenScale(1)
          }
        }}
      >
        <DialogContent className="w-[min(98vw,1280px)] max-w-[98vw] h-[92vh] max-h-[92vh] flex flex-col p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50">
            <div className="flex items-center justify-between gap-3">
              <DialogTitle>组成员</DialogTitle>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-content-muted hover:text-content"
                onClick={() => setGraphFullscreenOpen(false)}
                aria-label="关闭"
                title="关闭"
              >
                <X className="w-4 h-4" />
              </Button>
            </div>
          </DialogHeader>

          <div className="flex-1 min-h-0">
            <div
              className={[
                "relative h-full overflow-auto bg-surface-muted/40",
                isPanning ? "cursor-grabbing" : "cursor-grab",
              ].join(" ")}
              ref={graphViewportFullscreenRef}
              style={{
                backgroundImage:
                  `radial-gradient(circle at 1px 1px, rgba(148,163,184,${REL_GRAPH.gridDotOpacity}) 1px, transparent 0)`,
                backgroundSize: `${REL_GRAPH.gridDotSize}px ${REL_GRAPH.gridDotSize}px`,
              }}
              {...attachPanHandlers("fullscreen")}
              onWheel={(e) => {
                // Fullscreen: treat wheel as zoom (industry common in canvas views).
                // But never steal wheel inside interactive/scrollable nodes.
                if (isInteractiveTarget(e.target)) return
                e.preventDefault()
                const factor = e.deltaY > 0 ? 0.92 : 1.08
                setFsScale(fullscreenScale * factor)
              }}
            >
              <div className="sticky top-0 z-20 flex justify-end p-2 pointer-events-none">
                <div className="pointer-events-auto flex items-center gap-1 rounded-lg border border-line bg-surface/90 backdrop-blur px-1.5 py-1 shadow-sm">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    title="Fit"
                    aria-label="Fit"
                    onClick={fitFsAll}
                  >
                    <Scan className="w-4 h-4" />
                  </Button>
                  <div className="text-[11px] tabular-nums text-content w-[52px] text-center select-none">
                    {Math.round(fullscreenScale * 100)}%
                  </div>
                </div>
              </div>

              <div
                className="relative mx-auto"
                style={{
                  width: REL_GRAPH.width * fullscreenScale,
                  height: graphHeight * fullscreenScale,
                }}
              >
                <div
                  className={`relative ${REL_GRAPH.minWidthClass}`}
                  style={{
                    width: REL_GRAPH.width,
                    height: graphHeight,
                    transform: `scale(${fullscreenScale})`,
                    transformOrigin: "top left",
                  }}
                >
                  <RelationGraph
                    group={group}
                    groupId={groupId}
                    childGroups={childGroups}
                    ddBuckets={ddBuckets}
                    graphHeight={graphHeight}
                    isLoading={isLoading}
                    markerId="arrow-fs"
                    onOpenReason={openReason}
                    onDeleteRel={openDeleteRel}
                    onNavigateToGroup={(id) => router.push(hrefForChild(id))}
                    onNavigateToDataSource={(ns, name) => router.push(`/datasources/${encodeURIComponent(ns)}/${encodeURIComponent(name)}`)}
                  />
                </div>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={reasonOpen}
        onOpenChange={(v) => {
          if (!v) {
            closeReason()
            return
          }
          setReasonOpen(true)
        }}
      >
        <DialogContent className="w-[min(96vw,48rem)] max-w-2xl max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50">
            <div className="flex items-center justify-between gap-3">
              <DialogTitle>分组策略</DialogTitle>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-content-muted hover:text-content"
                onClick={closeReason}
                aria-label="关闭"
                title="关闭"
              >
                <X className="w-4 h-4" />
              </Button>
            </div>
          </DialogHeader>

          <div className="space-y-4 flex-1 min-h-0 overflow-y-auto px-6 py-6">
            <div className="space-y-1.5">
              <div className="text-xs text-content-muted">semantic domain id</div>
              {reasonRel?.sd_id ? (
                <div className="rounded-md border border-line bg-surface px-3 py-2 text-sm font-mono text-content break-words">
                  {reasonRel.sd_id}
                </div>
              ) : (
                <div className="rounded-md border border-line bg-surface px-3 py-2 text-sm font-mono text-content break-words">
                  -
                </div>
              )}
            </div>
            <div className="space-y-1.5">
              <div className="text-xs text-content-muted">data descriptor</div>
              <div className="rounded-md border border-line bg-surface px-3 py-2 text-sm font-mono text-content break-words">
                {(() => {
                  const id = reasonRel?.sd_id || ""
                  const meta = id ? sdMeta[id] : undefined
                  if (!id) return "-"
                  if (!meta) return "加载中…"
                  if (!meta.dd_namespace && !meta.dd_name) return "-"
                  return `${meta.dd_namespace || "-"} / ${meta.dd_name || "-"}`
                })()}
              </div>
            </div>
            <div className="space-y-1.5">
              <div className="text-xs text-content-muted">分组策略</div>
              <div className="rounded-md border border-line bg-surface-muted/50 px-3 py-2 max-h-[50vh] overflow-auto">
                <Markdown components={defaultMarkdownComponents}>
                  {reasonRel?.association_reason?.trim() ? reasonRel.association_reason : "-"}
                </Markdown>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleteRelOpen} onOpenChange={(v) => setDeleteRelOpen(v)}>
        <AlertDialogContent className="w-[min(96vw,36rem)] max-w-xl">
          <AlertDialogHeader>
            <AlertDialogTitle>确认解除关联？</AlertDialogTitle>
            <AlertDialogDescription>
              将解除该语义组与 semantic domain <span className="font-mono text-content">{deletingRel?.sd_id || "-"}</span> 的关联。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeleteRelOpen(false)}>取消</AlertDialogCancel>
            <AlertDialogAction className="bg-red-600 hover:bg-red-700" onClick={confirmDeleteRel}>
              解除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={deleteGroupOpen} onOpenChange={setDeleteGroupOpen}>
        <AlertDialogContent className="w-[min(96vw,36rem)] max-w-xl">
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除语义组？</AlertDialogTitle>
            <AlertDialogDescription>
              将删除语义组 <span className="font-medium text-content">{group?.group_name || "-"}</span>。此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeletingGroup}>取消</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700"
              onClick={confirmDeleteGroup}
              disabled={isDeletingGroup}
            >
              {isDeletingGroup ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={showDependencyDialog} onOpenChange={setShowDependencyDialog}>
        <AlertDialogContent className="w-[min(96vw,56rem)] max-w-4xl">
          <AlertDialogHeader>
            <AlertDialogTitle>无法删除 - 存在关联的智能体</AlertDialogTitle>
            <AlertDialogDescription>
              语义组 <span className="font-medium text-content">{group?.group_name || "-"}</span> 正在被以下 {dependentAgents.length} 个智能体使用，无法删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="mt-4 space-y-3 px-6">
            <div className="max-h-[320px] w-full overflow-auto rounded-md border border-line">
              <table className="w-full table-fixed text-sm">
                <thead>
                  <tr className="bg-surface-muted text-left">
                    <th className="w-auto px-4 py-3 font-medium">智能体名称</th>
                    <th className="w-28 px-4 py-3 font-medium">命名空间</th>
                    <th className="w-28 px-4 py-3 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {dependentAgents.map((agent, idx) => (
                    <tr key={`${agent.namespace}/${agent.name}/${idx}`} className="border-t border-line">
                      <td className="px-4 py-3 font-medium whitespace-normal break-all">{agent.name}</td>
                      <td className="px-4 py-3 text-content-muted">{agent.namespace}</td>
                      <td className="px-4 py-3 text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setShowDependencyDialog(false)
                            router.push(`/agents/${encodeURIComponent(agent.namespace)}/${encodeURIComponent(agent.name)}`)
                          }}
                          className="text-cta hover:text-cta/90 whitespace-nowrap cursor-pointer"
                        >
                          查看详情 →
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="text-sm text-content">请先删除这些智能体或修改其关联的语义组，然后再删除。</div>
          </div>
          <AlertDialogFooter>
            <AlertDialogAction onClick={() => setShowDependencyDialog(false)}>知道了</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}


"use client"

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import { api } from "@/lib/api"
import { toast } from "sonner"
import { Markdown, defaultMarkdownComponents } from "@/components/markdown"

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
import { ArrowLeft, ChevronRight, Layers, Link2, RefreshCw, Trash2, X, FileText, Database, Maximize2, Scan } from "lucide-react"

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

type DDGroupRelation = {
  id: number
  sd_id: string
  group_id: string
  association_reason?: string
}

function shortID(id: string) {
  const s = String(id || "")
  if (s.length <= 18) return s
  return `${s.slice(0, 8)}…${s.slice(-6)}`
}

type SemanticDomainMeta = {
  dd_namespace: string
  dd_name: string
}

const REL_GRAPH = {
  width: 1080,
  minWidthClass: "min-w-[1080px]",
  // This is a cap; actual maxHeight is computed from viewport.
  maxHeight: 560,
  // layout
  groupX: 190,
  sdX: 560, // legacy (kept to avoid noisy refactors)
  ddX: 900,
  rowStartY: 92, // legacy
  rowGapY: 76, // legacy
  minHeight: 320,
  paddingY: 96,
  // node sizes
  nodeW: 280,
  nodeH: 96,
  // edge tuning
  edgeGap: 10,
  sgCurve: 120,
  sdCurve: 90,
  // background grid
  // Keep it subtle so the canvas feels clean.
  gridDotOpacity: 0.1,
  gridDotSize: 20,
  // colors
  // Keep all edges the same blue (project-consistent, not “fancy”).
  sgStart: "#2563eb", // blue-600
  sgEnd: "#2563eb",
  ddStart: "#2563eb",
  ddEnd: "#2563eb",
  sgArrow: "#2563eb",
  ddArrow: "#2563eb",
  // Keep main stroke slim and crisp.
  strokeWidth: 2.2,
} as const

function bezier(startX: number, startY: number, endX: number, endY: number, curve: number) {
  const c1 = startX + curve
  const c2 = endX - curve
  return `M ${startX} ${startY} C ${c1} ${startY}, ${c2} ${endY}, ${endX} ${endY}`
}

export default function SemanticGroupDetailPage() {
  const router = useRouter()
  const params = useParams<{ id: string }>()
  const groupId = String(params?.id ?? "")

  const [group, setGroup] = useState<SemanticGroup | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const [relations, setRelations] = useState<DDGroupRelation[]>([])
  const [isLoadingRelations, setIsLoadingRelations] = useState(false)

  const [deleteRelOpen, setDeleteRelOpen] = useState(false)
  const [deletingRel, setDeletingRel] = useState<DDGroupRelation | null>(null)
  const [reasonOpen, setReasonOpen] = useState(false)
  const [reasonRel, setReasonRel] = useState<DDGroupRelation | null>(null)
  const [sdMeta, setSdMeta] = useState<Record<string, SemanticDomainMeta>>({})
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
      items: DDGroupRelation[]
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
    // Slightly over-estimate to avoid visual overflow; body can still scroll.
    const headerH = 88
    const rowH = 76
    const heights = ddBuckets.map((b) => Math.max(REL_GRAPH.nodeH, headerH + b.items.length * rowH))
    const total = heights.reduce((a, x) => a + x, 0) + Math.max(0, heights.length - 1) * gapY
    return Math.max(REL_GRAPH.minHeight, topPad + total + bottomPad)
  }, [ddBuckets])

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

  const loadGroup = async () => {
    if (!groupId) return
    setIsLoading(true)
    try {
      const res = await api.get(`/semantic-groups/${encodeURIComponent(groupId)}`)
      const data = res.data as unknown
      const r = isRecord(data) ? data : {}
      setGroup({
        id: String(r.id ?? groupId),
        group_name: String(r.group_name ?? ""),
        description: typeof r.description === "string" ? r.description : "",
        agent_card: typeof r.agent_card === "string" ? r.agent_card : "",
        version: typeof r.version === "string" ? r.version : "",
        created_at: typeof r.created_at === "string" ? r.created_at : "",
      })
    } catch (e) {
      console.error("load semantic group failed", e)
      toast.error("加载语义组失败")
      setGroup(null)
    } finally {
      setIsLoading(false)
    }
  }

  const loadRelations = async () => {
    if (!groupId) return
    setIsLoadingRelations(true)
    try {
      const res = await api.get(`/dd-group-relations/group/${encodeURIComponent(groupId)}`)
      const data = res.data as unknown
      const r = isRecord(data) ? data : {}
      const list = Array.isArray(r.items) ? (r.items as unknown[]) : []
      const adapted: DDGroupRelation[] = list
        .map((x) => (isRecord(x) ? x : {}))
        .map((x) => ({
          id: Number(x.id ?? 0),
          sd_id: String(x.sd_id ?? ""),
          group_id: String(x.group_id ?? ""),
          association_reason: typeof x.association_reason === "string" ? x.association_reason : "",
        }))
        .filter((x) => x.id > 0)
      setRelations(adapted)
    } catch (e) {
      console.error("load relations failed", e)
      toast.error("加载关联关系失败")
      setRelations([])
    } finally {
      setIsLoadingRelations(false)
    }
  }

  useEffect(() => {
    void loadGroup()
    void loadRelations()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupId])

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      const missing = relations
        .map((r) => r.sd_id)
        .filter((id) => id && !sdMeta[id])
      if (missing.length === 0) return

      for (const id of missing) {
        try {
          const res = await api.get(`/semantic-domains/${encodeURIComponent(id)}`)
          const data = res.data as unknown
          const r = isRecord(data) ? data : {}
          const ns = typeof r.dd_namespace === "string" ? r.dd_namespace : ""
          const nm = typeof r.dd_name === "string" ? r.dd_name : ""
          if (!cancelled) {
            setSdMeta((prev) => ({ ...prev, [id]: { dd_namespace: ns, dd_name: nm } }))
          }
        } catch (e) {
          console.warn("load semantic domain failed", id, e)
          if (!cancelled) {
            setSdMeta((prev) => ({ ...prev, [id]: { dd_namespace: "", dd_name: "" } }))
          }
        }
      }
    }
    void run()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [relations])

  const openDeleteRel = (r: DDGroupRelation) => {
    setDeletingRel(r)
    setDeleteRelOpen(true)
  }

  const openReason = (r: DDGroupRelation) => {
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
      await loadRelations()
    } catch (e) {
      console.error("delete relation failed", e)
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "解除关联失败")
    }
  }

  return (
    <div className="p-8 space-y-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.back()}
              className="-ml-2 h-8 px-2 text-slate-500 hover:text-slate-900"
            >
              <ArrowLeft className="w-4 h-4 mr-1" />
              返回
            </Button>
            <nav className="flex items-center text-sm text-slate-500 min-w-0" aria-label="Breadcrumb">
              <Link href="/semantic-groups" className="hover:text-slate-900">
                语义组
              </Link>
              <ChevronRight className="w-4 h-4 mx-2 text-slate-400 shrink-0" />
              <span className="font-medium text-slate-900 truncate">{group?.group_name || groupId}</span>
            </nav>
          </div>

          <Button variant="outline" size="icon" onClick={() => { void loadGroup(); void loadRelations() }} title="刷新">
            <RefreshCw className={`w-4 h-4 ${(isLoading || isLoadingRelations) ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
          <Layers className="w-4 h-4 text-slate-500" />
          基本信息
        </div>
        <Card className="p-6 border-slate-200">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <div className="space-y-1 min-w-0">
              <div className="text-xs text-slate-500">名称</div>
              <div className="text-sm text-slate-900 truncate">{group?.group_name || "-"}</div>
            </div>
            <div className="space-y-1 min-w-0">
              <div className="text-xs text-slate-500">版本</div>
              <div className="text-sm text-slate-900 truncate">{group?.version || "-"}</div>
            </div>
            <div className="space-y-1 min-w-0">
              <div className="text-xs text-slate-500">创建时间</div>
              <div className="text-sm text-slate-900 truncate">
                {group?.created_at ? new Date(group.created_at).toLocaleString() : "-"}
              </div>
            </div>
          </div>
        </Card>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
          <FileText className="w-4 h-4 text-slate-500" />
          描述
        </div>
        <Card className="p-6 border-slate-200">
          {group?.description ? (
            <Markdown>{group.description}</Markdown>
          ) : (
            <div className="text-sm text-slate-500">-</div>
          )}
        </Card>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
            <Link2 className="w-4 h-4 text-slate-500" />
            组成员
          </div>
        </div>

        <Card className="border-slate-200">
          <div
            className={[
              "relative overflow-auto bg-slate-50/40",
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
                className="pointer-events-auto h-8 w-8 border border-slate-200 bg-white/90 backdrop-blur shadow-sm"
                title="Fullscreen"
                onClick={() => setGraphFullscreenOpen(true)}
                aria-label="Fullscreen"
              >
                <Maximize2 className="w-4 h-4" />
              </Button>
            </div>

            <div
              className={`relative ${REL_GRAPH.minWidthClass} mx-auto`}
              style={{ height: graphHeight, width: REL_GRAPH.width }}
            >
              {/* edges */}
              <svg
                className="absolute left-0 top-0"
                width={REL_GRAPH.width}
                height={graphHeight}
                viewBox={`0 0 ${REL_GRAPH.width} ${graphHeight}`}
                aria-hidden="true"
                shapeRendering="geometricPrecision"
              >
                <defs>
                  <style>{`
                    @keyframes flow {
                      from { stroke-dashoffset: 0; }
                      to { stroke-dashoffset: -48; }
                    }
                    .flow-line {
                      stroke-dasharray: 8 10;
                      animation: flow 1.4s linear infinite;
                    }
                    @media (prefers-reduced-motion: reduce) {
                      .flow-line { animation: none; }
                    }
                  `}</style>
                  <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                    <path d="M0,0 L8,4 L0,8 z" fill={REL_GRAPH.sgArrow} opacity="0.9" />
                  </marker>
                </defs>
                {(() => {
                  const topPad = 56
                  const gapY = 22
                  const headerH = 88
                  const rowH = 76
                  const ddCardW = 380
                  const ddCardX = REL_GRAPH.ddX

                  const groupCenterY = graphHeight / 2
                  const groupOutX = REL_GRAPH.groupX + REL_GRAPH.nodeW / 2 + REL_GRAPH.edgeGap
                  const ddInX = ddCardX - ddCardW / 2 - REL_GRAPH.edgeGap

                  let yCursor = topPad
                  return ddBuckets.map((b) => {
                    const h = Math.max(REL_GRAPH.nodeH, headerH + b.items.length * rowH)
                    const centerY = yCursor + h / 2
                    yCursor += h + gapY
                    const d = bezier(groupOutX, groupCenterY, ddInX, centerY, 180)
                    return (
                      <path
                        key={b.key}
                        d={d}
                        fill="none"
                        stroke={REL_GRAPH.sgStart}
                        strokeWidth={REL_GRAPH.strokeWidth}
                        opacity={1}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        markerEnd="url(#arrow)"
                        vectorEffect="non-scaling-stroke"
                        className="flow-line"
                      />
                    )
                  })
                })()}
              </svg>

              {/* group node */}
              <div
                className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
                style={{ left: REL_GRAPH.groupX, width: REL_GRAPH.nodeW, height: REL_GRAPH.nodeH, pointerEvents: "auto" }}
              >
                <div className="h-full rounded-xl border border-slate-200 bg-white shadow-sm px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 shrink-0">
                      <Layers className="w-4 h-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs text-slate-500">语义组</div>
                      <div className="mt-0.5 text-sm font-medium text-slate-900 truncate">{group?.group_name || groupId}</div>
                      <div className="text-[11px] text-slate-500 font-mono truncate">{groupId}</div>
                    </div>
                  </div>
                </div>
              </div>

              {/* DD buckets (result-focused): show each DD once, list SD mappings inside */}
              {isLoadingRelations && relations.length === 0 ? (
                <div className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-sm text-slate-500" style={{ left: REL_GRAPH.ddX }}>
                  加载中...
                </div>
              ) : ddBuckets.length === 0 ? (
                <div className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-sm text-slate-500" style={{ left: REL_GRAPH.ddX }}>
                  暂无关联
                </div>
              ) : (
                (() => {
                  const topPad = 56
                  const gapY = 22
                  const headerH = 88
                  const rowH = 76
                  const ddCardW = 380

                  let yCursor = topPad
                  return ddBuckets.map((b) => {
                    const h = Math.max(REL_GRAPH.nodeH, headerH + b.items.length * rowH)
                    const centerY = yCursor + h / 2
                    const topY = yCursor
                    yCursor += h + gapY

                    const ddFull = b.hasDD ? `${b.dd_namespace}/${b.dd_name}` : ""
                    return (
                      <div
                        key={b.key}
                        className={[
                          "absolute -translate-x-1/2 -translate-y-1/2 rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden flex flex-col",
                          b.hasDD ? "hover:border-indigo-200" : "opacity-80",
                        ].join(" ")}
                        style={{ top: centerY, left: REL_GRAPH.ddX, width: ddCardW, height: h }}
                      >
                        <div className="px-4 py-3 border-b border-slate-100">
                          <button
                            type="button"
                            disabled={!b.hasDD}
                            onClick={() => {
                              if (!b.hasDD) return
                              router.push(`/datasources/${encodeURIComponent(b.dd_namespace)}/${encodeURIComponent(b.dd_name)}`)
                            }}
                            onKeyDown={(e) => {
                              if (!b.hasDD) return
                              if (e.key !== "Enter" && e.key !== " ") return
                              e.preventDefault()
                              router.push(`/datasources/${encodeURIComponent(b.dd_namespace)}/${encodeURIComponent(b.dd_name)}`)
                            }}
                            className={[
                              "relative w-full flex items-center gap-2 text-left rounded-lg",
                              "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-200",
                              b.hasDD ? "cursor-pointer" : "cursor-default",
                            ].join(" ")}
                            title={b.hasDD ? ddFull : (b.isLoading ? "DD 信息加载中" : "未关联数据源")}
                          >
                            {b.dd_namespace ? (
                              <Badge
                                variant="secondary"
                                className="absolute right-0 top-0 translate-y-[-2px] translate-x-[2px] bg-white border border-slate-200 text-slate-600 font-mono text-[10px] h-5 px-2"
                              >
                                {b.dd_namespace}
                              </Badge>
                            ) : null}
                            <div className="w-8 h-8 rounded-full bg-indigo-50 flex items-center justify-center text-indigo-600 shrink-0">
                              <Database className="w-4 h-4" />
                            </div>
                            <div className="min-w-0">
                              <div className="text-xs text-slate-500">data descriptor</div>
                              <div className="mt-0.5 text-sm font-medium text-slate-900 truncate">
                                {!b.hasDD ? (b.isLoading ? "加载中..." : "未关联") : b.dd_name || "-"}
                              </div>
                              <div className="text-[11px] text-slate-500 truncate">
                                由 {b.items.length} 个 semantic domain 映射到此数据源
                              </div>
                            </div>
                          </button>
                        </div>

                        <div className="flex-1 min-h-0 overflow-auto divide-y divide-slate-100">
                          {b.items.map((r) => (
                            <div
                              key={r.id}
                              role="button"
                              tabIndex={0}
                              onClick={() => openReason(r)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault()
                                  openReason(r)
                                }
                              }}
                              className="group px-4 py-2.5 flex items-start justify-between gap-3 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
                              title="点击查看分组策略"
                            >
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  <div className="w-7 h-7 rounded-full bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
                                    <Link2 className="w-4 h-4" />
                                  </div>
                                  <div className="min-w-0">
                                    <div className="text-xs text-slate-500 whitespace-nowrap">semantic domain</div>
                                    <div className="mt-0.5 text-sm font-medium text-slate-900 truncate">{shortID(r.sd_id)}</div>
                                  </div>
                                </div>
                                <div className="mt-1.5 text-xs text-slate-500 line-clamp-1" title={r.association_reason || ""}>
                                  {r.association_reason ? `分组策略：${r.association_reason}` : <span className="text-slate-400 italic">暂无分组策略</span>}
                                </div>
                              </div>
                              <div className="shrink-0 flex items-center gap-1.5">
                                {b.hasDD ? (
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8 text-slate-600 hover:text-slate-900 opacity-0 group-hover:opacity-100 transition-opacity"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      router.push(`/datasources/${encodeURIComponent(b.dd_namespace)}/${encodeURIComponent(b.dd_name)}`)
                                    }}
                                    title={ddFull ? `查看数据源：${ddFull}` : "查看数据源"}
                                  >
                                    <ChevronRight className="w-4 h-4" />
                                  </Button>
                                ) : null}
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8 text-red-600 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    openDeleteRel(r)
                                  }}
                                  title="解除关联"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </Button>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )
                  })
                })()
              )}
            </div>
          </div>
        </Card>
      </div>

      {/* Fullscreen graph */}
      <Dialog
        open={graphFullscreenOpen}
        onOpenChange={(v) => {
          setGraphFullscreenOpen(v)
          if (v) {
            // Default to "fit" when opening fullscreen.
            setTimeout(() => fitFsAll(), 0)
          } else {
            setFullscreenScale(1)
          }
        }}
      >
        <DialogContent className="w-[min(98vw,1280px)] max-w-[98vw] h-[92vh] max-h-[92vh] flex flex-col p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
            <div className="flex items-center justify-between gap-3">
              <DialogTitle>组成员</DialogTitle>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-slate-500 hover:text-slate-900"
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
                "relative h-full overflow-auto bg-slate-50/40",
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
                <div className="pointer-events-auto flex items-center gap-1 rounded-lg border border-slate-200 bg-white/90 backdrop-blur px-1.5 py-1 shadow-sm">
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
                  <div className="text-[11px] tabular-nums text-slate-600 w-[52px] text-center select-none">
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
                  {/* edges */}
              <svg
                className="absolute left-0 top-0"
                width={REL_GRAPH.width}
                    height={graphHeight}
                    viewBox={`0 0 ${REL_GRAPH.width} ${graphHeight}`}
                    aria-hidden="true"
                    shapeRendering="geometricPrecision"
                  >
                    <defs>
                      <style>{`
                        @keyframes flow {
                          from { stroke-dashoffset: 0; }
                          to { stroke-dashoffset: -48; }
                        }
                        .flow-line {
                          stroke-dasharray: 8 10;
                          animation: flow 1.4s linear infinite;
                        }
                        @media (prefers-reduced-motion: reduce) {
                          .flow-line { animation: none; }
                        }
                      `}</style>
                      <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                        <path d="M0,0 L8,4 L0,8 z" fill={REL_GRAPH.sgArrow} opacity="0.9" />
                      </marker>
                    </defs>
                    {(() => {
                      const topPad = 56
                      const gapY = 22
                      const headerH = 88
                      const rowH = 76
                      const ddCardW = 380
                      const ddCardX = REL_GRAPH.ddX

                      const groupCenterY = graphHeight / 2
                      const groupOutX = REL_GRAPH.groupX + REL_GRAPH.nodeW / 2 + REL_GRAPH.edgeGap
                      const ddInX = ddCardX - ddCardW / 2 - REL_GRAPH.edgeGap

                      let yCursor = topPad
                      return ddBuckets.map((b) => {
                        const h = Math.max(REL_GRAPH.nodeH, headerH + b.items.length * rowH)
                        const centerY = yCursor + h / 2
                        yCursor += h + gapY
                        const d = bezier(groupOutX, groupCenterY, ddInX, centerY, 180)
                        return (
                          <path
                            key={b.key}
                            d={d}
                            fill="none"
                            stroke={REL_GRAPH.sgStart}
                            strokeWidth={REL_GRAPH.strokeWidth}
                            opacity={1}
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            markerEnd="url(#arrow)"
                            vectorEffect="non-scaling-stroke"
                            className="flow-line"
                          />
                        )
                      })
                    })()}
                  </svg>

                  {/* group node */}
                  <div
                    className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
                    style={{ left: REL_GRAPH.groupX, width: REL_GRAPH.nodeW, height: REL_GRAPH.nodeH, pointerEvents: "auto" }}
                  >
                    <div className="h-full rounded-xl border border-slate-200 bg-white shadow-sm px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 shrink-0">
                          <Layers className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <div className="text-xs text-slate-500">语义组</div>
                          <div className="mt-0.5 text-sm font-medium text-slate-900 truncate">{group?.group_name || groupId}</div>
                          <div className="text-[11px] text-slate-500 font-mono truncate">{groupId}</div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* DD buckets */}
                  {isLoadingRelations && relations.length === 0 ? (
                    <div className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-sm text-slate-500" style={{ left: REL_GRAPH.ddX }}>
                      加载中...
                    </div>
                  ) : ddBuckets.length === 0 ? (
                    <div className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-sm text-slate-500" style={{ left: REL_GRAPH.ddX }}>
                      暂无关联
                    </div>
                  ) : (
                    (() => {
                      const topPad = 56
                      const gapY = 22
                      const headerH = 88
                      const rowH = 76
                      const ddCardW = 380

                      let yCursor = topPad
                      return ddBuckets.map((b) => {
                        const h = Math.max(REL_GRAPH.nodeH, headerH + b.items.length * rowH)
                        const centerY = yCursor + h / 2
                        yCursor += h + gapY

                        const ddFull = b.hasDD ? `${b.dd_namespace}/${b.dd_name}` : ""
                        return (
                          <div
                            key={b.key}
                            className={[
                              "absolute -translate-x-1/2 -translate-y-1/2 rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden flex flex-col",
                              b.hasDD ? "hover:border-indigo-200" : "opacity-80",
                            ].join(" ")}
                            style={{ top: centerY, left: REL_GRAPH.ddX, width: ddCardW, height: h }}
                          >
                            <div className="px-4 py-3 border-b border-slate-100">
                              <button
                                type="button"
                                disabled={!b.hasDD}
                                onClick={() => {
                                  if (!b.hasDD) return
                                  router.push(`/datasources/${encodeURIComponent(b.dd_namespace)}/${encodeURIComponent(b.dd_name)}`)
                                }}
                                onKeyDown={(e) => {
                                  if (!b.hasDD) return
                                  if (e.key !== "Enter" && e.key !== " ") return
                                  e.preventDefault()
                                  router.push(`/datasources/${encodeURIComponent(b.dd_namespace)}/${encodeURIComponent(b.dd_name)}`)
                                }}
                                className={[
                                  "relative w-full flex items-center gap-2 text-left rounded-lg",
                                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-200",
                                  b.hasDD ? "cursor-pointer" : "cursor-default",
                                ].join(" ")}
                                title={b.hasDD ? ddFull : (b.isLoading ? "DD 信息加载中" : "未关联数据源")}
                              >
                                {b.dd_namespace ? (
                                  <Badge
                                    variant="secondary"
                                    className="absolute right-0 top-0 translate-y-[-2px] translate-x-[2px] bg-white border border-slate-200 text-slate-600 font-mono text-[10px] h-5 px-2"
                                  >
                                    {b.dd_namespace}
                                  </Badge>
                                ) : null}
                                <div className="w-8 h-8 rounded-full bg-indigo-50 flex items-center justify-center text-indigo-600 shrink-0">
                                  <Database className="w-4 h-4" />
                                </div>
                                <div className="min-w-0">
                                  <div className="text-xs text-slate-500">data descriptor</div>
                                  <div className="mt-0.5 text-sm font-medium text-slate-900 truncate">
                                    {!b.hasDD ? (b.isLoading ? "加载中..." : "未关联") : b.dd_name || "-"}
                                  </div>
                                  <div className="text-[11px] text-slate-500 truncate">
                                    由 {b.items.length} 个 semantic domain 映射到此数据源
                                  </div>
                                </div>
                              </button>
                            </div>

                            <div className="flex-1 min-h-0 overflow-auto divide-y divide-slate-100">
                              {b.items.map((r) => (
                                <div
                                  key={r.id}
                                  role="button"
                                  tabIndex={0}
                                  onClick={() => openReason(r)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter" || e.key === " ") {
                                      e.preventDefault()
                                      openReason(r)
                                    }
                                  }}
                                  className="group px-4 py-2.5 flex items-start justify-between gap-3 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
                                  title="点击查看分组策略"
                                >
                                  <div className="min-w-0">
                                    <div className="flex items-center gap-2">
                                      <div className="w-7 h-7 rounded-full bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
                                        <Link2 className="w-4 h-4" />
                                      </div>
                                      <div className="min-w-0">
                                        <div className="text-xs text-slate-500 whitespace-nowrap">semantic domain</div>
                                        <div className="mt-0.5 text-sm font-medium text-slate-900 truncate">{shortID(r.sd_id)}</div>
                                      </div>
                                    </div>
                                    <div className="mt-1.5 text-xs text-slate-500 line-clamp-1" title={r.association_reason || ""}>
                                      {r.association_reason ? `分组策略：${r.association_reason}` : <span className="text-slate-400 italic">暂无分组策略</span>}
                                    </div>
                                  </div>
                                  <div className="shrink-0 flex items-center gap-1.5">
                                    {b.hasDD ? (
                                      <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-8 w-8 text-slate-600 hover:text-slate-900 opacity-0 group-hover:opacity-100 transition-opacity"
                                        onClick={(e) => {
                                          e.stopPropagation()
                                          router.push(`/datasources/${encodeURIComponent(b.dd_namespace)}/${encodeURIComponent(b.dd_name)}`)
                                        }}
                                        title={ddFull ? `查看数据源：${ddFull}` : "查看数据源"}
                                      >
                                        <ChevronRight className="w-4 h-4" />
                                      </Button>
                                    ) : null}
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="h-8 w-8 text-red-600 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity"
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        openDeleteRel(r)
                                      }}
                                      title="解除关联"
                                    >
                                      <Trash2 className="w-4 h-4" />
                                    </Button>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )
                      })
                    })()
                  )}
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
          <DialogHeader className="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
            <div className="flex items-center justify-between gap-3">
              <DialogTitle>分组策略</DialogTitle>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-slate-500 hover:text-slate-900"
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
              <div className="text-xs text-slate-500">semantic domain id</div>
              {reasonRel?.sd_id ? (
                <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-mono text-slate-900 break-words">
                  {reasonRel.sd_id}
                </div>
              ) : (
                <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-mono text-slate-900 break-words">
                  -
                </div>
              )}
            </div>
            <div className="space-y-1.5">
              <div className="text-xs text-slate-500">data descriptor</div>
              <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-mono text-slate-900 break-words">
                {(() => {
                  const id = reasonRel?.sd_id || ""
                  const meta = id ? sdMeta[id] : undefined
                  if (!id) return "-"
                  if (!meta) return "加载中..."
                  if (!meta.dd_namespace && !meta.dd_name) return "-"
                  return `${meta.dd_namespace || "-"} / ${meta.dd_name || "-"}`
                })()}
              </div>
            </div>
            <div className="space-y-1.5">
              <div className="text-xs text-slate-500">分组策略</div>
              <div className="rounded-md border border-slate-200 bg-slate-50/50 px-3 py-2 max-h-[50vh] overflow-auto">
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
              将解除该语义组与 semantic domain <span className="font-mono text-slate-900">{deletingRel?.sd_id || "-"}</span> 的关联。
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
    </div>
  )
}


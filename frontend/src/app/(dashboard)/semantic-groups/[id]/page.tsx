"use client"

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"
import useSWR from "swr"
import { api } from "@/lib/api"
import { listAgentsAll } from "@/lib/agents-api"
import { listAllDescriptors } from "@/lib/descriptors-api"
import {
  getSemanticGroupWithMembers,
  removeSemanticGroupMember,
  submitAddSemanticGroupMember,
  submitRemoveSemanticGroupMember,
  updateSemanticGroup,
  waitForSemanticGroupMemberTask,
} from "@/lib/semantic-groups-api"
import { semanticGroupKey } from "@/lib/swr-keys"
import type {
  DDGroupRelationResponse,
  DataDescriptorResponse,
} from "@/lib/api-types"
import { toast } from "sonner"
import { Markdown, defaultMarkdownComponents } from "@/components/markdown"
import { RbacButton, RbacWrapper } from "@/components/rbac"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog,
  DialogContent,
  DialogFooter,
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
import { ArrowLeft, Check, ChevronRight, Database, Layers, Link2, RefreshCw, Trash2, X, FileText, Maximize2, Scan, Loader2, Pencil, Plus, Sparkles } from "lucide-react"
import { RelationGraph, REL_GRAPH } from "@/components/relation-graph"
import { cn } from "@/lib/utils"

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

type AgentCardSkillDraft = {
  id: string
  name: string
  description: string
  tags: string
  examples: string
}

type AgentCardObject = Record<string, unknown> & {
  name?: string
  description?: string
  skills?: unknown
}

function parseAgentCard(raw?: string): AgentCardObject | null {
  const s = String(raw ?? "").trim()
  if (!s) return {}
  try {
    const obj = JSON.parse(s) as unknown
    if (obj && typeof obj === "object" && !Array.isArray(obj)) {
      return obj as AgentCardObject
    }
    return null
  } catch {
    return null
  }
}

function stringifyAgentCard(card: AgentCardObject): string {
  return JSON.stringify(card)
}

function skillsFromCard(card: AgentCardObject | null): AgentCardSkillDraft[] {
  const raw = card?.skills
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((sk) => ({
      id: String(sk.id ?? ""),
      name: String(sk.name ?? ""),
      description: String(sk.description ?? ""),
      tags: Array.isArray(sk.tags) ? sk.tags.map((t) => String(t)).join(", ") : "",
      examples: Array.isArray(sk.examples) ? sk.examples.map((t) => String(t)).join("\n") : "",
    }))
}

function applySkills(card: AgentCardObject, drafts: AgentCardSkillDraft[]): AgentCardObject {
  const skills = drafts.map((d) => ({
    id: d.id.trim(),
    name: d.name.trim(),
    description: d.description.trim(),
    tags: d.tags.split(/[,，]/).map((t) => t.trim()).filter(Boolean),
    examples: d.examples.split("\n").map((t) => t.trim()).filter(Boolean),
  }))
  return { ...card, skills }
}

function emptySkillDraft(): AgentCardSkillDraft {
  return { id: "", name: "", description: "", tags: "", examples: "" }
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

  const [descOpen, setDescOpen] = useState(false)
  const [descDraft, setDescDraft] = useState("")
  const [savingDesc, setSavingDesc] = useState(false)

  const [cardOpen, setCardOpen] = useState(false)
  const [cardName, setCardName] = useState("")
  const [cardDesc, setCardDesc] = useState("")
  const [cardSkills, setCardSkills] = useState<AgentCardSkillDraft[]>([])
  const [cardRawFallback, setCardRawFallback] = useState("")
  const [cardUseRaw, setCardUseRaw] = useState(false)
  const [savingCard, setSavingCard] = useState(false)

  const [addMemberOpen, setAddMemberOpen] = useState(false)
  const [addMemberQuery, setAddMemberQuery] = useState("")
  const [addMemberReason, setAddMemberReason] = useState("手动添加")
  const [descriptorOptions, setDescriptorOptions] = useState<DataDescriptorResponse[]>([])
  const [loadingDescriptors, setLoadingDescriptors] = useState(false)
  const [selectedDescriptorKey, setSelectedDescriptorKey] = useState("")
  const [addingMember, setAddingMember] = useState(false)
  const [removeMemberOpen, setRemoveMemberOpen] = useState(false)
  const [removingMember, setRemovingMember] = useState(false)
  const [memberToRemove, setMemberToRemove] = useState<{
    label: string
    sdIds: string[]
  } | null>(null)

  const parsedAgentCard = useMemo(() => parseAgentCard(group?.agent_card), [group?.agent_card])
  const agentCardSkills = useMemo(() => skillsFromCard(parsedAgentCard), [parsedAgentCard])
  const canEditMembers = childGroups.length === 0
  const existingMemberKeys = useMemo(() => {
    const keys = new Set<string>()
    for (const r of relations) {
      const meta = sdMeta[r.sd_id]
      if (meta?.dd_namespace && meta?.dd_name) {
        keys.add(`${meta.dd_namespace}/${meta.dd_name}`)
      }
    }
    return keys
  }, [relations, sdMeta])

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
    if (!group?.id || !deletingRel?.sd_id) return
    const toastId = toast.loading("正在刷新组描述和 Agent Card…")
    try {
      await removeSemanticGroupMember(group.id, { sd_id: deletingRel.sd_id })
      toast.success("已解除关联，组描述和 Agent Card 已刷新", { id: toastId })
      setDeleteRelOpen(false)
      setDeletingRel(null)
      await mutate()
    } catch (e) {
      console.error("delete relation failed", e)
      const err = e as { message?: string; response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || err.message || "解除关联失败", { id: toastId })
    }
  }

  const openEditDescription = () => {
    setDescDraft(group?.description || "")
    setDescOpen(true)
  }

  const saveDescription = async () => {
    if (!group?.id || savingDesc) return
    setSavingDesc(true)
    try {
      // Keep table description and agent_card.description in sync so list/detail and agent creation agree.
      const card = parseAgentCard(group.agent_card) ?? {}
      card.description = descDraft
      await updateSemanticGroup(group.id, {
        description: descDraft,
        agent_card: stringifyAgentCard(card),
      })
      toast.success("描述已更新")
      setDescOpen(false)
      await mutate()
    } catch (e) {
      console.error("update semantic group description failed", e)
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "更新描述失败")
    } finally {
      setSavingDesc(false)
    }
  }

  const openEditAgentCard = () => {
    const parsed = parseAgentCard(group?.agent_card)
    if (!parsed) {
      setCardUseRaw(true)
      setCardRawFallback(group?.agent_card || "")
      setCardName("")
      setCardDesc("")
      setCardSkills([])
    } else {
      setCardUseRaw(false)
      setCardRawFallback("")
      setCardName(String(parsed.name ?? ""))
      setCardDesc(String(parsed.description ?? group?.description ?? ""))
      setCardSkills(skillsFromCard(parsed).length > 0 ? skillsFromCard(parsed) : [emptySkillDraft()])
    }
    setCardOpen(true)
  }

  const saveAgentCard = async () => {
    if (!group?.id || savingCard) return
    setSavingCard(true)
    try {
      let nextCard: AgentCardObject
      if (cardUseRaw) {
        const parsed = parseAgentCard(cardRawFallback)
        if (!parsed) {
          toast.error("agent_card 不是合法 JSON")
          return
        }
        nextCard = parsed
      } else {
        const base = parseAgentCard(group.agent_card) ?? {}
        nextCard = applySkills(
          { ...base, name: cardName.trim(), description: cardDesc },
          cardSkills.filter((s) => s.id.trim() || s.name.trim()),
        )
      }
      const description = String(nextCard.description ?? group.description ?? "")
      await updateSemanticGroup(group.id, {
        description,
        agent_card: stringifyAgentCard(nextCard),
      })
      toast.success("Agent Card 已更新")
      setCardOpen(false)
      await mutate()
    } catch (e) {
      console.error("update semantic group agent_card failed", e)
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "更新 Agent Card 失败")
    } finally {
      setSavingCard(false)
    }
  }

  const openAddMember = async () => {
    setAddMemberOpen(true)
    setAddMemberQuery("")
    setSelectedDescriptorKey("")
    setAddMemberReason("手动添加")
    setLoadingDescriptors(true)
    try {
      const items = await listAllDescriptors()
      setDescriptorOptions(items)
    } catch (e) {
      console.error("list descriptors for add member failed", e)
      toast.error("加载数据源列表失败")
    } finally {
      setLoadingDescriptors(false)
    }
  }

  const confirmAddMember = async () => {
    if (!group?.id || !selectedDescriptorKey || addingMember) return
    const [ns, ...rest] = selectedDescriptorKey.split("/")
    const name = rest.join("/")
    if (!ns || !name) return
    setAddingMember(true)
    const groupId = group.id
    try {
      const taskId = await submitAddSemanticGroupMember(groupId, {
        dd_namespace: ns,
        dd_name: name,
        association_reason: addMemberReason.trim() || "手动添加",
      })
      toast.success("成员已添加，组描述正在后台刷新…")
      setAddMemberOpen(false)
      await mutate()
      // Background poll — don't block the UI
      void (async () => {
        try {
          const status = await waitForSemanticGroupMemberTask(taskId)
          if (status.result?.action === "SKIPPED") return
          await mutate()
          toast.success("组描述和 Agent Card 已刷新")
        } catch (e) {
          console.warn("background refresh group after add member failed", e)
          toast.warning("组描述刷新未完成，请稍后手动刷新", { description: "可点击页面上的刷新按钮" })
        }
      })()
    } catch (e) {
      console.error("add semantic group member failed", e)
      const err = e as { message?: string; response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || err.message || "添加成员失败")
    } finally {
      setAddingMember(false)
    }
  }

  const openRemoveMember = (bucket: {
    hasDD: boolean
    dd_namespace: string
    dd_name: string
    items: DDGroupRelationResponse[]
  }) => {
    const sdIds = [...new Set(bucket.items.map((r) => r.sd_id).filter(Boolean))]
    if (sdIds.length === 0) return
    setMemberToRemove({
      label: bucket.hasDD ? `${bucket.dd_namespace} / ${bucket.dd_name}` : "该成员",
      sdIds,
    })
    setRemoveMemberOpen(true)
  }

  const confirmRemoveMember = async () => {
    if (!group?.id || !memberToRemove || removingMember) return
    setRemovingMember(true)
    const groupId = group.id
    try {
      // Submit all removals in parallel (fire-and-forget)
      const taskIds: string[] = []
      for (const sdId of memberToRemove.sdIds) {
        taskIds.push(await submitRemoveSemanticGroupMember(groupId, { sd_id: sdId }))
      }
      toast.success("成员已移除，组描述正在后台刷新…")
      setRemoveMemberOpen(false)
      setMemberToRemove(null)
      await mutate()
      // Background poll for all tasks
      void (async () => {
        try {
          await Promise.all(taskIds.map((tid) => waitForSemanticGroupMemberTask(tid)))
          await mutate()
          toast.success("组描述和 Agent Card 已刷新")
        } catch (e) {
          console.warn("background refresh group after remove member failed", e)
          toast.warning("组描述刷新未完成，请稍后手动刷新", { description: "可点击页面上的刷新按钮" })
        }
      })()
    } catch (e) {
      console.error("remove semantic group member failed", e)
      const err = e as { message?: string; response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || err.message || "移除成员失败")
    } finally {
      setRemovingMember(false)
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
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-medium text-content">
            <FileText className="w-4 h-4 text-content-muted" />
            描述
          </div>
          <RbacWrapper requiredPermission="semantic-group:manage">
            <Button variant="outline" size="sm" onClick={openEditDescription} disabled={!group?.id}>
              <Pencil className="w-3.5 h-3.5 mr-1.5" />
              编辑
            </Button>
          </RbacWrapper>
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
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-medium text-content">
            <Sparkles className="w-4 h-4 text-content-muted" />
            Agent Card
          </div>
          <RbacWrapper requiredPermission="semantic-group:manage">
            <Button variant="outline" size="sm" onClick={openEditAgentCard} disabled={!group?.id}>
              <Pencil className="w-3.5 h-3.5 mr-1.5" />
              编辑
            </Button>
          </RbacWrapper>
        </div>
        <Card className="p-6 border-line space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1 min-w-0">
              <div className="text-xs text-content-muted">名称</div>
              <div className="text-sm text-content truncate">{parsedAgentCard?.name || "-"}</div>
            </div>
            <div className="space-y-1 min-w-0">
              <div className="text-xs text-content-muted">Skills</div>
              <div className="text-sm text-content">{agentCardSkills.length} 个</div>
            </div>
          </div>
          {agentCardSkills.length > 0 ? (
            <ul className="space-y-2">
              {agentCardSkills.map((sk) => (
                <li key={`${sk.id}-${sk.name}`} className="rounded-md border border-line px-3 py-2">
                  <div className="text-sm font-medium text-content truncate">{sk.name || sk.id || "未命名 skill"}</div>
                  {sk.id ? <div className="text-xs font-mono text-content-muted">{sk.id}</div> : null}
                  {sk.description ? (
                    <div className="mt-1 text-xs text-content-muted whitespace-pre-wrap break-words line-clamp-3">{sk.description}</div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-sm text-content-muted">暂无 skill</div>
          )}
        </Card>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-medium text-content">
            <Layers className="w-4 h-4 text-content-muted" />
            层级成员列表
          </div>
          {canEditMembers ? (
            <RbacWrapper requiredPermission="semantic-group:manage">
              <Button variant="outline" size="sm" onClick={() => void openAddMember()} disabled={!group?.id}>
                <Plus className="w-3.5 h-3.5 mr-1.5" />
                添加成员
              </Button>
            </RbacWrapper>
          ) : null}
        </div>
        <Card className="border-line overflow-hidden">
          {isLoading && !group ? (
            <div className="px-4 py-6 text-sm text-content-muted">加载中…</div>
          ) : childGroups.length === 0 && ddBuckets.length === 0 ? (
            <div className="px-4 py-6 text-sm text-content-muted">暂无成员</div>
          ) : (
            <>
              {childGroups.length > 0 ? (
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
              ) : null}
              {ddBuckets.length > 0 ? (
                <ul
                  className={`list-none divide-y divide-[var(--color-line)] ${childGroups.length > 0 ? "border-t border-line" : ""}`}
                  role="list"
                >
                  {ddBuckets.map((b) => {
                    const href = b.hasDD
                      ? `/datasources/${encodeURIComponent(b.dd_namespace)}/${encodeURIComponent(b.dd_name)}`
                      : "#"
                    const isClickable = b.hasDD
                    return (
                      <li key={b.key} className="flex items-center gap-2 pr-3 min-w-0">
                        <Link
                          href={href}
                          className={`flex flex-1 items-center gap-3 px-4 py-3 min-w-0 ${
                            isClickable
                              ? "hover:bg-surface-muted/60 transition-colors"
                              : "bg-surface-muted/40 cursor-not-allowed opacity-70"
                          }`}
                          onClick={isClickable ? undefined : (e) => e.preventDefault()}
                          aria-disabled={!isClickable}
                        >
                          <span className="w-8 h-8 rounded-full bg-surface-muted flex items-center justify-center text-content-muted shrink-0">
                            <Database className="w-4 h-4" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block font-medium text-content truncate">
                              {b.hasDD ? `${b.dd_namespace} / ${b.dd_name}` : "加载中…"}
                            </span>
                            <span className="text-xs text-content-muted">{b.items.length} 个关联</span>
                          </span>
                        </Link>
                        <RbacButton
                          requiredPermission="semantic-group:manage"
                          variant="outline"
                          size="sm"
                          className="shrink-0 text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700"
                          onClick={() => openRemoveMember(b)}
                          disabled={removingMember}
                        >
                          <Trash2 className="w-3.5 h-3.5 mr-1.5" />
                          移除
                        </RbacButton>
                      </li>
                    )
                  })}
                </ul>
              ) : null}
            </>
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
              onRemoveDDFromGroup={openRemoveMember}
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
              onRemoveDDFromGroup={openRemoveMember}
                    onNavigateToGroup={(id) => router.push(hrefForChild(id))}
                    onNavigateToDataSource={(ns, name) => router.push(`/datasources/${encodeURIComponent(ns)}/${encodeURIComponent(name)}`)}
                  />
                </div>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={descOpen} onOpenChange={setDescOpen}>
        <DialogContent className="w-[min(96vw,42rem)] max-w-2xl max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50">
            <DialogTitle>编辑描述</DialogTitle>
          </DialogHeader>
          <div className="px-6 py-4 flex-1 min-h-0 overflow-y-auto">
            <Label htmlFor="sg-description">描述</Label>
            <Textarea
              id="sg-description"
              className="mt-2 min-h-[220px]"
              value={descDraft}
              onChange={(e) => setDescDraft(e.target.value)}
              placeholder="语义组描述"
            />
            <p className="mt-2 text-xs text-content-muted">保存时会同步写入 agent_card.description，避免管理页与创建智能体读到不同文案。</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDescOpen(false)} disabled={savingDesc}>取消</Button>
            <Button onClick={() => void saveDescription()} disabled={savingDesc}>
              {savingDesc ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={cardOpen} onOpenChange={setCardOpen}>
        <DialogContent className="w-[min(96vw,48rem)] max-w-3xl max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50">
            <DialogTitle>编辑 Agent Card</DialogTitle>
          </DialogHeader>
          <div className="px-6 py-4 flex-1 min-h-0 overflow-y-auto space-y-4">
            {cardUseRaw ? (
              <div className="space-y-2">
                <Label htmlFor="sg-agent-card-raw">agent_card JSON</Label>
                <Textarea
                  id="sg-agent-card-raw"
                  className="min-h-[280px] font-mono text-xs"
                  value={cardRawFallback}
                  onChange={(e) => setCardRawFallback(e.target.value)}
                />
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  <Label htmlFor="sg-agent-card-name">名称</Label>
                  <Input id="sg-agent-card-name" value={cardName} onChange={(e) => setCardName(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="sg-agent-card-desc">description</Label>
                  <Textarea
                    id="sg-agent-card-desc"
                    className="min-h-[120px]"
                    value={cardDesc}
                    onChange={(e) => setCardDesc(e.target.value)}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium text-content">Skills</div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCardSkills((prev) => [...prev, emptySkillDraft()])}
                  >
                    <Plus className="w-3.5 h-3.5 mr-1.5" />
                    添加 skill
                  </Button>
                </div>
                <div className="space-y-3">
                  {cardSkills.map((sk, idx) => (
                    <div key={`${idx}-${sk.id}`} className="rounded-md border border-line p-3 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-xs text-content-muted">Skill {idx + 1}</div>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-red-600 hover:text-red-700"
                          onClick={() => setCardSkills((prev) => prev.filter((_, i) => i !== idx))}
                        >
                          删除
                        </Button>
                      </div>
                      <Input
                        placeholder="id"
                        value={sk.id}
                        onChange={(e) => setCardSkills((prev) => prev.map((item, i) => i === idx ? { ...item, id: e.target.value } : item))}
                      />
                      <Input
                        placeholder="name"
                        value={sk.name}
                        onChange={(e) => setCardSkills((prev) => prev.map((item, i) => i === idx ? { ...item, name: e.target.value } : item))}
                      />
                      <Textarea
                        placeholder="description"
                        className="min-h-[72px]"
                        value={sk.description}
                        onChange={(e) => setCardSkills((prev) => prev.map((item, i) => i === idx ? { ...item, description: e.target.value } : item))}
                      />
                      <Input
                        placeholder="tags，逗号分隔"
                        value={sk.tags}
                        onChange={(e) => setCardSkills((prev) => prev.map((item, i) => i === idx ? { ...item, tags: e.target.value } : item))}
                      />
                      <Textarea
                        placeholder="examples，每行一条"
                        className="min-h-[64px]"
                        value={sk.examples}
                        onChange={(e) => setCardSkills((prev) => prev.map((item, i) => i === idx ? { ...item, examples: e.target.value } : item))}
                      />
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCardOpen(false)} disabled={savingCard}>取消</Button>
            <Button onClick={() => void saveAgentCard()} disabled={savingCard}>
              {savingCard ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={addMemberOpen} onOpenChange={setAddMemberOpen}>
        <DialogContent className="w-[min(96vw,42rem)] max-w-2xl max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50">
            <DialogTitle>添加成员</DialogTitle>
            <p className="text-sm text-content-muted font-normal pt-1">
              添加后将根据当前成员重新生成组的描述和 Agent Card。
            </p>
          </DialogHeader>
          <div className="px-6 py-4 flex-1 min-h-0 overflow-y-auto space-y-4">
            <div className="space-y-2">
              <Label htmlFor="add-member-search">选择数据源</Label>
              <Input
                id="add-member-search"
                placeholder="按命名空间或名称筛选"
                value={addMemberQuery}
                onChange={(e) => setAddMemberQuery(e.target.value)}
              />
            </div>
            <div className="max-h-[280px] overflow-auto rounded-md border border-line">
              {loadingDescriptors ? (
                <div className="px-3 py-6 text-sm text-content-muted">加载数据源…</div>
              ) : (
                (() => {
                  const q = addMemberQuery.trim().toLowerCase()
                  const available = descriptorOptions.filter((d) => {
                    const key = `${d.namespace}/${d.name}`
                    if (existingMemberKeys.has(key)) return false
                    if (!q) return true
                    return key.toLowerCase().includes(q)
                  })
                  if (available.length === 0) {
                    return (
                      <div className="px-3 py-6 text-sm text-content-muted">
                        {q ? "没有匹配的可添加数据源" : "暂无可添加的数据源（现有成员已从列表中排除）"}
                      </div>
                    )
                  }
                  return (
                    <ul className="divide-y divide-[var(--color-line)]">
                      {available.slice(0, 80).map((d) => {
                        const key = `${d.namespace}/${d.name}`
                        const selected = selectedDescriptorKey === key
                        return (
                          <li key={key}>
                            <button
                              type="button"
                              aria-pressed={selected}
                              className={cn(
                                "w-full text-left px-3 py-2.5 text-sm flex items-center gap-3 border-l-2 transition-colors",
                                selected
                                  ? "bg-cta/10 border-l-cta"
                                  : "border-l-transparent hover:bg-surface-muted/60",
                              )}
                              onClick={() => setSelectedDescriptorKey(key)}
                            >
                              <span className="min-w-0 flex-1">
                                <div className={cn("font-medium truncate", selected ? "text-cta" : "text-content")}>
                                  {d.name}
                                </div>
                                <div className="text-xs text-content-muted">{d.namespace}</div>
                              </span>
                              {selected ? (
                                <Check className="w-4 h-4 text-cta shrink-0" aria-hidden />
                              ) : null}
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  )
                })()
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="add-member-reason">关联原因（可选）</Label>
              <Input
                id="add-member-reason"
                value={addMemberReason}
                onChange={(e) => setAddMemberReason(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddMemberOpen(false)} disabled={addingMember}>取消</Button>
            <Button onClick={() => void confirmAddMember()} disabled={addingMember || !selectedDescriptorKey}>
              {addingMember ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              添加
            </Button>
          </DialogFooter>
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

      <AlertDialog open={removeMemberOpen} onOpenChange={setRemoveMemberOpen}>
        <AlertDialogContent className="w-[min(96vw,36rem)] max-w-xl">
          <AlertDialogHeader>
            <AlertDialogTitle>确认移除成员？</AlertDialogTitle>
            <AlertDialogDescription>
              将从该语义组移除数据源 <span className="font-medium text-content">{memberToRemove?.label || "-"}</span>。组的描述和 Agent Card 会根据剩余成员自动刷新。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={removingMember}>取消</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700"
              onClick={confirmRemoveMember}
              disabled={removingMember}
            >
              {removingMember ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              移除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={deleteRelOpen} onOpenChange={(v) => setDeleteRelOpen(v)}>
        <AlertDialogContent className="w-[min(96vw,36rem)] max-w-xl">
          <AlertDialogHeader>
            <AlertDialogTitle>确认解除关联？</AlertDialogTitle>
            <AlertDialogDescription>
              将解除该语义组与 semantic domain <span className="font-mono text-content">{deletingRel?.sd_id || "-"}</span> 的关联。组的描述和 Agent Card 会根据剩余成员自动刷新。
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


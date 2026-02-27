"use client"

import { useEffect, useMemo, useState, type ReactNode } from "react"
import { useParams, useRouter } from "next/navigation"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { RbacButton, RbacWrapper } from "@/components/rbac"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { HoverHint } from "@/components/hover-hint"
import { Markdown } from "@/components/markdown"
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
import { ArrowLeft, Loader2, Trash2, RefreshCw, Server, Database, Shield, Sparkles, ChevronRight, ChevronDown, Info, Wrench, Layers, Link2 } from "lucide-react"

type UnknownRecord = Record<string, unknown>

function isRecord(v: unknown): v is UnknownRecord {
  return typeof v === "object" && v !== null
}

function asString(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined
}

type SemanticGroup = {
  id: string
  group_name: string
  version?: string
  created_at?: string
}

type DDGroupRelation = {
  id: number
  sd_id: string
  group_id: string
  association_reason?: string
}

type SemanticDomainMeta = {
  dd_namespace: string
  dd_name: string
}

function InfoItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="flex items-center px-3 py-2 rounded-md border border-slate-200 bg-white text-sm text-slate-700 font-normal shadow-sm min-h-[38px]">
        <div className="min-w-0 w-full">{value}</div>
      </div>
    </div>
  )
}

export default function AgentDetailPage() {
  const router = useRouter()
  const params = useParams<{ namespace: string; name: string }>()
  const namespace = decodeURIComponent(params?.namespace || "default")
  const name = decodeURIComponent(params?.name || "")

  const [isLoading, setIsLoading] = useState(false)
  const [agent, setAgent] = useState<UnknownRecord | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isDeleteOpen, setIsDeleteOpen] = useState(false)
  const [skillQuery, setSkillQuery] = useState("")
  const [expandedSkillIds, setExpandedSkillIds] = useState<Record<string, boolean>>({})

  const displayName = useMemo(() => {
    const card = agent?.agentCard
    if (isRecord(card) && typeof card.name === "string" && card.name) return card.name
    return name
  }, [agent, name])

  const load = async () => {
    if (!name) return
    setIsLoading(true)
    try {
      const res = await api.get(`/namespaces/${encodeURIComponent(namespace)}/agents/${encodeURIComponent(name)}`)
      const data = res.data as unknown
      setAgent(isRecord(data) ? data : {})
    } catch (e) {
      console.error("load agent failed", e)
      toast.error("加载智能体详情失败")
      setAgent(null)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespace, name])

  const onDelete = async () => {
    if (!name || isDeleting) return
    setIsDeleting(true)
    try {
      await api.delete(`/namespaces/${encodeURIComponent(namespace)}/agents/${encodeURIComponent(name)}`)
      toast.success("已删除智能体")
      router.push("/agents")
    } catch (e) {
      console.error("delete agent failed", e)
      toast.error("删除失败")
    } finally {
      setIsDeleting(false)
      setIsDeleteOpen(false)
    }
  }

  const model = useMemo(() => {
    const m = agent?.model
    return isRecord(m) ? m : null
  }, [agent])

  const agentCard = useMemo(() => {
    const c = agent?.agentCard
    return isRecord(c) ? c : null
  }, [agent])

  const dataPolicy = useMemo(() => {
    const p = agent?.dataPolicy
    return isRecord(p) ? p : null
  }, [agent])

  const dataSourceType = useMemo(() => asString(dataPolicy?.dataSourceType) || "", [dataPolicy])
  const semanticGroupID = useMemo(() => asString(dataPolicy?.semanticGroupID) || "", [dataPolicy])
  const isSemanticGroupAgent = useMemo(
    () => dataSourceType === "SemanticGroup" || (Boolean(semanticGroupID) && dataSourceType !== "SemanticDomain"),
    [dataSourceType, semanticGroupID],
  )

  const [semanticGroup, setSemanticGroup] = useState<SemanticGroup | null>(null)
  const [relations, setRelations] = useState<DDGroupRelation[]>([])
  const [sdMeta, setSdMeta] = useState<Record<string, SemanticDomainMeta>>({})
  const [isLoadingSg, setIsLoadingSg] = useState(false)
  const [isLoadingRelations, setIsLoadingRelations] = useState(false)

  const sourceSelector = useMemo(() => {
    const raw = dataPolicy?.sourceNameSelector
    return Array.isArray(raw) ? raw.filter((s): s is string => typeof s === "string") : []
  }, [dataPolicy])

  const activeDescriptors = useMemo(() => {
    const raw = agent?.activeDataDescriptors
    if (!Array.isArray(raw)) return []
    return raw
      .map((x) => (isRecord(x) ? x : null))
      .filter((x): x is UnknownRecord => Boolean(x))
      .map((x) => ({
        name: asString(x.name) || "",
        namespace: asString(x.namespace) || "default",
        lastSynced: asString(x.lastSynced) || "",
      }))
      .filter((x) => x.name)
  }, [agent])

  const conditions = useMemo(() => {
    const raw = agent?.conditions
    if (!Array.isArray(raw)) return []
    return raw
      .map((x) => (isRecord(x) ? x : null))
      .filter((x): x is UnknownRecord => Boolean(x))
      .map((x) => ({
        type: asString(x.type) || "",
        status: asString(x.status) || "",
        reason: asString(x.reason) || "",
        message: asString(x.message) || "",
        lastTransitionTime: asString(x.lastTransitionTime) || "",
      }))
      .filter((x) => x.type)
  }, [agent])

  const overallStatus = useMemo(() => {
    const avail = conditions.find((c) => c.type.toLowerCase() === "available")
    if (avail?.status === "True") return "AVAILABLE"
    const creating = conditions.find((c) => c.type.toLowerCase() === "creating")
    if (creating) return "CREATING"
    return "UNKNOWN"
  }, [conditions])

  // Keep raw status text (AVAILABLE/CREATING/UNKNOWN) as-is for UI consistency.

  const endpoint = useMemo(() => {
    const raw = agent?.endpoint
    if (!isRecord(raw)) return null
    return {
      address: asString(raw.address) || "",
      port: typeof raw.port === "number" ? raw.port : Number(raw.port),
      protocol: asString(raw.protocol) || "",
    }
  }, [agent])

  const skills = useMemo(() => {
    const raw = agentCard?.skills
    if (!Array.isArray(raw)) return []
    return raw
      .map((x) => (isRecord(x) ? x : null))
      .filter((x): x is UnknownRecord => Boolean(x))
      .map((x) => ({
        id: asString(x.id) || "",
        name: asString(x.name) || "",
        description: asString(x.description) || "",
        tags: Array.isArray(x.tags) ? x.tags.filter((t): t is string => typeof t === "string") : [],
        examples: Array.isArray(x.examples) ? x.examples.filter((t): t is string => typeof t === "string") : [],
      }))
      .filter((x) => x.id || x.name)
  }, [agentCard])

  const filteredSkills = useMemo(() => {
    const q = skillQuery.trim().toLowerCase()
    if (!q) return skills
    return skills.filter((s) => {
      const hay = `${s.id} ${s.name} ${s.description} ${(s.tags || []).join(" ")}`
      return hay.toLowerCase().includes(q)
    })
  }, [skills, skillQuery])

  const memberDescriptors = useMemo(() => {
    type Bucket = {
      key: string
      dd_namespace: string
      dd_name: string
      sdCount: number
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
      const b = map.get(key) || {
        key,
        dd_namespace,
        dd_name,
        sdCount: 0,
        hasDD,
        isLoading: false,
      }
      b.sdCount += 1
      if (isLoading) b.isLoading = true
      if (hasDD) {
        b.dd_namespace = dd_namespace
        b.dd_name = dd_name
        b.hasDD = true
      }
      map.set(key, b)
    }
    const arr = Array.from(map.values())
    arr.sort((a, b) => {
      if (a.key === "__unknown__" && b.key !== "__unknown__") return 1
      if (b.key === "__unknown__" && a.key !== "__unknown__") return -1
      return a.key.localeCompare(b.key)
    })
    return arr
  }, [relations, sdMeta])

  useEffect(() => {
    if (!isSemanticGroupAgent || !semanticGroupID) {
      setSemanticGroup(null)
      setRelations([])
      setSdMeta({})
      return
    }

    let cancelled = false
    const loadSg = async () => {
      setIsLoadingSg(true)
      try {
        const res = await api.get(`/semantic-groups/${encodeURIComponent(semanticGroupID)}`)
        const data = (res.data?.data ?? res.data) as unknown
        const r = isRecord(data) ? data : {}
        if (cancelled) return
        setSemanticGroup({
          id: String(r.id ?? semanticGroupID),
          group_name: String(r.group_name ?? ""),
          version: typeof r.version === "string" ? r.version : "",
          created_at: typeof r.created_at === "string" ? r.created_at : "",
        })
      } catch (e) {
        if (!cancelled) setSemanticGroup(null)
      } finally {
        if (!cancelled) setIsLoadingSg(false)
      }
    }

    const loadRel = async () => {
      setIsLoadingRelations(true)
      try {
        const res = await api.get(`/dd-group-relations/group/${encodeURIComponent(semanticGroupID)}`)
        const data = (res.data?.data ?? res.data) as unknown
        const r = isRecord(data) ? data : {}
        const list = Array.isArray((r as UnknownRecord).items) ? ((r as UnknownRecord).items as unknown[]) : []
        const adapted: DDGroupRelation[] = list
          .map((x) => (isRecord(x) ? x : {}))
          .map((x) => ({
            id: Number(x.id ?? 0),
            sd_id: String(x.sd_id ?? ""),
            group_id: String(x.group_id ?? ""),
            association_reason: typeof x.association_reason === "string" ? x.association_reason : "",
          }))
          .filter((x) => x.id > 0 && x.sd_id)
        if (!cancelled) setRelations(adapted)
      } catch (e) {
        if (!cancelled) setRelations([])
      } finally {
        if (!cancelled) setIsLoadingRelations(false)
      }
    }

    void loadSg()
    void loadRel()
    return () => {
      cancelled = true
    }
  }, [isSemanticGroupAgent, semanticGroupID])

  useEffect(() => {
    if (!isSemanticGroupAgent) return
    let cancelled = false
    const run = async () => {
      const missing = relations
        .map((r) => r.sd_id)
        .filter((id) => id && !sdMeta[id])
      if (missing.length === 0) return

      for (const id of missing) {
        try {
          const res = await api.get(`/semantic-domains/${encodeURIComponent(id)}`)
          const data = (res.data?.data ?? res.data) as unknown
          const r = isRecord(data) ? data : {}
          const ns = typeof (r as UnknownRecord).dd_namespace === "string" ? ((r as UnknownRecord).dd_namespace as string) : ""
          const nm = typeof (r as UnknownRecord).dd_name === "string" ? ((r as UnknownRecord).dd_name as string) : ""
          if (!cancelled) {
            setSdMeta((prev) => ({ ...prev, [id]: { dd_namespace: ns, dd_name: nm } }))
          }
        } catch {
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
  }, [relations, isSemanticGroupAgent])

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <Button variant="ghost" size="sm" onClick={() => router.back()} className="-ml-2 h-8 px-2 text-slate-500 hover:text-slate-900">
            <ArrowLeft className="w-4 h-4 mr-1" />
            返回
          </Button>
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-600 min-w-0">
              <span className="text-slate-700 shrink-0">智能体</span>
              <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />
              <span className="font-mono text-slate-700 shrink-0">{namespace}</span>
              <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />
              <span className="text-slate-700 truncate" title={displayName}>
                {displayName}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" onClick={() => void load()} disabled={isLoading}>
            <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
          </Button>
          <RbacWrapper requiredRole="admin">
            <Button
              variant="outline"
              onClick={() => setIsDeleteOpen(true)}
              disabled={isLoading}
              className="bg-white hover:bg-red-50 hover:text-red-600 hover:border-red-200"
            >
              <Trash2 className="w-4 h-4 mr-2" />
              删除
            </Button>
          </RbacWrapper>
        </div>
      </div>

      {isLoading && !agent ? (
        <div className="rounded-lg border border-slate-200 bg-white p-6">
          <div className="text-sm text-slate-500 inline-flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> 加载中...
          </div>
        </div>
      ) : !agent ? (
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">未找到该智能体。</div>
      ) : (
        <>
        <div className="space-y-3">
          <div className="text-sm font-medium text-slate-900 flex items-center gap-2">
            <Info className="w-4 h-4 text-slate-500" />
            基础信息
          </div>
          <Card className="rounded-lg border border-slate-200">
            <CardContent className="pt-6">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                <InfoItem
                  label="名称"
                  value={
                    <HoverHint text={displayName} copyText={displayName} enableCopy>
                      <span className="truncate block w-full">{displayName || "-"}</span>
                    </HoverHint>
                  }
                />
                <InfoItem label="命名空间" value={<span className="font-mono">{namespace}</span>} />
                <InfoItem
                  label="资源标识"
                  value={
                    <HoverHint text={name || "-"} copyText={name || "-"} enableCopy>
                      <span className="font-mono truncate block w-full">{name || "-"}</span>
                    </HoverHint>
                  }
                />
                <InfoItem
                  label="状态"
                  value={
                    <Badge
                      variant="outline"
                      className={
                        overallStatus === "AVAILABLE"
                          ? "bg-green-50 text-green-700 border-green-200"
                          : overallStatus === "CREATING"
                            ? "bg-blue-50 text-blue-700 border-blue-200"
                            : "bg-slate-50 text-slate-600 border-slate-200"
                      }
                    >
                      {overallStatus}
                    </Badge>
                  }
                />
                <InfoItem label="规划模型" value={<span className="font-mono text-xs">{asString(model?.plannerLLM) || "-"}</span>} />
                <InfoItem label="专家模型" value={<span className="font-mono text-xs">{asString(model?.expertLLM) || "-"}</span>} />
                <InfoItem
                  label="服务地址"
                  value={
                    <HoverHint
                      text={endpoint?.address ? `${endpoint.address}:${Number.isFinite(endpoint.port) ? endpoint.port : "-"} (${endpoint.protocol || "-"})` : "-"}
                      copyText={endpoint?.address ? `${endpoint.address}:${Number.isFinite(endpoint.port) ? endpoint.port : "-"} (${endpoint.protocol || "-"})` : "-"}
                      enableCopy
                    >
                      <span className="font-mono text-xs truncate block w-full">
                        {endpoint?.address ? `${endpoint.address}:${Number.isFinite(endpoint.port) ? endpoint.port : "-"} (${endpoint.protocol || "-"})` : "-"}
                      </span>
                    </HoverHint>
                  }
                />
                <InfoItem
                  label="最大步数"
                  value={<span>{typeof agent?.expertAgentMaxSteps === "string" && agent.expertAgentMaxSteps ? agent.expertAgentMaxSteps : "-"}</span>}
                />
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <div className="space-y-3">
            <div className="text-sm font-medium text-slate-900 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-slate-500" />
              概览
            </div>
            <Card className="rounded-lg border border-slate-200">
              <CardContent className="pt-6 text-sm text-slate-700 leading-7">
              <Markdown>{asString(agentCard?.description) || "暂无描述"}</Markdown>
              </CardContent>
            </Card>
          </div>

          <div className="space-y-3">
            <div className="text-sm font-medium text-slate-900 flex items-center gap-2">
              {isSemanticGroupAgent ? (
                <Layers className="w-4 h-4 text-slate-500" />
              ) : (
                <Database className="w-4 h-4 text-slate-500" />
              )}
              数据源
            </div>
            <Card className="rounded-lg border border-slate-200">
              <CardContent className="pt-6 space-y-4">
              {isSemanticGroupAgent ? (
                <>
                  <div>
                    <div className="text-xs font-medium text-slate-500 mb-2">语义组</div>
                    <div className="rounded-md border border-slate-200 bg-white px-4 py-3 flex items-center justify-between gap-3">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 shrink-0">
                          <Layers className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-slate-900 truncate">
                            {semanticGroup?.group_name || (isLoadingSg ? "加载中..." : (semanticGroupID || "-"))}
                          </div>
                          <div className="text-[11px] font-mono text-slate-500 truncate">
                            {semanticGroupID || "-"}
                            {semanticGroup?.version ? ` · v${semanticGroup.version}` : ""}
                          </div>
                        </div>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          if (!semanticGroupID) return
                          router.push(`/semantic-groups/${encodeURIComponent(semanticGroupID)}`)
                        }}
                        disabled={!semanticGroupID}
                      >
                        查看语义组
                      </Button>
                    </div>
                  </div>

                  <div>
                    <div className="text-xs font-medium text-slate-500 mb-2 flex items-center gap-2">
                      <Link2 className="w-3.5 h-3.5 text-slate-400" />
                      语义组成员
                    </div>
                    {isLoadingRelations && memberDescriptors.length === 0 ? (
                      <div className="text-sm text-slate-500">加载中...</div>
                    ) : memberDescriptors.length === 0 ? (
                      <div className="text-sm text-slate-500">-</div>
                    ) : (
                      <div className="rounded-md border border-slate-200 overflow-hidden">
                        <Table>
                          <TableHeader>
                            <TableRow className="bg-slate-50">
                              <TableHead>数据源</TableHead>
                              <TableHead className="w-[1%] whitespace-nowrap">命名空间</TableHead>
                              <TableHead className="w-[1%] whitespace-nowrap" title="Semantic Domain 的数量">
                                Semantic Domain 数
                              </TableHead>
                              <TableHead className="w-[96px] text-right">操作</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {memberDescriptors.map((b) => {
                              const ddFull = b.hasDD ? `${b.dd_namespace}/${b.dd_name}` : ""
                              return (
                                <TableRow key={b.key} className={b.hasDD ? "cursor-pointer hover:bg-slate-50" : ""}>
                                  <TableCell
                                    className="min-w-0"
                                    onClick={() => {
                                      if (!b.hasDD) return
                                      router.push(`/datasources/${encodeURIComponent(b.dd_namespace)}/${encodeURIComponent(b.dd_name)}`)
                                    }}
                                  >
                                    <div className="flex items-center gap-2 min-w-0">
                                      <div className="w-7 h-7 rounded-full bg-indigo-50 flex items-center justify-center text-indigo-600 shrink-0">
                                        <Database className="w-4 h-4" />
                                      </div>
                                      <div className="min-w-0">
                                        <div className="text-xs text-slate-500">data descriptor</div>
                                        <div className="text-sm font-medium text-slate-900 truncate" title={ddFull || ""}>
                                          {b.hasDD ? (b.dd_name || "-") : (b.isLoading ? "加载中..." : "-")}
                                        </div>
                                      </div>
                                    </div>
                                  </TableCell>
                                  <TableCell className="font-mono text-xs text-slate-600 whitespace-nowrap w-[1%]">
                                    {b.hasDD ? (b.dd_namespace || "-") : "-"}
                                  </TableCell>
                                  <TableCell className="text-xs text-slate-700 tabular-nums whitespace-nowrap w-[1%]">
                                    {b.sdCount}
                                  </TableCell>
                                  <TableCell className="text-right">
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="text-blue-600 hover:text-blue-800"
                                      disabled={!b.hasDD}
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        if (!b.hasDD) return
                                        router.push(`/datasources/${encodeURIComponent(b.dd_namespace)}/${encodeURIComponent(b.dd_name)}`)
                                      }}
                                    >
                                      查看
                                    </Button>
                                  </TableCell>
                                </TableRow>
                              )
                            })}
                          </TableBody>
                        </Table>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <div className="text-xs font-medium text-slate-500 mb-2">数据源选择器</div>
                    {sourceSelector.length === 0 ? (
                      <div className="text-sm text-slate-500">-</div>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {sourceSelector.map((s) => (
                          <Badge key={s} variant="secondary" className="text-[11px] h-5 px-2 font-mono" title={s}>
                            {s}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>

                  <div>
                    <div className="text-xs font-medium text-slate-500 mb-2">已激活数据描述符</div>
                    {activeDescriptors.length === 0 ? (
                      <div className="text-sm text-slate-500">-</div>
                    ) : (
                      <div className="rounded-md border border-slate-200 overflow-hidden">
                        <Table>
                          <TableHeader>
                            <TableRow className="bg-slate-50">
                              <TableHead>名称</TableHead>
                              <TableHead className="w-[120px]">命名空间</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {activeDescriptors.map((d) => (
                              <TableRow key={`${d.namespace}/${d.name}`}>
                                <TableCell className="font-mono text-xs">{d.name}</TableCell>
                                <TableCell className="font-mono text-xs text-slate-600">{d.namespace}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}
                  </div>
                </>
              )}
              </CardContent>
            </Card>
          </div>

          <div className="space-y-3">
            <div className="text-sm font-medium text-slate-900 flex items-center gap-2">
              <Shield className="w-4 h-4 text-slate-500" />
              状态与条件
            </div>
            <Card className="rounded-lg border border-slate-200">
              <CardContent className="pt-6 max-h-[520px] overflow-auto pr-2">
              {conditions.length === 0 ? (
                <div className="text-sm text-slate-500">暂无条件信息。</div>
              ) : (
                <div className="rounded-md border border-slate-200 overflow-hidden">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-slate-50">
                        <TableHead className="w-[140px]">类型</TableHead>
                        <TableHead className="w-[120px]">状态</TableHead>
                        <TableHead className="w-[160px]">原因</TableHead>
                        <TableHead>信息</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {conditions.map((c) => (
                        <TableRow key={`${c.type}:${c.reason}:${c.status}`}>
                          <TableCell className="font-mono text-xs">{c.type}</TableCell>
                          <TableCell className="text-xs">
                            <Badge
                              variant="outline"
                              className={
                                c.status === "True"
                                  ? "bg-green-50 text-green-700 border-green-200"
                                  : c.status === "False"
                                    ? "bg-red-50 text-red-700 border-red-200"
                                    : "bg-slate-50 text-slate-600 border-slate-200"
                              }
                            >
                              {c.status || "-"}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-xs text-slate-700">{c.reason || "-"}</TableCell>
                          <TableCell className="text-xs text-slate-600">{c.message || "-"}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
              </CardContent>
            </Card>
          </div>
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between gap-4">
            <div className="text-sm font-medium text-slate-900 flex items-center gap-2">
              <Wrench className="w-4 h-4 text-slate-500" />
              技能
            </div>
            <div className="w-full max-w-sm">
              <Input
                value={skillQuery}
                onChange={(e) => setSkillQuery(e.target.value)}
                placeholder="搜索技能（名称 / id / tag / 描述）"
              />
            </div>
          </div>
          <Card className="rounded-lg border border-slate-200">
            <CardContent className="pt-6">
            {skills.length === 0 ? (
              <div className="text-sm text-slate-500">暂无技能信息。</div>
            ) : filteredSkills.length === 0 ? (
              <div className="text-sm text-slate-500">未找到匹配的技能。</div>
            ) : (
              <div className="space-y-3">
                {filteredSkills.map((s) => {
                  const key = s.id || s.name
                  const expanded = Boolean(expandedSkillIds[key])
                  return (
                    <div key={`${s.id}:${s.name}`} className="rounded-md border border-slate-200 bg-white">
                      <button
                        type="button"
                        className="w-full px-4 py-3 flex items-start justify-between gap-3 text-left hover:bg-slate-50/60 transition-colors"
                        onClick={() => setExpandedSkillIds((m) => ({ ...m, [key]: !expanded }))}
                        aria-expanded={expanded}
                      >
                        <div className="min-w-0">
                          <div className="font-medium text-sm text-slate-900 truncate">
                            {s.name || s.id}
                          </div>
                          <div className="mt-0.5 font-mono text-[11px] text-slate-500 truncate">
                            {s.id}
                          </div>
                        </div>
                        <div className="shrink-0 flex items-center gap-2">
                          <Badge variant="outline" className="text-xs">{s.tags.length} 标签</Badge>
                          <span className="text-slate-400">
                            <ChevronDown className={`w-4 h-4 transition-transform ${expanded ? "rotate-180" : ""}`} />
                          </span>
                        </div>
                      </button>
                      {expanded ? (
                        <div className="px-4 pb-4">
                          {s.description ? (
                            <div className="mt-2 text-xs text-slate-600 whitespace-pre-wrap leading-6">
                              {s.description}
                            </div>
                          ) : null}
                          {s.tags.length > 0 ? (
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {s.tags.map((t) => (
                                <Badge key={t} variant="secondary" className="text-[11px] h-5 px-2">
                                  {t}
                                </Badge>
                              ))}
                            </div>
                          ) : null}
                          {s.examples.length > 0 ? (
                            <div className="mt-2 text-[11px] text-slate-500">
                              示例：{s.examples.length}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            )}
            </CardContent>
          </Card>
        </div>
        </>
      )}

      <AlertDialog open={isDeleteOpen} onOpenChange={setIsDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除？</AlertDialogTitle>
            <AlertDialogDescription>
              删除后将无法恢复。该操作只删除智能体，不影响底层数据源与配置。
              <span className="block mt-2 font-mono text-xs text-slate-600">{namespace}/{name}</span>
            </AlertDialogDescription>
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


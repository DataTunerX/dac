"use client"

import { useEffect, useMemo, useState, type ReactNode } from "react"
import Link from "next/link"
import { useParams, useRouter } from "next/navigation"
import useSWR from "swr"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { getAgent } from "@/lib/agents-api"
import { BizAgentCompositionGraph } from "@/components/agents/biz-agent-composition-graph"
import { useAgentComposition } from "@/hooks/use-agent-composition"
import { agentKey } from "@/lib/swr-keys"
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
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ArrowLeft, Loader2, Trash2, RefreshCw, Server, Database, Shield, Sparkles, ChevronRight, ChevronDown, Info, Wrench, Briefcase, Maximize2, X } from "lucide-react"


function InfoItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-content-muted">{label}</div>
      <div className="flex items-center px-3 py-2 rounded-md border border-line bg-surface text-sm text-content font-normal shadow-sm min-h-[38px]">
        <div className="min-w-0 w-full">{value}</div>
      </div>
    </div>
  )
}

function displayLimitValue(value?: string) {
  return value?.trim() ? value : "-"
}

async function fetcherAgent(_key: readonly [string, string, string]) {
  const [, ns, nm] = _key
  return getAgent(ns, nm)
}

export default function AgentDetailPage() {
  const router = useRouter()
  const params = useParams<{ namespace: string; name: string }>()
  const namespace = decodeURIComponent(params?.namespace || "default")
  const name = decodeURIComponent(params?.name || "")

  const swrKey = namespace && name ? agentKey(namespace, name) : null
  const { data: agent, error: swrError, isLoading, mutate } = useSWR(swrKey, fetcherAgent)

  const [isDeleting, setIsDeleting] = useState(false)
  const [isDeleteOpen, setIsDeleteOpen] = useState(false)
  const [skillQuery, setSkillQuery] = useState("")
  const [expandedSkillIds, setExpandedSkillIds] = useState<Record<string, boolean>>({})
  const [isLineageZoomOpen, setIsLineageZoomOpen] = useState(false)

  useEffect(() => {
    if (swrError) toast.error("加载智能体详情失败")
  }, [swrError])

  const displayName = useMemo(() => {
    const cardName = agent?.agentCard?.name
    return (typeof cardName === "string" && cardName) ? cardName : name
  }, [agent, name])

  const refreshData = () => mutate()

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

  const model = agent?.model ?? null
  const agentCard = agent?.agentCard ?? null
  const dataPolicy = agent?.dataPolicy ?? null
  const dataSourceType = dataPolicy?.dataSourceType ?? ""
  const semanticGroupID = dataPolicy?.semanticGroupID ?? ""
  // skill DAC：无数据源 / 无编排循环，详情不展示这些字段
  const isSkillAgent = (agent?.dacType || "").toLowerCase() === "skill"
  const isSemanticGroupAgent =
    !isSkillAgent &&
    (dataSourceType === "SemanticGroup" || (Boolean(semanticGroupID) && dataSourceType !== "SemanticDomain"))

  const {
    semanticGroup,
    compositionDataAgents,
    isLoadingRelations,
    isLoadingCompositionAgents,
  } = useAgentComposition({
    isSemanticGroupAgent,
    semanticGroupID,
    namespace,
    name,
  })

  const sourceSelector = useMemo(() => {
    const raw = dataPolicy?.sourceNameSelector
    return Array.isArray(raw) ? raw.filter((s): s is string => typeof s === "string") : []
  }, [dataPolicy])

  const activeDescriptors = useMemo(() => {
    const raw = agent?.activeDataDescriptors ?? []
    return raw
      .map((x) => ({
        name: x.name ?? "",
        namespace: x.namespace ?? "default",
        lastSynced: x.lastSynced ?? "",
      }))
      .filter((x) => x.name)
  }, [agent])

  const conditions = useMemo(() => {
    const raw = agent?.conditions ?? []
    return raw
      .map((x) => ({
        type: x.type ?? "",
        status: x.status ?? "",
        reason: x.reason ?? "",
        message: x.message ?? "",
        lastTransitionTime: x.lastTransitionTime ?? "",
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
    if (!raw) return null
    return {
      address: raw.address ?? "",
      port: raw.port ?? 0,
      protocol: raw.protocol ?? "",
    }
  }, [agent])

  const skills = useMemo(() => {
    const raw = agentCard?.skills ?? []
    return raw
      .map((x) => ({
        id: x.id ?? "",
        name: x.name ?? "",
        description: x.description ?? "",
        tags: Array.isArray(x.tags) ? x.tags.filter((t): t is string => typeof t === "string") : [],
        examples: Array.isArray(x.examples) ? x.examples.filter((t): t is string => typeof t === "string") : [],
      }))
      .filter((x) => x.id || x.name)
  }, [agentCard])

  const attachedSkillRefs = useMemo(() => {
    const raw = agent?.skillPolicy?.skills ?? []
    return raw.filter((ref) => ref.namespace && ref.name)
  }, [agent])

  const filteredSkills = useMemo(() => {
    const q = skillQuery.trim().toLowerCase()
    if (!q) return skills
    return skills.filter((s) => {
      const hay = `${s.id} ${s.name} ${s.description} ${(s.tags || []).join(" ")}`
      return hay.toLowerCase().includes(q)
    })
  }, [skills, skillQuery])

  const showCompositionGraph =
    isSemanticGroupAgent && (semanticGroup || isLoadingRelations || isLoadingCompositionAgents)

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <Button variant="ghost" size="sm" onClick={() => router.back()} className="-ml-2 h-8 px-2 text-content-muted hover:text-content">
            <ArrowLeft className="w-4 h-4 mr-1" />
            返回
          </Button>
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-medium text-content min-w-0">
              <span className="text-content shrink-0">智能体</span>
              <ChevronRight className="w-4 h-4 text-content-muted shrink-0" />
              <span className="font-mono text-content shrink-0">{namespace}</span>
              <ChevronRight className="w-4 h-4 text-content-muted shrink-0" />
              <span className="text-content truncate" title={displayName}>
                {displayName}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" onClick={() => void refreshData()} disabled={isLoading} aria-label="刷新">
            <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
          </Button>
          <RbacWrapper requiredRole="admin">
            <Button
              variant="outline"
              onClick={() => setIsDeleteOpen(true)}
              disabled={isLoading}
              className="bg-surface hover:bg-red-50 hover:text-red-600 hover:border-red-200"
            >
              <Trash2 className="w-4 h-4 mr-2" />
              删除
            </Button>
          </RbacWrapper>
        </div>
      </div>

      {isLoading && !agent ? (
        <div className="rounded-lg border border-line bg-surface p-6">
          <div className="text-sm text-content-muted inline-flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> 加载中…
          </div>
        </div>
      ) : !agent ? (
        <div className="rounded-lg border border-line bg-surface p-6 text-sm text-content-muted">未找到该智能体。</div>
      ) : (
        <>
        <div className="space-y-3">
          <div className="text-sm font-medium text-content flex items-center gap-2">
            <Info className="w-4 h-4 text-content-muted" />
            基础信息
          </div>
          {attachedSkillRefs.length > 0 ? (
            <div className="rounded-lg border border-line bg-surface px-4 py-3">
              <div className="mb-2 text-xs font-medium text-content-muted">
                {isSkillAgent ? "Skill Hub 绑定" : "本地执行附件"}
              </div>
              <div className="flex flex-wrap gap-2">
                {attachedSkillRefs.map((ref) => (
                  <Badge
                    key={`${ref.namespace}/${ref.name}@${ref.version || "latest"}`}
                    variant="outline"
                    className="font-mono text-xs"
                  >
                    {ref.namespace}/{ref.name}@{ref.version || "latest"}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}
          <Card className="rounded-lg border border-line">
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
                            ? "bg-cta/10 text-cta border-cta/20"
                            : "bg-surface-muted text-content border-line"
                      }
                    >
                      {overallStatus}
                    </Badge>
                  }
                />
                {isSkillAgent ? (
                  <InfoItem
                    label="模型"
                    value={<span className="font-mono text-xs">{model?.expertLLM ?? model?.plannerLLM ?? "-"}</span>}
                  />
                ) : (
                  <>
                    <InfoItem label="规划模型" value={<span className="font-mono text-xs">{model?.plannerLLM ?? "-"}</span>} />
                    <InfoItem label="专家模型" value={<span className="font-mono text-xs">{model?.expertLLM ?? "-"}</span>} />
                  </>
                )}
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
                {!isSkillAgent && (
                  <InfoItem
                    label="编排最大循环数"
                    value={<span>{displayLimitValue(agent?.orchestratorAgentMaxLoops)}</span>}
                  />
                )}
                <InfoItem
                  label={isSkillAgent ? "最大步数" : "专家最大步数"}
                  value={<span>{displayLimitValue(agent?.expertAgentMaxSteps)}</span>}
                />
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <div className="space-y-3">
            <div className="text-sm font-medium text-content flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-content-muted" />
              概览
            </div>
            <Card className="rounded-lg border border-line">
              <CardContent className="pt-6 text-sm text-content leading-7">
              <Markdown>{agentCard?.description ?? "暂无描述"}</Markdown>
              </CardContent>
            </Card>
          </div>

          {!isSkillAgent && (
          <div className="space-y-3">
            <div className="text-sm font-medium text-content flex items-center gap-2">
              {isSemanticGroupAgent ? (
                <Briefcase className="w-4 h-4 text-content-muted" />
              ) : (
                <Database className="w-4 h-4 text-content-muted" />
              )}
              {isSemanticGroupAgent ? "语义关系" : "数据源"}
            </div>
            <Card className="rounded-lg border border-line relative overflow-visible">
              <CardContent className="overflow-visible pt-6 space-y-4">
              {isSemanticGroupAgent ? (
                <>
                  {!showCompositionGraph ? (
                    <div className="text-sm text-content-muted">暂无语义关系数据</div>
                  ) : (
                    <>
                      <div className="absolute right-3 top-3 z-10">
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          className="h-7 w-7 bg-surface/90 backdrop-blur"
                          onClick={() => setIsLineageZoomOpen(true)}
                          aria-label="放大"
                          title="放大"
                        >
                          <Maximize2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                      <div className="min-h-[280px] w-full overflow-x-auto overflow-y-visible">
                        <BizAgentCompositionGraph
                          bizDisplayName={displayName}
                          bizNamespace={namespace}
                          bizName={name}
                          semanticGroup={semanticGroup}
                          dataAgents={compositionDataAgents}
                          isLoading={isLoadingRelations || isLoadingCompositionAgents}
                        />
                      </div>
                    </>
                  )}
                </>
              ) : (
                <>
                  <div>
                    <div className="text-xs font-medium text-content-muted mb-2">数据源选择器</div>
                    {sourceSelector.length === 0 ? (
                      <div className="text-sm text-content-muted">-</div>
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
                    <div className="text-xs font-medium text-content-muted mb-2">已激活数据描述符</div>
                    {activeDescriptors.length === 0 ? (
                      <div className="text-sm text-content-muted">-</div>
                    ) : (
                      <div className="rounded-md border border-line overflow-hidden">
                        <Table>
                          <TableHeader>
                            <TableRow className="bg-surface-muted">
                              <TableHead>名称</TableHead>
                              <TableHead className="w-[120px]">命名空间</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {activeDescriptors.map((d) => (
                              <TableRow key={`${d.namespace}/${d.name}`}>
                                <TableCell className="font-mono text-xs">{d.name}</TableCell>
                                <TableCell className="font-mono text-xs text-content">{d.namespace}</TableCell>
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
          )}

          <div className="space-y-3">
            <div className="text-sm font-medium text-content flex items-center gap-2">
              <Shield className="w-4 h-4 text-content-muted" />
              状态与条件
            </div>
            <Card className="rounded-lg border border-line">
              <CardContent className="pt-6 max-h-[520px] overflow-auto pr-2">
              {conditions.length === 0 ? (
                <div className="text-sm text-content-muted">暂无条件信息。</div>
              ) : (
                <div className="rounded-md border border-line overflow-hidden">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-surface-muted">
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
                                    : "bg-surface-muted text-content border-line"
                              }
                            >
                              {c.status || "-"}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-xs text-content">{c.reason || "-"}</TableCell>
                          <TableCell className="text-xs text-content">{c.message || "-"}</TableCell>
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
            <div className="text-sm font-medium text-content flex items-center gap-2">
              <Wrench className="w-4 h-4 text-content-muted" />
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
          <Card className="rounded-lg border border-line">
            <CardContent className="pt-6">
            {skills.length === 0 ? (
              <div className="text-sm text-content-muted">暂无技能信息。</div>
            ) : filteredSkills.length === 0 ? (
              <div className="text-sm text-content-muted">未找到匹配的技能。</div>
            ) : (
              <div className="space-y-3">
                {filteredSkills.map((s) => {
                  const key = s.id || s.name
                  const expanded = Boolean(expandedSkillIds[key])
                  return (
                    <div key={`${s.id}:${s.name}`} className="rounded-md border border-line bg-surface">
                      <button
                        type="button"
                        className="w-full px-4 py-3 flex items-start justify-between gap-3 text-left hover:bg-surface-muted/60 transition-colors cursor-pointer"
                        onClick={() => setExpandedSkillIds((m) => ({ ...m, [key]: !expanded }))}
                        aria-expanded={expanded}
                        aria-label={expanded ? "收起技能" : "展开技能"}
                      >
                        <div className="min-w-0">
                          <div className="font-medium text-sm text-content truncate">
                            {s.name || s.id}
                          </div>
                          <div className="mt-0.5 font-mono text-[11px] text-content-muted truncate">
                            {s.id}
                          </div>
                        </div>
                        <div className="shrink-0 flex items-center gap-2">
                          <Badge variant="outline" className="text-xs">{s.tags.length} 标签</Badge>
                          <span className="text-content-muted">
                            <ChevronDown className={`w-4 h-4 transition-transform ${expanded ? "rotate-180" : ""}`} />
                          </span>
                        </div>
                      </button>
                      {expanded ? (
                        <div className="px-4 pb-4">
                          {s.description ? (
                            <div className="mt-2 text-xs text-content whitespace-pre-wrap leading-6">
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
                            <div className="mt-2 text-[11px] text-content-muted">
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

      <Dialog open={isLineageZoomOpen} onOpenChange={setIsLineageZoomOpen}>
        <DialogContent className="w-[min(96vw,72rem)] max-w-none max-h-[90vh] flex flex-col p-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50 flex-shrink-0 flex flex-row items-center justify-between gap-3">
            <DialogTitle>语义关系</DialogTitle>
            <Button variant="ghost" size="icon" onClick={() => setIsLineageZoomOpen(false)} aria-label="关闭" title="关闭">
              <X className="w-4 h-4" />
            </Button>
          </DialogHeader>
          <div className="p-6 overflow-auto flex-1 min-h-0">
            <div className="min-h-[400px] w-full">
              <BizAgentCompositionGraph
                bizDisplayName={displayName}
                bizNamespace={namespace}
                bizName={name}
                semanticGroup={semanticGroup}
                dataAgents={compositionDataAgents}
                isLoading={isLoadingRelations || isLoadingCompositionAgents}
                onLinkClick={() => setIsLineageZoomOpen(false)}
              />
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog open={isDeleteOpen} onOpenChange={setIsDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除？</AlertDialogTitle>
            <AlertDialogDescription>
              删除后将无法恢复。该操作只删除智能体，不影响底层数据源与配置。
              <span className="block mt-2 font-mono text-xs text-content">{namespace}/{name}</span>
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

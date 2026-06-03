"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import axios from "axios"
import { toast } from "sonner"
import {
  AGENT_REGISTRY_NAMES,
  listAgentRegistries,
  listRegisteredAgents,
  type AgentRegistryName,
} from "@/lib/agent-registry-api"
import type {
  AgentRegistrySummaryResponse,
  RegisteredAgentCardResponse,
} from "@/lib/api-types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { PaginationBar } from "@/components/pagination-bar"
import { cn } from "@/lib/utils"
import { Loader2, RefreshCw, Search, X } from "lucide-react"

function apiErrorMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const body = err.response?.data as { message?: string } | undefined
    if (body?.message) return body.message
  }
  return fallback
}

function cardString(card: Record<string, unknown>, key: string): string {
  const value = card[key]
  if (typeof value === "string") return value
  if (value == null) return ""
  return String(value)
}

function skillsCount(card: Record<string, unknown>): number {
  const skills = card.skills
  return Array.isArray(skills) ? skills.length : 0
}

function formatCardFieldValue(value: unknown): string {
  if (value == null) return ""
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  return JSON.stringify(value, null, 2)
}

function CardFieldsReadonly({ card }: { card: Record<string, unknown> }) {
  const entries = useMemo(
    () => Object.entries(card).sort(([a], [b]) => a.localeCompare(b)),
    [card]
  )

  return (
    <div className="rounded-lg border border-line bg-surface p-4 space-y-3">
      {entries.map(([key, value]) => {
        const text = formatCardFieldValue(value)
        return (
          <div key={key} className="space-y-1">
            <Label className="font-mono text-xs text-content-muted">{key}</Label>
            <div className="text-sm font-mono text-content break-all rounded-md bg-surface-muted px-3 py-2 border border-line whitespace-pre-wrap">
              {text.trim() ? text : <span className="text-content-muted">（空）</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function PageSpinner() {
  return (
    <div className="flex items-center justify-center py-12">
      <Loader2 className="h-6 w-6 animate-spin text-content-muted" />
    </div>
  )
}

export function AgentRegistryPanel() {
  const [mounted, setMounted] = useState(false)
  const [activeRegistry, setActiveRegistry] = useState<AgentRegistryName>("orchestrator-registry")
  const [summaries, setSummaries] = useState<AgentRegistrySummaryResponse[]>([])
  const [agents, setAgents] = useState<RegisteredAgentCardResponse[]>([])
  const [isLoadingSummaries, setIsLoadingSummaries] = useState(false)
  const [isLoadingAgents, setIsLoadingAgents] = useState(false)

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [searchQuery, setSearchQuery] = useState("")

  const [detailOpen, setDetailOpen] = useState(false)
  const [selectedAgent, setSelectedAgent] = useState<RegisteredAgentCardResponse | null>(null)

  const summaryByName = useMemo(() => {
    const map = new Map<string, AgentRegistrySummaryResponse>()
    for (const item of summaries) map.set(item.name, item)
    return map
  }, [summaries])

  const activeSummary = summaryByName.get(activeRegistry)
  const isLoading = isLoadingSummaries || isLoadingAgents

  const loadSummaries = useCallback(async () => {
    setIsLoadingSummaries(true)
    try {
      const data = await listAgentRegistries()
      setSummaries(data.items ?? [])
    } catch (e) {
      console.error("list agent registries failed", e)
      toast.error(apiErrorMessage(e, "加载注册中心状态失败"))
      setSummaries([])
    } finally {
      setIsLoadingSummaries(false)
    }
  }, [])

  const loadAgents = useCallback(async (registry: AgentRegistryName) => {
    setIsLoadingAgents(true)
    try {
      const data = await listRegisteredAgents(registry)
      setAgents(data.items ?? [])
    } catch (e) {
      console.error("list registered agents failed", e)
      toast.error(apiErrorMessage(e, "加载 agent 列表失败"))
      setAgents([])
    } finally {
      setIsLoadingAgents(false)
    }
  }, [])

  const refreshAll = useCallback(async () => {
    await Promise.all([loadSummaries(), loadAgents(activeRegistry)])
  }, [activeRegistry, loadAgents, loadSummaries])

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    void loadSummaries()
  }, [loadSummaries])

  useEffect(() => {
    setPage(1)
    void loadAgents(activeRegistry)
  }, [activeRegistry, loadAgents])

  useEffect(() => {
    setPage(1)
  }, [searchQuery])

  const filteredAgents = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return agents
    return agents.filter((item) => {
      const card = item.card ?? {}
      const name = cardString(card, "name").toLowerCase()
      const url = cardString(card, "url").toLowerCase()
      const version = cardString(card, "version").toLowerCase()
      return name.includes(q) || url.includes(q) || version.includes(q)
    })
  }, [agents, searchQuery])

  const pagedAgents = useMemo(() => {
    const start = (page - 1) * pageSize
    return filteredAgents.slice(start, start + pageSize)
  }, [filteredAgents, page, pageSize])

  const openDetail = (item: RegisteredAgentCardResponse) => {
    setSelectedAgent(item)
    setDetailOpen(true)
  }

  const closeDetail = () => {
    setDetailOpen(false)
    setSelectedAgent(null)
  }

  const dialogTitle =
    cardString(selectedAgent?.card ?? {}, "name") || selectedAgent?.registry || "agent"

  if (!mounted) {
    return <PageSpinner />
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="text-sm font-medium text-content">
          <span className="text-content font-semibold">注册中心</span>
        </div>

        <div className="flex items-center gap-2 flex-wrap justify-end">
          <div className="relative mr-2">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-content-muted" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索名称或地址"
              className="h-9 w-[min(16rem,70vw)] pl-8"
            />
          </div>

          <div className="flex items-center gap-2 mr-2">
            <span className="text-xs font-medium text-content-muted">注册中心</span>
            <Select
              value={activeRegistry}
              onValueChange={(v) => setActiveRegistry(v as AgentRegistryName)}
            >
              <SelectTrigger className="h-9 w-[min(16rem,70vw)] font-mono text-sm">
                <SelectValue placeholder="选择注册中心" />
              </SelectTrigger>
              <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                {AGENT_REGISTRY_NAMES.map((name) => {
                  const summary = summaryByName.get(name)
                  const suffix =
                    summary && summary.reachable
                      ? ` (${summary.agent_count})`
                      : summary && !summary.reachable
                        ? " (不可达)"
                        : ""
                  return (
                    <SelectItem key={name} value={name} className="font-mono">
                      {name}
                      {suffix}
                    </SelectItem>
                  )
                })}
              </SelectContent>
            </Select>
          </div>

          <Button
            variant="outline"
            size="icon"
            onClick={() => void refreshAll()}
            disabled={isLoading}
            title="刷新"
            aria-label="刷新"
          >
            <RefreshCw className={cn("w-4 h-4", isLoading && "animate-spin")} />
          </Button>
        </div>
      </div>

      {activeSummary && !activeSummary.reachable ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 break-all">
          {activeSummary.error || "注册中心不可达"}
        </div>
      ) : null}

      <div className="rounded-lg border border-line bg-surface overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-surface-muted">
              <TableHead>名称</TableHead>
              <TableHead>地址</TableHead>
              <TableHead>版本</TableHead>
              <TableHead>技能数</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pagedAgents.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-content-muted py-10">
                  {isLoadingAgents
                    ? "加载中…"
                    : searchQuery.trim()
                      ? "未找到匹配的 Agent"
                      : "暂无已注册 Agent"}
                </TableCell>
              </TableRow>
            ) : (
              pagedAgents.map((item, index) => {
                const card = item.card ?? {}
                const name = cardString(card, "name") || "-"
                const url = cardString(card, "url") || "-"
                const rowKey = `${item.registry}-${url || name}-${index}`
                return (
                  <TableRow key={rowKey} className="hover:bg-surface-muted">
                    <TableCell className="font-medium font-mono text-content">{name}</TableCell>
                    <TableCell className="font-mono text-sm text-content-muted max-w-[360px] truncate" title={url}>
                      {url}
                    </TableCell>
                    <TableCell className="font-mono text-sm text-content-muted">
                      {cardString(card, "version") || "—"}
                    </TableCell>
                    <TableCell className="font-mono text-sm text-content-muted">{skillsCount(card)}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => openDetail(item)}>
                        查看
                      </Button>
                    </TableCell>
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </div>

      <PaginationBar
        total={filteredAgents.length}
        page={page}
        pageSize={pageSize}
        pageSizeOptions={[10, 20, 50, 100]}
        isLoading={isLoadingAgents}
        onPageChange={setPage}
        onPageSizeChange={(n) => {
          setPageSize(n)
          setPage(1)
        }}
      />

      <Dialog
        open={detailOpen}
        onOpenChange={(v) => {
          if (!v) closeDetail()
          else setDetailOpen(true)
        }}
      >
        <DialogContent className="sm:max-w-[760px] max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50 shrink-0">
            <div className="flex items-center justify-between gap-3">
              <div>
                <DialogTitle className="font-mono text-sm">{dialogTitle}</DialogTitle>
                {selectedAgent?.registry ? (
                  <p className="text-xs text-content-muted mt-1 font-mono">{selectedAgent.registry}</p>
                ) : null}
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={closeDetail}
                aria-label="关闭"
                title="关闭"
              >
                <X className="w-4 h-4" />
              </Button>
            </div>
          </DialogHeader>

          <div className="flex-1 min-h-0 overflow-y-auto px-6 py-6">
            {selectedAgent ? <CardFieldsReadonly card={selectedAgent.card ?? {}} /> : null}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

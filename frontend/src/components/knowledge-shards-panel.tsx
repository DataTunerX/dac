"use client"

import * as React from "react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import {
  groupKnowledgeShards,
  getSummaryPreview,
  type KnowledgeShard,
  type KnowledgeShardWithIndex,
} from "@/lib/knowledge-shards"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { EmptyState } from "@/components/ui/empty-state"
import { Markdown, defaultMarkdownComponents } from "@/components/markdown"
import {
  BookOpen,
  FileText,
  Info,
  Layers,
  Loader2,
  Maximize2,
  RefreshCw,
  Search,
  X,
} from "lucide-react"

type UnknownRecord = Record<string, unknown>

function isRecord(v: unknown): v is UnknownRecord {
  return typeof v === "object" && v !== null
}

function sourceBadgeClass(sourceType: string) {
  const t = (sourceType || "").toLowerCase()
  if (t.includes("gitee")) return "bg-red-50 text-red-700 border-red-100"
  if (t.includes("github")) return "bg-surface-muted text-content border-line"
  if (t.includes("gitlab")) return "bg-orange-50 text-orange-700 border-orange-100"
  if (t.includes("mysql")) return "bg-sky-50 text-sky-700 border-sky-100"
  if (t.includes("postgres")) return "bg-indigo-50 text-indigo-700 border-indigo-100"
  if (t.includes("clickhouse")) return "bg-amber-50 text-amber-700 border-amber-100"
  return "bg-cta/10 text-cta border-cta/20"
}

function getShardTitle(shard: KnowledgeShard, fallbackIndex: number): string {
  const moduleName =
    typeof shard.metadata?.module_name === "string"
      ? shard.metadata.module_name.trim()
      : ""
  if (moduleName) return moduleName
  return `分片 #${fallbackIndex + 1}`
}

function getShardSummary(shard: KnowledgeShard): string {
  const summary =
    typeof shard.metadata?.summary === "string" ? shard.metadata.summary : ""
  if (summary.trim()) return summary
  if (shard.content) {
    return shard.content.length > 150
      ? `${shard.content.slice(0, 150)}...`
      : shard.content
  }
  return "暂无摘要"
}

type KnowledgeShardsPanelProps = {
  namespace: string
  name: string
}

export function KnowledgeShardsPanel({ namespace, name }: KnowledgeShardsPanelProps) {
  const [isLoading, setIsLoading] = useState(false)
  const [results, setResults] = useState<KnowledgeShard[]>([])
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
  const [selectedShard, setSelectedShard] = useState<KnowledgeShardWithIndex | null>(null)
  const [fileSearch, setFileSearch] = useState("")
  const [debouncedFileSearch, setDebouncedFileSearch] = useState("")
  const [shardSearch, setShardSearch] = useState("")
  const [debouncedShardSearch, setDebouncedShardSearch] = useState("")
  const [visibleCount, setVisibleCount] = useState(50)
  const fileSearchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const shardSearchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const knowledgeDetailMarkdownComponents = useMemo(
    () => ({
      ...defaultMarkdownComponents,
      a: (props: React.ComponentProps<"a">) => (
        <a
          {...props}
          target="_blank"
          rel="noopener noreferrer"
          className="text-cta hover:underline break-all"
        />
      ),
    }),
    [],
  )

  const loadKnowledge = useCallback(async () => {
    setIsLoading(true)
    try {
      const res = await api.get(
        `/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}/knowledge`,
      )
      const data = res.data as unknown
      const r = isRecord(data) ? data : {}
      const list = Array.isArray(r.results) ? r.results : []
      const adapted: KnowledgeShard[] = list.map((it) => {
        const x = isRecord(it) ? it : {}
        return {
          content: typeof x.page_content === "string" ? x.page_content : undefined,
          metadata: isRecord(x.metadata) ? (x.metadata as UnknownRecord) : undefined,
          score: typeof x.score === "number" ? x.score : undefined,
        }
      })
      setResults(adapted)
    } catch (e) {
      console.error("load knowledge failed", e)
      toast.error("加载知识分片失败")
    } finally {
      setIsLoading(false)
    }
  }, [namespace, name])

  useEffect(() => {
    void loadKnowledge()
  }, [loadKnowledge])

  const fileGroups = useMemo(() => groupKnowledgeShards(results), [results])

  const handleFileSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    setFileSearch(value)
    if (fileSearchTimerRef.current) clearTimeout(fileSearchTimerRef.current)
    fileSearchTimerRef.current = setTimeout(() => setDebouncedFileSearch(value), 200)
  }, [])

  const handleShardSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    setShardSearch(value)
    if (shardSearchTimerRef.current) clearTimeout(shardSearchTimerRef.current)
    shardSearchTimerRef.current = setTimeout(() => setDebouncedShardSearch(value), 200)
  }, [])

  const filteredFileGroups = useMemo(() => {
    const q = debouncedFileSearch.trim().toLowerCase()
    if (!q) return fileGroups
    return fileGroups.filter((group) => {
      const haystack = [group.label, group.detail, group.id]
        .filter((value): value is string => typeof value === "string" && value.length > 0)
        .join(" ")
        .toLowerCase()
      return haystack.includes(q)
    })
  }, [fileGroups, debouncedFileSearch])

  useEffect(() => {
    if (filteredFileGroups.length === 0) {
      setSelectedFileId(null)
      return
    }
    if (!selectedFileId || !filteredFileGroups.some((group) => group.id === selectedFileId)) {
      setSelectedFileId(filteredFileGroups[0].id)
    }
  }, [filteredFileGroups, selectedFileId])

  const selectedGroup = useMemo(
    () => fileGroups.find((group) => group.id === selectedFileId) ?? null,
    [fileGroups, selectedFileId],
  )

  const filteredShards = useMemo(() => {
    if (!selectedGroup) return []
    const q = debouncedShardSearch.trim().toLowerCase()
    if (!q) return selectedGroup.shards
    return selectedGroup.shards.filter((shard) => {
      const fields = [
        getShardTitle(shard, shard.originalIndex),
        getShardSummary(shard),
        shard.metadata?.source_type,
        shard.metadata?.module_name,
        shard.content,
      ]
      return fields.some(
        (value) => typeof value === "string" && value.toLowerCase().includes(q),
      )
    })
  }, [selectedGroup, debouncedShardSearch])

  const visibleShards = useMemo(
    () => filteredShards.slice(0, visibleCount),
    [filteredShards, visibleCount],
  )

  const hasMoreShards = filteredShards.length > visibleCount

  useEffect(() => {
    setVisibleCount(50)
    setShardSearch("")
    setDebouncedShardSearch("")
  }, [selectedFileId])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-medium text-content flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-content-muted shrink-0" />
            知识分片
          </h3>
          <p className="text-xs text-content-muted mt-1">
            {fileGroups.length} 个文件 · {results.length} 个分片
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void loadKnowledge()}
          disabled={isLoading}
          className="h-8 shrink-0"
        >
          {isLoading ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <>
              <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
              刷新
            </>
          )}
        </Button>
      </div>

      {isLoading ? (
        <div className="rounded-xl border border-line bg-surface shadow-sm p-16 flex flex-col items-center justify-center text-content-muted">
          <Loader2 className="w-7 h-7 animate-spin mb-3 text-cta" />
          <p className="text-sm">正在加载知识分片…</p>
        </div>
      ) : results.length === 0 ? (
        <div className="rounded-xl border border-line bg-surface shadow-sm overflow-hidden">
          <EmptyState icon={BookOpen} message="暂无知识分片" />
        </div>
      ) : (
        <div className="rounded-xl border border-line bg-surface shadow-sm overflow-hidden min-h-[520px] h-[min(72vh,720px)] grid grid-cols-1 lg:grid-cols-[minmax(260px,30%)_minmax(0,1fr)]">
          <aside className="flex flex-col min-h-0 border-b lg:border-b-0 lg:border-r border-line bg-surface-muted/25 max-lg:max-h-[38vh]">
            <div className="shrink-0 px-3 py-3 border-b border-line space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-content">源文件</span>
                <span className="text-xs text-content-muted tabular-nums">
                  {filteredFileGroups.length}/{fileGroups.length}
                </span>
              </div>
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-content-muted pointer-events-none" />
                <Input
                  value={fileSearch}
                  onChange={handleFileSearchChange}
                  placeholder="搜索文件名…"
                  className="pl-8 h-8 text-sm bg-surface"
                />
              </div>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto p-2">
              {filteredFileGroups.length === 0 ? (
                <div className="px-3 py-10 text-sm text-content-muted text-center">
                  未找到匹配的文件
                </div>
              ) : (
                <ul className="space-y-0.5" role="listbox" aria-label="源文件列表">
                  {filteredFileGroups.map((group) => {
                    const active = group.id === selectedFileId
                    return (
                      <li key={group.id}>
                        <button
                          type="button"
                          role="option"
                          aria-selected={active}
                          onClick={() => setSelectedFileId(group.id)}
                          className={cn(
                            "w-full flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors cursor-pointer",
                            active
                              ? "bg-surface text-content shadow-sm ring-1 ring-line"
                              : "text-content hover:bg-surface/80",
                          )}
                        >
                          <FileText
                            className={cn(
                              "w-4 h-4 shrink-0",
                              active ? "text-cta" : "text-content-muted",
                            )}
                          />
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium truncate leading-snug">
                              {group.label}
                            </div>
                            {group.detail ? (
                              <div className="text-[11px] text-content-muted truncate mt-0.5">
                                {group.detail}
                              </div>
                            ) : null}
                          </div>
                          <span
                            className={cn(
                              "shrink-0 text-xs tabular-nums px-1.5 py-0.5 rounded-md",
                              active
                                ? "bg-cta/10 text-cta font-medium"
                                : "text-content-muted",
                            )}
                          >
                            {group.shards.length}
                          </span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </aside>

          <section className="flex flex-col min-h-0 min-w-0">
            {selectedGroup ? (
              <>
                <div className="shrink-0 px-4 py-3 border-b border-line flex flex-wrap items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-content truncate">
                      {selectedGroup.label}
                    </div>
                    <div className="text-xs text-content-muted mt-0.5">
                      {debouncedShardSearch.trim()
                        ? `${filteredShards.length}/${selectedGroup.shards.length} 个分片`
                        : `${selectedGroup.shards.length} 个分片`}
                    </div>
                  </div>
                  <div className="relative w-full sm:w-52">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-content-muted pointer-events-none" />
                    <Input
                      value={shardSearch}
                      onChange={handleShardSearchChange}
                      placeholder="搜索当前文件分片…"
                      className="pl-8 h-8 text-sm"
                    />
                  </div>
                </div>

                <div className="flex-1 min-h-0 overflow-auto p-4">
                  {filteredShards.length === 0 ? (
                    <div className="h-full flex items-center justify-center p-8">
                      <EmptyState
                        icon={Search}
                        message="未找到匹配的分片"
                        subMessage="试试其他关键词"
                      />
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                      {visibleShards.map((shard) => {
                        const summary = getShardSummary(shard)
                        const sourceType =
                          typeof shard.metadata?.source_type === "string"
                            ? shard.metadata.source_type
                            : ""
                        const { preview: summaryPreview, fileCount } = getSummaryPreview(summary)
                        const isSelected = selectedShard?.originalIndex === shard.originalIndex

                        return (
                          <Card
                            key={shard.originalIndex}
                            onClick={() => setSelectedShard(shard)}
                            className={cn(
                              "cursor-pointer group flex flex-col min-h-[200px] relative overflow-hidden transition-shadow duration-200",
                              "hover:shadow-md",
                              isSelected && "ring-2 ring-brand/30 shadow-md",
                            )}
                          >
                            <div className="absolute top-0 right-0 p-3 opacity-[0.04] group-hover:opacity-[0.08] transition-opacity pointer-events-none">
                              <Layers className="w-16 h-16 text-cta" />
                            </div>

                            <CardHeader className="relative z-10 pb-2 space-y-2">
                              <div className="flex items-center justify-between gap-2">
                                {sourceType ? (
                                  <Badge
                                    variant="outline"
                                    className={cn(
                                      "px-2 py-0.5 text-xs font-medium max-w-[9rem] truncate",
                                      sourceBadgeClass(sourceType),
                                    )}
                                  >
                                    {sourceType}
                                  </Badge>
                                ) : (
                                  <span />
                                )}
                                <Maximize2 className="w-4 h-4 text-content-muted group-hover:text-cta transition-colors shrink-0" />
                              </div>
                              <CardTitle className="text-base line-clamp-2 leading-snug group-hover:text-cta transition-colors">
                                {getShardTitle(shard, shard.originalIndex)}
                              </CardTitle>
                            </CardHeader>

                            <CardContent className="relative z-10 flex-1 pt-0">
                              <p className="text-sm text-content-muted leading-relaxed line-clamp-4">
                                {summaryPreview}
                              </p>
                            </CardContent>

                            <CardFooter className="relative z-10 mt-auto border-t border-line flex items-center gap-2 text-xs text-content-muted px-4 py-2.5">
                              {fileCount > 0 ? (
                                <span className="text-[11px] bg-surface-muted border border-line rounded px-2 py-0.5">
                                  {fileCount} files
                                </span>
                              ) : null}
                              <div className="flex-1" />
                              <span className="font-mono tabular-nums opacity-60">
                                #{shard.originalIndex + 1}
                              </span>
                            </CardFooter>
                          </Card>
                        )
                      })}
                    </div>
                  )}
                </div>

                {hasMoreShards ? (
                  <div className="shrink-0 border-t border-line px-4 py-3 flex justify-center bg-surface">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setVisibleCount((count) => count + 50)}
                    >
                      加载更多（还剩 {filteredShards.length - visibleCount} 个）
                    </Button>
                  </div>
                ) : null}
              </>
            ) : (
              <div className="flex-1 flex items-center justify-center p-8">
                <EmptyState icon={FileText} message="请选择左侧文件查看分片" />
              </div>
            )}
          </section>
        </div>
      )}

      <Dialog open={!!selectedShard} onOpenChange={(open) => !open && setSelectedShard(null)}>
        <DialogContent className="w-[min(96vw,72rem)] max-w-none max-h-[90vh] flex flex-col p-0 overflow-hidden">
          <DialogHeader className="px-6 py-5 border-b border-line bg-surface-muted/50 flex-shrink-0 relative">
            <div className="flex items-center gap-3 mb-2">
              {typeof selectedShard?.metadata?.source_type === "string" &&
              String(selectedShard.metadata.source_type).trim() ? (
                <Badge variant="outline" className="bg-cta/10 text-cta border-cta/20">
                  {String(selectedShard.metadata.source_type).trim()}
                </Badge>
              ) : null}
              <span className="text-xs text-content-muted font-mono">
                #{selectedShard ? selectedShard.originalIndex + 1 : "-"}
              </span>
            </div>
            <DialogTitle className="text-xl text-content pr-8">
              {selectedShard ? getShardTitle(selectedShard, selectedShard.originalIndex) : "分片详情"}
            </DialogTitle>
            <button
              type="button"
              className="absolute right-4 top-4 p-2 text-content-muted hover:text-content hover:bg-surface-muted rounded-full transition-colors cursor-pointer"
              onClick={() => setSelectedShard(null)}
              aria-label="关闭"
            >
              <X className="w-5 h-5" />
            </button>
          </DialogHeader>

          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <div className="space-y-3">
              <h4 className="text-sm font-semibold text-content flex items-center gap-2">
                <FileText className="w-4 h-4 text-cta" />
                Summary
              </h4>
              <div className="text-sm text-content leading-7 bg-surface-muted p-4 rounded-lg border border-line whitespace-pre-wrap break-words">
                {(typeof selectedShard?.metadata?.summary === "string" && selectedShard.metadata.summary.trim()) ||
                  (selectedShard?.content ? "未找到 summary，以下为原文内容。" : "暂无内容。")}
              </div>
            </div>

            {selectedShard?.content ? (
              <div className="space-y-3 pt-4 border-t border-line">
                <h4 className="text-sm font-semibold text-content flex items-center gap-2">
                  <FileText className="w-4 h-4 text-content-muted" />
                  Detail
                </h4>
                <div className="bg-surface p-4 rounded-lg border border-line prose prose-sm max-w-none prose-slate">
                  <Markdown components={knowledgeDetailMarkdownComponents}>
                    {selectedShard.content}
                  </Markdown>
                </div>
              </div>
            ) : null}

            {selectedShard?.metadata ? (
              <div className="space-y-3 pt-4 border-t border-line">
                <h4 className="text-sm font-semibold text-content flex items-center gap-2">
                  <Info className="w-4 h-4 text-content-muted" />
                  Metadata
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 bg-surface-muted rounded-lg p-4 border border-line">
                  {Object.entries(selectedShard.metadata)
                    .filter(([key]) => !["module_name", "summary", "source_type"].includes(key))
                    .map(([key, value]) => (
                      <div key={key} className="space-y-1 min-w-0">
                        <div className="text-xs font-medium text-content-muted">
                          {key}
                        </div>
                        <div className="text-sm text-content font-mono break-all">{String(value)}</div>
                      </div>
                    ))}
                </div>
              </div>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

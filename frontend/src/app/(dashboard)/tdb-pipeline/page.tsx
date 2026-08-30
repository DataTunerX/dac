"use client"

import { useCallback, useMemo, useState } from "react"
import useSWR from "swr"
import {
  Ban,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  UploadCloud,
  Workflow,
} from "lucide-react"
import { toast } from "sonner"

import { PaginationBar } from "@/components/pagination-bar"
import { RbacWrapper } from "@/components/rbac"
import { TDBPipelineCreateDialog } from "@/components/tdb-pipeline-create-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { PageContainer } from "@/components/ui/page-container"
import { PageHeader } from "@/components/ui/page-header"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { TableWrapper } from "@/components/ui/table-wrapper"
import { getApiErrorMessage } from "@/lib/api-error"
import type { TDBPipelineRun } from "@/lib/api-types"
import {
  cancelTDBPipelineRun,
  getTDBPipelineOptions,
  isTerminalRunStatus,
  listTDBPipelineRuns,
  pauseTDBPipelineRun,
  resumeTDBPipelineRun,
  retryTDBPipelineFailed,
  retryTDBPipelineS3Upload,
} from "@/lib/tdb-pipeline-api"

/** Runs advance on their own, so the list re-reads while any run is live. */
const LIVE_REFRESH_MS = 15000

const STATUS_STYLES: Record<string, string> = {
  accepted: "bg-cta/10 text-cta border-cta/20",
  running: "bg-cta/10 text-cta border-cta/20",
  paused: "bg-amber-50 text-amber-700 border-amber-200",
  succeeded: "bg-[#ecfdf5] text-[#16a34a] border-[#bbf7d0]",
  failed: "bg-red-50 text-red-700 border-red-200",
  canceled: "bg-surface-muted text-content border-line",
}

function RunStatusBadge({ status }: { status: string }) {
  const key = status.trim().toLowerCase()
  return (
    <Badge
      variant="outline"
      className={STATUS_STYLES[key] ?? "bg-surface-muted text-content border-line"}
    >
      {status || "unknown"}
    </Badge>
  )
}

function formatTime(input?: string) {
  if (!input) return "-"
  const d = new Date(input)
  if (!Number.isFinite(d.getTime())) return "-"
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d)
}

/** Compact per-job tally: finished / total, with failures called out. */
function RunProgress({ run }: { run: TDBPipelineRun }) {
  const { counters } = run
  const done = counters.succeeded + counters.failed + counters.canceled
  return (
    <div className="space-y-0.5 text-xs">
      <div className="text-content">
        {done} / {counters.total_jobs}
      </div>
      <div className="text-content-muted">
        {counters.running > 0 ? `运行 ${counters.running} · ` : ""}
        {counters.queued > 0 ? `排队 ${counters.queued} · ` : ""}
        <span className={counters.failed > 0 ? "text-red-600" : undefined}>
          失败 {counters.failed}
        </span>
      </div>
    </div>
  )
}

export default function TDBPipelinePage() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [createOpen, setCreateOpen] = useState(false)
  const [busyRunId, setBusyRunId] = useState<string | null>(null)

  const { data: options } = useSWR("tdb-pipeline-options", getTDBPipelineOptions)

  const listKey = useMemo(
    () => ["tdb-pipeline-runs", page, pageSize] as const,
    [page, pageSize]
  )
  const { data, error, isLoading, mutate } = useSWR(
    listKey,
    () => listTDBPipelineRuns({ limit: pageSize, offset: (page - 1) * pageSize }),
    {
      refreshInterval: (latest) =>
        latest?.items?.some((run) => !isTerminalRunStatus(run.status)) ? LIVE_REFRESH_MS : 0,
    }
  )

  const runs = data?.items ?? []
  const total = data?.totalCount ?? 0

  const runAction = useCallback(
    async (runId: string, label: string, action: (id: string) => Promise<unknown>) => {
      setBusyRunId(runId)
      try {
        await action(runId)
        toast.success(`${label}成功`)
        await mutate()
      } catch (err) {
        toast.error(getApiErrorMessage(err, `${label}失败`))
      } finally {
        setBusyRunId(null)
      }
    },
    [mutate]
  )

  return (
    <PageContainer>
      <PageHeader
        title="TDB 入库流水线"
        description="向 TDB Pipeline Controller 提交异步入库任务，写入与各领域技能 Agent 共用的 TDB。"
        actions={
          <>
            <Button variant="outline" onClick={() => void mutate()} disabled={isLoading}>
              <RefreshCw className={isLoading ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"} />
              刷新
            </Button>
            <RbacWrapper>
              <Button onClick={() => setCreateOpen(true)} disabled={!options}>
                <Plus className="mr-2 h-4 w-4" />
                新建入库任务
              </Button>
            </RbacWrapper>
          </>
        }
      />

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {getApiErrorMessage(error, "加载入库任务失败")}
        </div>
      ) : null}

      <TableWrapper>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>运行 ID</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>目标</TableHead>
              <TableHead>源</TableHead>
              <TableHead>进度</TableHead>
              <TableHead>提交时间</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && runs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="py-10 text-center text-content-muted">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin" />
                </TableCell>
              </TableRow>
            ) : runs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7}>
                  <EmptyState
                    icon={Workflow}
                    message="暂无入库任务"
                    subMessage="点击“新建入库任务”，选择领域与源地址即可提交。"
                  />
                </TableCell>
              </TableRow>
            ) : (
              runs.map((run) => {
                const busy = busyRunId === run.run_id
                const terminal = isTerminalRunStatus(run.status)
                return (
                  <TableRow key={run.run_id}>
                    <TableCell className="font-mono text-xs" title={run.run_id}>
                      {run.run_id}
                      {run.summary_error ? (
                        <div
                          className="text-[11px] text-amber-600"
                          title={run.summary_error}
                        >
                          状态可能过期：控制器不可达
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <RunStatusBadge status={run.status} />
                    </TableCell>
                    <TableCell className="text-xs">
                      <div className="text-content">{run.domain}</div>
                      <div className="text-content-muted">{run.gateway_url}</div>
                    </TableCell>
                    <TableCell
                      className="max-w-[240px] truncate text-xs text-content-muted"
                      title={run.source_uri}
                    >
                      {run.source_uri}
                    </TableCell>
                    <TableCell>
                      <RunProgress run={run} />
                    </TableCell>
                    <TableCell className="text-xs text-content-muted">
                      {formatTime(run.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <RbacWrapper>
                        <div className="flex justify-end gap-1">
                          {run.status === "paused" ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={busy}
                              title="继续"
                              onClick={() =>
                                void runAction(run.run_id, "继续", resumeTDBPipelineRun)
                              }
                            >
                              <Play className="h-4 w-4" />
                            </Button>
                          ) : (
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={busy || terminal}
                              title="暂停派发"
                              onClick={() =>
                                void runAction(run.run_id, "暂停", pauseTDBPipelineRun)
                              }
                            >
                              <Pause className="h-4 w-4" />
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy || run.counters.failed === 0}
                            title="重试失败任务"
                            onClick={() =>
                              void runAction(run.run_id, "重试", (id) =>
                                retryTDBPipelineFailed(id)
                              )
                            }
                          >
                            <RotateCcw className="h-4 w-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy}
                            title="仅重试产物上传"
                            onClick={() =>
                              void runAction(run.run_id, "重试上传", retryTDBPipelineS3Upload)
                            }
                          >
                            <UploadCloud className="h-4 w-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy || terminal}
                            title="取消运行"
                            onClick={() =>
                              void runAction(run.run_id, "取消", cancelTDBPipelineRun)
                            }
                          >
                            <Ban className="h-4 w-4" />
                          </Button>
                        </div>
                      </RbacWrapper>
                    </TableCell>
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </TableWrapper>

      <PaginationBar
        total={total}
        page={page}
        pageSize={pageSize}
        isLoading={isLoading}
        onPageChange={setPage}
        onPageSizeChange={(size) => {
          setPageSize(size)
          setPage(1)
        }}
      />

      <TDBPipelineCreateDialog
        open={createOpen}
        options={options}
        onOpenChange={setCreateOpen}
        onCreated={() => void mutate()}
      />
    </PageContainer>
  )
}

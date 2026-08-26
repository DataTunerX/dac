"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useParams, useRouter } from "next/navigation"
import useSWR from "swr"
import { toast } from "sonner"
import { api } from "@/lib/api"
import {
  appendDescriptorSourcesAndResync,
  getDescriptor,
  listAllDescriptors,
} from "@/lib/descriptors-api"
import {
  buildAppendSources,
  buildCreateDescriptorPayload,
} from "@/lib/descriptor-payload"
import type { DataDescriptorResponse, DataSourceResponse } from "@/lib/api-types"
import { validateSystemLlmConfigMaps } from "@/lib/system-config-meta"
import { RbacButton, RbacWrapper } from "@/components/rbac"
import { useAuthHydrated, useIsSuper } from "@/lib/use-user-role"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
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
import { 
  ArrowLeft, 
  Loader2, 
  RefreshCw, 
  Trash2, 
  Network, 
  ChevronRight, 
  Activity, 
  Server, 
  Clock, 
  Target,
  List,
  Link as LinkIcon
} from "lucide-react"
import type { DiscoveryJobResponse, DiscoveryJobStatus, DiscoveredService } from "@/lib/discovery"
import {
  deleteDiscoveryScan,
  detectCreateType,
  discoveryMatchType,
  extractDataSourceEndpoint,
  getConnectionIdentity,
  getDiscoveryScan,
} from "@/lib/discovery"
import { CreateDataSourceDialog, type DataSourceFormValues } from "@/components/data-source-forms"
import { cn } from "@/lib/utils"
import { BrandIcon } from "@/components/brand-icon"
import { discoveryAssociationsKey, discoveryScanKey } from "@/lib/swr-keys"
import { getApiErrorMessage } from "@/lib/api-error"

function statusBadgeVariant(status: DiscoveryJobStatus): "secondary" | "destructive" | "outline" {
  if (status === "FAILED") return "destructive"
  if (status === "SUCCEEDED") return "secondary"
  return "outline"
}

function statusLabel(status: DiscoveryJobStatus) {
  switch (status) {
    case "PENDING":
      return "排队中"
    case "RUNNING":
      return "扫描中"
    case "SUCCEEDED":
      return "已完成"
    case "FAILED":
      return "失败"
    default:
      return status
  }
}

function servicePill(s: DiscoveredService) {
  const name = (s.serviceType || "unknown").toUpperCase()
  const product = [s.product, s.version].filter(Boolean).join(" ")
  return product ? `${name} · ${product}` : name
}

function formatDuration(start?: number, end?: number, status?: DiscoveryJobStatus): string {
  if (!start) return "-"
  // Auto-detect unit: if start is small (e.g. < 1e11), assume seconds, else milliseconds
  const isSeconds = start < 100000000000
  const startTime = isSeconds ? start * 1000 : start
  const endTime = end ? (isSeconds ? end * 1000 : end) : Date.now()
  
  // If pending, duration is 0 or -
  if (status === "PENDING") return "-"

  const diff = Math.max(0, endTime - startTime)
  if (diff < 1000) return "< 1s"
  
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return `${seconds}s`
  
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return `${minutes}m ${remainingSeconds}s`
}

function InfoItem({ label, value, icon: Icon, fullWidth = false }: { label: string; value: React.ReactNode; icon?: React.ComponentType<{ className?: string }>; fullWidth?: boolean }) {
  return (
    <div className={cn("space-y-1.5", fullWidth ? "md:col-span-2" : "")}>
      <div className="text-xs font-medium text-content-muted flex items-center gap-1.5">
        {Icon ? <Icon className="w-3.5 h-3.5" /> : null}
        {label}
      </div>
      <div className="flex items-center px-3 py-2 rounded-md border border-line bg-surface text-sm text-content font-normal shadow-sm min-h-[38px]">
        {value}
      </div>
    </div>
  )
}

function LinkItem({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="flex items-center hover:text-cta transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cta focus-visible:ring-offset-2 rounded cursor-pointer"
    >
      {label}
    </Link>
  )
}

const normalize = (s?: string) => (s || "").trim().toLowerCase()

type ServiceIconKind =
  | {
      kind: "brand"
      slug:
        | "mysql"
        | "postgresql"
        | "minio"
        | "github"
        | "gitlab"
        | "gitee"
        | "redis"
        | "nginx"
        | "openssh"
    }
  | { kind: "lucide"; name: "server" | "link" }

function inferServiceIcon(s: DiscoveredService): ServiceIconKind {
  const st = normalize(s.serviceType)
  const product = normalize(s.product)

  if (st === "mysql" || product.includes("mysql") || product.includes("mariadb")) {
    return { kind: "brand", slug: "mysql" }
  }
  if (st === "postgres" || product.includes("postgres")) {
    return { kind: "brand", slug: "postgresql" }
  }
  if (st === "redis" || product.includes("redis")) {
    return { kind: "brand", slug: "redis" }
  }
  if (product.includes("minio")) {
    return { kind: "brand", slug: "minio" }
  }

  if (st === "ssh" || product.includes("openssh") || product.includes("ssh")) {
    return { kind: "brand", slug: "openssh" }
  }

  if (st === "http" && product.includes("nginx")) {
    return { kind: "brand", slug: "nginx" }
  }

  // Code repo heuristics: product banner often includes GitLab/Gitee/GitHub.
  if (product.includes("gitlab")) return { kind: "brand", slug: "gitlab" }
  if (product.includes("gitee")) return { kind: "brand", slug: "gitee" }
  if (product.includes("github")) return { kind: "brand", slug: "github" }

  // Fallback
  return { kind: "lucide", name: "server" }
}

function ServiceIconCell({ s }: { s: DiscoveredService }) {
  const icon = inferServiceIcon(s)
  return (
    <div className="w-8 h-8 rounded-full bg-cta/10 flex items-center justify-center shrink-0">
      {icon.kind === "brand" ? (
        <BrandIcon slug={icon.slug} size={16} />
      ) : (
        <Server className="w-4 h-4 text-cta" />
      )}
    </div>
  )
}

interface DataSourceRef {
  name: string
  namespace: string
  /** Canonical match type (e.g. coderepo, minio, mysql). */
  type: string
  host: string
  port: string
  /** Associated database names (mysql/postgres sources only). */
  databases: string[]
}

type AppendContext = {
  namespace: string
  name: string
  lockedDatabases: string[]
  /** Kept out of form inputs — never echoed into the password field */
  retainedCredentials: { user: string; password: string }
  connectionType: "mysql" | "postgres"
  host: string
  port: string
  promptsConfigMapName: string
  gpuEnabled: string
  descriptorType: string
}

const INFRA_SERVICES_COLUMNS = [
  { id: "host", size: 160 },
  { id: "port", size: 80 },
  { id: "service", size: 220 },
  { id: "tls", size: 72 },
  { id: "details", size: 260 },
  { id: "actions", size: 200 },
] as const

/** Prefer human-useful metadata in the details column; skip internal scanner tags. */
function detailHints(s: DiscoveredService): [string, string][] {
  const skip = new Set(["fingerprinter", "transport"])
  const entries = Object.entries(s.metadata ?? {})
    .filter(([k, v]) => !skip.has(k) && v != null && String(v).trim() !== "")
    .map(([k, v]) => [k, String(v)] as [string, string])
  return entries.slice(0, 3)
}

const linkedActionSegmentClass =
  "inline-flex h-full items-center justify-center gap-1.5 px-3 text-xs font-medium leading-none transition-colors disabled:pointer-events-none disabled:opacity-50"

/**
 * Single-height table action for already-linked services:
 * status + optional CTA as equal halves of one segmented control.
 */
function LinkedServiceActions({
  linkedCount,
  onView,
  canAppend,
  onAppend,
  isAppendLoading,
}: {
  linkedCount: number
  onView: () => void
  canAppend: boolean
  onAppend: () => void
  isAppendLoading: boolean
}) {
  const linkedLabel = linkedCount > 0 ? `已关联 · ${linkedCount}` : "已关联"
  const authHydrated = useAuthHydrated()
  const canAppendAsAdmin = useIsSuper()
  const appendEnabled = authHydrated && canAppendAsAdmin

  if (!canAppend) {
    return (
      <button
        type="button"
        onClick={onView}
        title="查看已关联数据源"
        className="inline-flex h-8 max-w-full items-center gap-1.5 rounded-md border border-line bg-surface px-3 text-xs font-medium leading-none text-cta transition-colors hover:bg-cta/5"
      >
        <LinkIcon className="size-3.5 shrink-0 opacity-80" />
        <span className="truncate tabular-nums">{linkedLabel}</span>
      </button>
    )
  }

  return (
    <div
      className="inline-flex h-8 max-w-full items-stretch overflow-hidden rounded-md border border-line"
      role="group"
      aria-label="数据源关联操作"
    >
      <button
        type="button"
        onClick={onView}
        title="查看已关联数据源"
        className={cn(linkedActionSegmentClass, "min-w-0 bg-surface text-content hover:bg-surface-muted")}
      >
        <LinkIcon className="size-3.5 shrink-0 text-cta" />
        <span className="truncate tabular-nums">{linkedLabel}</span>
      </button>
      <span className="w-px shrink-0 self-stretch bg-line" aria-hidden />
      <button
        type="button"
        onClick={onAppend}
        disabled={!appendEnabled || isAppendLoading}
        title={
          !authHydrated
            ? "继续关联数据库"
            : canAppendAsAdmin
              ? "继续关联数据库"
              : "无权限：仅管理员可继续关联"
        }
            className={cn(
              linkedActionSegmentClass,
              "shrink-0 bg-btn-primary text-content-inverse hover:bg-btn-primary-hover"
            )}
      >
        {isAppendLoading ? <Loader2 className="size-3.5 animate-spin" /> : null}
        继续关联
      </button>
    </div>
  )
}

function buildAssociationIndex(items: DataDescriptorResponse[]): DataSourceRef[] {
  const byKey = new Map<string, DataSourceRef>()
  for (const item of items) {
    for (const s of (item.sources ?? []) as DataSourceResponse[]) {
      const ep = extractDataSourceEndpoint(s)
      if (!ep) continue
      const identity = getConnectionIdentity(ep.matchType, ep.host, ep.port)
      const key = `${item.namespace ?? "default"}/${item.name}|${identity}`
      const db = String(s.metadata?.database ?? "").trim()
      const existing = byKey.get(key)
      if (existing) {
        if (db && !existing.databases.includes(db)) existing.databases.push(db)
      } else {
        byKey.set(key, {
          name: item.name,
          namespace: item.namespace ?? "default",
          type: ep.matchType,
          host: ep.host,
          port: ep.port,
          databases: db ? [db] : [],
        })
      }
    }
  }
  return [...byKey.values()]
}

export default function InfraDiscoveryDetailPage() {
  const router = useRouter()
  const params = useParams<{ id: string }>()
  const id = decodeURIComponent(params?.id || "")

  const {
    data: job,
    error: jobError,
    isLoading,
    isValidating,
    mutate: mutateJob,
  } = useSWR(
    id ? discoveryScanKey(id) : null,
    () => getDiscoveryScan(id),
    {
      refreshInterval: (latest) =>
        latest?.status === "PENDING" || latest?.status === "RUNNING" ? 1200 : 0,
      revalidateOnFocus: false,
    },
  )

  useEffect(() => {
    if (jobError) toast.error("加载扫描详情失败")
  }, [jobError])

  const { data: existingDataSources = [], mutate: mutateAssociations } = useSWR(
    discoveryAssociationsKey,
    async () => buildAssociationIndex(await listAllDescriptors()),
    { revalidateOnFocus: false },
  )

  const isPolling = job?.status === "PENDING" || job?.status === "RUNNING"

  const [isDeleteOpen, setIsDeleteOpen] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [createInitial, setCreateInitial] = useState<Partial<DataSourceFormValues> | null>(null)
  const [appendContext, setAppendContext] = useState<AppendContext | null>(null)
  const [isAppendLoading, setIsAppendLoading] = useState(false)

  const services = useMemo(() => {
    const items = job?.services || []
    return [...items].sort((a, b) => (a.port ?? 0) - (b.port ?? 0))
  }, [job?.services])

  const findMatchingDataSource = (s: DiscoveredService) => {
    const type = discoveryMatchType(s)
    const targetIdentity = getConnectionIdentity(type, s.host, s.port)

    return existingDataSources.find((ds) => {
      const dsIdentity = getConnectionIdentity(ds.type, ds.host, ds.port)
      return dsIdentity === targetIdentity
    })
  }

  /** Union of databases already linked on this host:port across all descriptors. */
  const getAssociatedDatabases = (s: DiscoveredService): string[] => {
    const type = discoveryMatchType(s)
    const targetIdentity = getConnectionIdentity(type, s.host, s.port)
    const dbs = new Set<string>()
    for (const ds of existingDataSources) {
      const dsIdentity = getConnectionIdentity(ds.type, ds.host, ds.port)
      if (dsIdentity !== targetIdentity) continue
      for (const db of ds.databases) {
        if (db) dbs.add(db)
      }
    }
    return [...dbs]
  }

  const openCreateFromService = (s: DiscoveredService) => {
    const t = detectCreateType(s)
    if (!t) {
      toast.error("该服务类型暂不支持一键创建数据源")
      return
    }
    setAppendContext(null)
    const safeName = `${t}-${s.host}-${s.port}`
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, "-")
      .replace(/-+/g, "-")
      .slice(0, 63)
    if (t === "coderepo") {
      const baseUrl = `http://${s.host}:${String(s.port).trim().replace(/^:/, "")}`
      const product = normalize(s.product)
      const codeRepoType = product.includes("gitee")
        ? "gitee"
        : product.includes("github")
          ? "github"
          : "gitlab"
      setCreateInitial({
        name: safeName,
        namespace: "default",
        type: "coderepo",
        // Best-effort defaults; user can refine to /owner/repo(.git)
        codeRepoType,
        codeRepoPath: baseUrl,
        codeRepoBranch: "main",
        codeRepoToken: "",
      })
    } else {
      setCreateInitial({
        name: safeName,
        namespace: "default",
        type: t,
        host: s.host,
        port: String(s.port),
      })
    }
    setIsCreateOpen(true)
  }

  const openAppendFromService = async (s: DiscoveredService, match: DataSourceRef) => {
    if (match.type !== "mysql" && match.type !== "postgres") {
      toast.error("仅 MySQL / Postgres 支持继续关联数据库")
      return
    }
    setIsAppendLoading(true)
    try {
      const dd = await getDescriptor(match.namespace, match.name)
      const identity = getConnectionIdentity(match.type, match.host, match.port)
      const template = (dd.sources ?? []).find((src) => {
        const ep = extractDataSourceEndpoint(src)
        if (!ep) return false
        return getConnectionIdentity(ep.matchType, ep.host, ep.port) === identity
      })
      const meta = template?.metadata ?? {}
      const lockedDatabases = getAssociatedDatabases(s)
      const connectionType = match.type as "mysql" | "postgres"
      setAppendContext({
        namespace: match.namespace,
        name: match.name,
        lockedDatabases,
        retainedCredentials: {
          user: String(meta.user ?? ""),
          password: String(meta.password ?? ""),
        },
        connectionType,
        host: match.host,
        port: match.port,
        promptsConfigMapName: template?.prompts?.configMapName ?? "",
        gpuEnabled: dd.gpuEnabled === "yes" ? "yes" : "no",
        descriptorType:
          connectionType === "postgres" ? "structured-postgres" : "structured-mysql",
      })
      // Do not put password into form state (avoid echoing secrets into the DOM).
      setCreateInitial({
        name: match.name,
        namespace: match.namespace,
        type: connectionType,
        host: match.host,
        port: match.port,
        user: String(meta.user ?? ""),
        password: "",
        databases: [],
        gpuEnabled: dd.gpuEnabled === "yes" ? "yes" : "no",
        promptsConfigMapName: template?.prompts?.configMapName ?? "",
      })
      setIsCreateOpen(true)
    } catch (e) {
      console.error("Failed to open append dialog", e)
      toast.error("加载已有数据源失败，无法继续关联")
    } finally {
      setIsAppendLoading(false)
    }
  }

  const handleCreate = async (data: DataSourceFormValues & { enableCodeRepo?: boolean }) => {
    // Continue-associate: DD already exists; LLM pre-check was done at create time.
    if (appendContext) {
      const locked = new Set(appendContext.lockedDatabases)
      const newDbs = (data.databases ?? [])
        .map((s) => s.trim())
        .filter(Boolean)
        .filter((db) => !locked.has(db))
      if (newDbs.length === 0) {
        toast.error("请至少选择一个尚未关联的数据库")
        throw new Error("请至少选择一个尚未关联的数据库")
      }

      try {
        const dd = await getDescriptor(appendContext.namespace, appendContext.name)
        const sources = buildAppendSources({
          existingSources: dd.sources ?? [],
          descriptorName: appendContext.name,
          type: appendContext.connectionType,
          host: String(data.host ?? appendContext.host),
          port: String(data.port ?? appendContext.port),
          user: String(data.user ?? appendContext.retainedCredentials.user),
          password: String(data.password ?? appendContext.retainedCredentials.password),
          newDatabases: newDbs,
          promptsConfigMapName:
            String(data.promptsConfigMapName || "").trim() || appendContext.promptsConfigMapName,
        })
        await appendDescriptorSourcesAndResync(
          appendContext.namespace,
          appendContext.name,
          sources,
          {
            gpuEnabled: data.gpuEnabled === "yes" ? "yes" : appendContext.gpuEnabled,
            descriptorType: appendContext.descriptorType,
          },
        )
        toast.success(`已关联 ${newDbs.length} 个新数据库，同步已触发`)
        await mutateAssociations()
        setAppendContext(null)
        setIsCreateOpen(false)
      } catch (err) {
        console.error("continue-associate append failed", err)
        toast.error(getApiErrorMessage(err, "继续关联失败"), { duration: 10000 })
        throw err
      }
      return
    }

    // Create: check LLM CMs in the form-selected namespace (matches operator PreCheck).
    const targetNs = String(data.namespace || "default").trim() || "default"
    const llmErr = await validateSystemLlmConfigMaps(targetNs)
    if (llmErr) {
      toast.error(llmErr, { duration: 8000 })
      throw new Error(llmErr)
    }

    try {
      const payload = buildCreateDescriptorPayload(data)
      await api.post(
        `/namespaces/${encodeURIComponent(payload.namespace)}/descriptors`,
        payload,
      )
      toast.success("数据源创建成功")
      await mutateAssociations()
      setIsCreateOpen(false)
    } catch (err) {
      console.error("create from discovery failed", err)
      toast.error(getApiErrorMessage(err, "创建失败，请检查输入或日志"))
      throw err
    }
  }

  const onDelete = async () => {
    if (!id) return
    setIsDeleting(true)
    try {
      await deleteDiscoveryScan(id)
      toast.success("已删除扫描记录")
      router.push("/infra")
    } catch (err) {
      console.error("Delete discovery scan failed", err)
      toast.error("删除失败")
    } finally {
      setIsDeleting(false)
      setIsDeleteOpen(false)
    }
  }

  const title = job?.name || id

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6">
      {/* Header Section */}
      <div className="space-y-4">
        {/* Breadcrumb */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.back()}
              className="-ml-2 h-8 px-2 text-content-muted hover:text-content"
            >
              <ArrowLeft className="w-4 h-4 mr-1" />
              返回
            </Button>
            <nav className="flex items-center text-sm text-content-muted min-w-0" aria-label="Breadcrumb">
              <LinkItem href="/infra" label="资产探测" />
              <ChevronRight className="w-4 h-4 mx-2 text-content-muted shrink-0" />
              <span className="font-medium text-content truncate">{id}</span>
            </nav>
          </div>
        </div>

        {/* Title & Actions */}
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-content">{title}</h1>
              {job && (
                <Badge variant={statusBadgeVariant(job.status)} className="font-mono text-xs">
                  {statusLabel(job.status)}
                </Badge>
              )}
            </div>
            {job?.startedAt && (
              <div className="text-sm text-content-muted">
                开始于 <span className="font-mono">{new Date(job.startedAt < 100000000000 ? job.startedAt * 1000 : job.startedAt).toLocaleString()}</span>
              </div>
            )}
          </div>
          
          <div className="flex items-center gap-2">
             <Button
              variant="outline"
              onClick={() => void mutateJob()}
              disabled={isLoading || isValidating}
              className="bg-surface hover:bg-surface-muted"
            >
              <RefreshCw className={cn("w-4 h-4 mr-2", (isPolling || isValidating) && "animate-spin")} />
              刷新
            </Button>
            <RbacWrapper requiredPermission="discovery:manage">
              <Button variant="outline" onClick={() => setIsDeleteOpen(true)} className="bg-surface hover:bg-red-50 hover:text-red-600 hover:border-red-200">
                <Trash2 className="w-4 h-4 mr-2" />
                删除
              </Button>
            </RbacWrapper>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div>
        {isLoading && !job ? (
           <div className="flex flex-col items-center justify-center py-20 text-content-muted">
             <Loader2 className="w-8 h-8 animate-spin mb-4 text-cta" />
             <p>正在加载扫描信息…</p>
           </div>
        ) : !job ? (
          <div className="rounded-lg border border-dashed border-line-hover p-12 text-center">
            <Network className="mx-auto h-12 w-12 text-content-muted" />
            <h3 className="mt-2 text-sm font-semibold text-content">未找到扫描记录</h3>
            <p className="mt-1 text-sm text-content-muted">该记录不存在或已被删除。</p>
            <div className="mt-6">
              <Button variant="outline" onClick={() => router.push("/infra")}>返回列表</Button>
            </div>
          </div>
        ) : (
          <div className="space-y-8">
            {/* Section 1: Basic Info */}
            <section className="space-y-3">
              <h3 className="text-sm font-medium text-content flex items-center gap-2">
                <Target className="w-4 h-4 text-content-muted" />
                基础信息
              </h3>
              <div className="bg-surface rounded-lg border border-line p-5 shadow-sm">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-content-muted flex items-center gap-1.5">
                      <Target className="w-3.5 h-3.5" />
                      扫描目标
                    </div>
                    <div className="flex items-center px-3 py-2 rounded-md border border-line bg-surface text-sm text-content font-normal shadow-sm font-mono">
                      {job.target}
                    </div>
                  </div>
                  
                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-content-muted flex items-center gap-1.5">
                      <Activity className="w-3.5 h-3.5" />
                      当前状态
                    </div>
                    <div className="flex items-center px-3 py-2 rounded-md border border-line bg-surface text-sm shadow-sm">
                      <span className={cn("inline-flex items-center gap-1.5", 
                        job.status === "FAILED" ? "text-red-600" : 
                        job.status === "SUCCEEDED" ? "text-emerald-600" : "text-blue-600"
                      )}>
                        <div className={cn("w-1.5 h-1.5 rounded-full", 
                          job.status === "FAILED" ? "bg-red-500" : 
                          job.status === "SUCCEEDED" ? "bg-emerald-500" : "bg-blue-500 animate-pulse"
                        )} />
                        {statusLabel(job.status)}
                      </span>
                      {job.error ? <span className="ml-2 text-red-500 text-xs truncate" title={job.error}>{job.error}</span> : null}
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-content-muted flex items-center gap-1.5">
                      <Clock className="w-3.5 h-3.5" />
                      任务耗时
                    </div>
                     <div className="flex items-center px-3 py-2 rounded-md border border-line bg-surface text-sm text-content font-normal shadow-sm">
                      {formatDuration(job.startedAt, job.finishedAt, job.status)}
                    </div>
                  </div>
                </div>
              </div>
            </section>

            {/* Section 2: Discovered Services */}
            <section className="space-y-3">
               <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-content flex items-center gap-2">
                 <List className="w-4 h-4 text-content-muted" />
                 发现的服务
               </h3>
               <Badge variant="secondary" className="bg-surface border-line text-content">
                  共 {services.length} 个
               </Badge>
             </div>
             
             <TableWrapper className="shadow-sm">
             <Table storageKey="infra-services-list-v2" columns={[...INFRA_SERVICES_COLUMNS]}>
                <TableHeader>
                  <TableRow className="bg-surface-muted/50">
                    <TableHead columnId="host">地址</TableHead>
                    <TableHead columnId="port">端口</TableHead>
                    <TableHead columnId="service">服务识别</TableHead>
                    <TableHead columnId="tls">TLS</TableHead>
                    <TableHead columnId="details">详细信息</TableHead>
                    <TableHead columnId="actions">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {services.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} className="h-32 text-center text-sm text-content-muted">
                        {job?.status === "RUNNING" || job?.status === "PENDING" ? (
                          <div className="flex flex-col items-center gap-2">
                            <Loader2 className="w-6 h-6 animate-spin text-cta" />
                            <span>正在扫描中，请稍候...</span>
                          </div>
                        ) : (
                          "未发现开放服务"
                        )}
                      </TableCell>
                    </TableRow>
                  ) : (
                    services.map((s) => {
                      const hints = detailHints(s)
                      const canCreate = !!detectCreateType(s)
                      const match = findMatchingDataSource(s)
                      const canAppend = match?.type === "mysql" || match?.type === "postgres"
                      const linkedDbCount = canAppend ? getAssociatedDatabases(s).length : 0
                      return (
                        <TableRow key={`${s.host}:${s.port}`} className="hover:bg-surface-muted">
                          <TableCell columnId="host" className="font-mono text-sm">{s.host}</TableCell>
                          <TableCell columnId="port" className="font-mono text-sm text-content">{s.port}</TableCell>
                          <TableCell columnId="service">
                            <div className="flex items-center gap-2 min-w-0">
                              <ServiceIconCell s={s} />
                              <Badge variant="outline" className="font-normal text-content bg-surface truncate">
                                {servicePill(s)}
                              </Badge>
                            </div>
                          </TableCell>
                          <TableCell columnId="tls">
                             {s.tls ? (
                              <Badge variant="secondary" className="text-xs bg-cta/10 text-cta border-cta/20 hover:bg-cta/20">
                                TLS
                              </Badge>
                            ) : (
                              <span className="text-content-muted">-</span>
                            )}
                          </TableCell>
                          <TableCell columnId="details" className="text-sm">
                            <div className="space-y-1 min-w-0">
                              {hints.length === 0 ? (
                                <span className="text-content-muted text-xs">-</span>
                              ) : (
                                hints.map(([k, v]) => (
                                  <div key={k} className="text-xs text-content flex gap-2 min-w-0">
                                    <span className="text-content-muted font-medium shrink-0">{k}:</span>
                                    <span className="truncate" title={v}>{v}</span>
                                  </div>
                                ))
                              )}
                            </div>
                          </TableCell>
                          <TableCell columnId="actions" className="align-middle">
                            <div className="flex items-center justify-end whitespace-nowrap">
                              {match ? (
                                <LinkedServiceActions
                                  linkedCount={linkedDbCount}
                                  onView={() =>
                                    router.push(
                                      `/datasources/${encodeURIComponent(match.namespace)}/${encodeURIComponent(match.name)}`
                                    )
                                  }
                                  canAppend={canAppend}
                                  onAppend={() => void openAppendFromService(s, match)}
                                  isAppendLoading={isAppendLoading}
                                />
                              ) : canCreate ? (
                                <RbacButton
                                  variant="default"
                                  size="sm"
                                  onClick={() => openCreateFromService(s)}
                                  className="h-8 bg-btn-primary hover:bg-btn-primary-hover text-content-inverse"
                                  requiredPermission="descriptor:create"
                                >
                                  创建数据源
                                </RbacButton>
                              ) : (
                                <span className="text-xs text-content-muted">暂不支持</span>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      )
                    })
                  )}
                </TableBody>
              </Table>
             </TableWrapper>
            </section>
          </div>
        )}
      </div>

      <AlertDialog open={isDeleteOpen} onOpenChange={setIsDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除？</AlertDialogTitle>
            <AlertDialogDescription>删除后将无法恢复。该操作只删除扫描记录，不影响目标资产。</AlertDialogDescription>
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

      <CreateDataSourceDialog
        open={isCreateOpen}
        onOpenChange={(open) => {
          setIsCreateOpen(open)
          if (!open) setAppendContext(null)
        }}
        onSubmit={handleCreate}
        initialValues={createInitial ?? undefined}
        mode={appendContext ? "append" : "create"}
        lockedDatabases={appendContext?.lockedDatabases ?? []}
        retainedCredentials={appendContext?.retainedCredentials}
        title={
          appendContext ? "从扫描结果继续关联数据库" : "从扫描结果创建数据源"
        }
      />
    </div>
  )
}

"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"
import { useParams, useRouter } from "next/navigation"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { listDescriptorsAll } from "@/lib/descriptors-api"
import type { DataDescriptorResponse, DataSourceResponse } from "@/lib/api-types"
import { RbacButton, RbacWrapper } from "@/components/rbac"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
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
  Save, 
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
import { deleteDiscoveryScan, getDiscoveryScan, updateDiscoveryScan } from "@/lib/discovery"
import { CreateDataSourceDialog, type DataSourceFormValues } from "@/components/data-source-forms"
import { cn } from "@/lib/utils"
import { BrandIcon } from "@/components/brand-icon"

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

// Helper to normalize strings for comparison
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

// Helper to generate a unique connection identity string
// Format: "type://host:port"
const getConnectionIdentity = (type: string, host: string, port: string | number) => {
  let t = normalize(type)
  // Alias mappings can be added here if needed
  if (t === 'mariadb') t = 'mysql' 
  
  const h = normalize(host)
  const p = String(port).trim()
  
  return `${t}://${h}:${p}`
}

interface DataSourceRef {
  name: string
  namespace: string
  type: string
  host: string
  port: string
}

export default function InfraDiscoveryDetailPage() {
  const router = useRouter()
  const params = useParams<{ id: string }>()
  const id = decodeURIComponent(params?.id || "")

  const [job, setJob] = useState<DiscoveryJobResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isPolling, setIsPolling] = useState(false)
  const pollTimer = useRef<number | null>(null)

  const [existingDataSources, setExistingDataSources] = useState<DataSourceRef[]>([])

  const fetchExistingDataSources = async () => {
    try {
      const { items } = await listDescriptorsAll({ limit: 1000 })
      // A single DataDescriptor can fan out into N DataSources (one per database
      // for structured-mysql / structured-postgres). For matching against
      // discovered services we treat each underlying source as an independent
      // connection identity, otherwise multi-DB descriptors would only match
      // the first database.
      const parsed: DataSourceRef[] = items.flatMap((item: DataDescriptorResponse) => {
        const sources = item.sources ?? []
        return sources
          .map((s: DataSourceResponse) => {
            const meta = s.metadata ?? {}
            const host = meta.host
            const port = meta.port
            if (!host || !port) return null
            return {
              name: item.name,
              namespace: item.namespace ?? "default",
              type: s.type ?? "",
              host: String(host),
              port: String(port),
            } satisfies DataSourceRef
          })
          .filter((r): r is DataSourceRef => r != null)
      })
      // De-dup by (namespace, name, identity) so the same descriptor with N
      // databases on the same host:port doesn't show up N times in match results.
      const seen = new Set<string>()
      const unique: DataSourceRef[] = []
      for (const r of parsed) {
        const key = `${r.namespace}/${r.name}|${getConnectionIdentity(r.type, r.host, r.port)}`
        if (seen.has(key)) continue
        seen.add(key)
        unique.push(r)
      }
      setExistingDataSources(unique)
    } catch (e) {
      console.error("Failed to fetch existing data sources", e)
    }
  }

  useEffect(() => {
    void fetchExistingDataSources()
  }, [])

  const [nameDraft, setNameDraft] = useState("")
  const [isSavingName, setIsSavingName] = useState(false)

  const [isDeleteOpen, setIsDeleteOpen] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [createInitial, setCreateInitial] = useState<Partial<DataSourceFormValues> | null>(null)

  const services = useMemo(() => {
    const items = job?.services || []
    return [...items].sort((a, b) => (a.port ?? 0) - (b.port ?? 0))
  }, [job?.services])

  const detectCreateType = (s: DiscoveredService): "mysql" | "postgres" | "minio" | "coderepo" | null => {
    if (s.serviceType === "mysql") return "mysql"
    if (s.serviceType === "postgres") return "postgres"
    if ((s.product || "").toLowerCase().includes("minio")) return "minio"
    // Heuristic: in sandbox, GitLab CE (code repo) is exposed on 8929 and often detected as generic HTTP.
    if (normalize(s.serviceType) === "http" && Number(s.port) === 8929) return "coderepo"
    return null
  }

  const findMatchingDataSource = (s: DiscoveredService) => {
    // 1. Determine service type from discovery result
    let type = normalize(s.serviceType)
    const product = normalize(s.product)
    
    // Heuristic: MinIO often appears as generic HTTP but has 'minio' in product string
    if (product.includes("minio")) {
      type = "minio"
    }

    const targetIdentity = getConnectionIdentity(type, s.host, s.port)

    return existingDataSources.find(ds => {
      const dsIdentity = getConnectionIdentity(ds.type, ds.host, ds.port)
      return dsIdentity === targetIdentity
    })
  }

  const openCreateFromService = (s: DiscoveredService) => {
    const t = detectCreateType(s)
    if (!t) {
      toast.error("该服务类型暂不支持一键创建数据源")
      return
    }
    const safeName = `${t}-${s.host}-${s.port}`
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, "-")
      .replace(/-+/g, "-")
      .slice(0, 63)
    if (t === "coderepo") {
      const baseUrl = `http://${s.host}:${String(s.port).trim().replace(/^:/, "")}`
      setCreateInitial({
        name: safeName,
        namespace: "default",
        type: "coderepo",
        // Best-effort defaults; user can refine to /owner/repo(.git)
        codeRepoType: "gitlab",
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

  const handleCreate = async (data: DataSourceFormValues & { enableCodeRepo?: boolean }) => {
    const namespace = String(data.namespace || "default").trim() || "default"
    const t = String(data.type || "").trim()
    const isStructuredDB = t === "mysql" || t === "postgres"

    const promptsName = String(data.promptsConfigMapName || "").trim()
    const hasPrompts = Boolean(promptsName)

    const repoType = String(data.codeRepoType || "").trim()
    const repoPath = String(data.codeRepoPath || "").trim()
    const repoBranch = String(data.codeRepoBranch || "").trim()
    const repoToken = String(data.codeRepoToken || "").trim()

    // Payload normalization:
    // - structured DBs: sources[].type = mysql/postgres (+ optional source.codeRepo)
    // - object store / fileserver: sources[].type = minio/fileserver
    // - code repo: descriptorType = "code", sources[].type = github/gitee/...（execution-engine 认 descriptorType === "code"）
    const isCodeRepo = t === "coderepo"
    const descriptorType = isCodeRepo ? "code" : isStructuredDB ? `structured-${t}` : "unstructured"

    const name = String(data.name || "").trim()

    if (isCodeRepo) {
      const sourceType = repoType || "github"
      const metadata: Record<string, string> = {
        codeRepoPath: repoPath,
        codeRepoBranch: repoBranch || "main",
        codeRepoToken: repoToken,
      }
      const payload = {
        name,
        namespace,
        descriptorType,
        sources: [
          {
            name: name + "-source",
            type: sourceType,
            metadata,
            ...(hasPrompts ? { prompts: { configMapName: promptsName } } : {}),
            extract: { tables: [] },
            processing: { cleaning: [] },
          },
        ],
      }
      await api.post(`/namespaces/${namespace}/descriptors`, payload)
      toast.success("数据源创建成功")
      setIsCreateOpen(false)
      return
    }

    const hasCodeRepo =
      Boolean(data.enableCodeRepo) && Boolean(repoType || repoPath || repoBranch || repoToken)

    const baseMetadata: Record<string, string> = {
      host: String(data.host ?? ""),
      port: String(data.port ?? ""),
    }
    if (t === "minio") {
      baseMetadata.access_key = String(data.accessKey ?? "")
      baseMetadata.secret_key = String(data.secretKey ?? "")
      baseMetadata.bucket = String(data.bucket ?? "")
    } else if (t === "fileserver") {
      if (data.path) baseMetadata.path = String(data.path)
    }

    const extractFiles = String(data.extractFiles ?? "")
      .split(/\r?\n|,/g)
      .map((s) => s.trim())
      .filter(Boolean)

    const buildSource = (sourceName: string, metadata: Record<string, string>) => ({
      name: sourceName,
      type: t,
      metadata,
      ...(hasPrompts ? { prompts: { configMapName: promptsName } } : {}),
      ...(hasCodeRepo
        ? {
            codeRepo: {
              codeRepoType: repoType,
              codeRepoPath: repoPath,
              codeRepoBranch: repoBranch,
              codeRepoToken: repoToken,
            },
          }
        : {}),
      extract:
        t === "minio" || t === "fileserver"
          ? { files: extractFiles }
          : { tables: [] },
      processing: { cleaning: [] },
    })

    // Fan-out for structured DBs: one logical DataSource per selected database,
    // sharing the same host/port credentials. Other types keep 1:1 mapping.
    let sources: ReturnType<typeof buildSource>[]
    if (isStructuredDB) {
      const dbs = (data.databases ?? []).map((s) => s.trim()).filter(Boolean)
      if (dbs.length === 0) {
        toast.error("请至少选择一个数据库")
        return
      }
      sources = dbs.map((db) => {
        const suffix = db
          .toLowerCase()
          .replace(/[^a-z0-9-]/g, "-")
          .replace(/-+/g, "-")
          .replace(/^-+|-+$/g, "")
          .slice(0, 40) || "db"
        return buildSource(`${name}-${suffix}`, {
          ...baseMetadata,
          user: String(data.user ?? ""),
          password: String(data.password ?? ""),
          database: db,
        })
      })
    } else {
      sources = [buildSource(`${name}-source`, baseMetadata)]
    }

    const payload = {
      name,
      namespace,
      descriptorType,
      sources,
    }

    await api.post(`/namespaces/${namespace}/descriptors`, payload)
    toast.success("数据源创建成功")
    setIsCreateOpen(false)
  }

  const stopPolling = () => {
    if (pollTimer.current) {
      window.clearInterval(pollTimer.current)
      pollTimer.current = null
    }
    setIsPolling(false)
  }

  const fetchJob = async () => {
    if (!id) return null
    setIsLoading(true)
    try {
      const next = await getDiscoveryScan(id)
      setJob(next)
      if (next.status === "SUCCEEDED" || next.status === "FAILED") {
        stopPolling()
      }
      return next
    } catch (err) {
      console.error("Fetch discovery scan failed", err)
      toast.error("加载扫描详情失败")
      return null
    } finally {
      setIsLoading(false)
    }
  }

  const startPolling = () => {
    stopPolling()
    setIsPolling(true)
    pollTimer.current = window.setInterval(() => {
      fetchJob().catch(() => {
        // ignore transient
      })
    }, 1200)
  }

  useEffect(() => {
    void (async () => {
      const next = await fetchJob()
      if (next && (next.status === "PENDING" || next.status === "RUNNING")) {
        startPolling()
      }
    })()
    return () => stopPolling()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

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
             <Button variant="outline" onClick={() => void fetchJob()} disabled={isLoading} className="bg-surface hover:bg-surface-muted">
              <RefreshCw className={cn("w-4 h-4 mr-2", (isPolling || isLoading) && "animate-spin")} />
              刷新
            </Button>
            <RbacWrapper requiredRole="admin">
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
             
             <div className="bg-surface rounded-lg border border-line shadow-sm overflow-hidden">
             <Table>
                <TableHeader>
                  <TableRow className="bg-surface-muted/50">
                    <TableHead className="w-[180px]">地址</TableHead>
                    <TableHead className="w-[100px]">端口</TableHead>
                    <TableHead className="w-[200px]">服务识别</TableHead>
                    <TableHead className="w-[100px]">TLS</TableHead>
                    <TableHead>详细信息</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {services.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="h-32 text-center text-sm text-content-muted">
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
                      const hints = s.metadata ? Object.entries(s.metadata).slice(0, 3) : []
                      const canCreate = !!detectCreateType(s)
                      return (
                        <TableRow key={`${s.host}:${s.port}`} className="hover:bg-surface-muted">
                          <TableCell className="font-mono text-sm">{s.host}</TableCell>
                          <TableCell className="font-mono text-sm text-content">{s.port}</TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2 min-w-0">
                              <ServiceIconCell s={s} />
                              <Badge variant="outline" className="font-normal text-content bg-surface truncate">
                                {servicePill(s)}
                              </Badge>
                            </div>
                          </TableCell>
                          <TableCell>
                             {s.tls ? (
                              <Badge variant="secondary" className="text-xs bg-cta/10 text-cta border-cta/20 hover:bg-cta/20">
                                TLS
                              </Badge>
                            ) : (
                              <span className="text-content-muted">-</span>
                            )}
                          </TableCell>
                          <TableCell className="text-sm">
                             <div className="flex items-start justify-between gap-4">
                                <div className="space-y-1 pt-1">
                                  {hints.length === 0 ? (
                                    <span className="text-content-muted text-xs">-</span>
                                  ) : (
                                    hints.map(([k, v]) => (
                                      <div key={k} className="text-xs text-content flex gap-2">
                                        <span className="text-content-muted font-medium shrink-0">{k}:</span> 
                                        <span className="truncate max-w-[200px]" title={String(v)}>{String(v)}</span>
                                      </div>
                                    ))
                                  )}
                                </div>
                                {(() => {
                                  const match = findMatchingDataSource(s)
                                  if (match) {
                                    return (
                                      <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => router.push(`/datasources/${encodeURIComponent(match.namespace)}/${encodeURIComponent(match.name)}`)}
                                        className="shrink-0 h-8 text-cta border-cta/20 hover:bg-cta/10 cursor-pointer"
                                      >
                                        <LinkIcon className="w-3.5 h-3.5 mr-1.5" />
                                        已关联
                                      </Button>
                                    )
                                  }
                                  
                                  return (
                                    <RbacButton
                                      variant={canCreate ? "default" : "ghost"}
                                      size="sm"
                                      onClick={() => openCreateFromService(s)}
                                      disabled={!canCreate}
                                      className={cn(
                                        "shrink-0 h-8",
                                        canCreate ? "bg-[#1e293b] hover:bg-[#0f172a] text-content-inverse" : "text-content-muted"
                                      )}
                                      requiredRole="admin"
                                      fallbackTitle="无权限：仅管理员可创建数据源"
                                    >
                                      {canCreate ? "创建数据源" : "暂不支持"}
                                    </RbacButton>
                                  )
                                })()}
                             </div>
                          </TableCell>
                        </TableRow>
                      )
                    })
                  )}
                </TableBody>
              </Table>
             </div>
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
        onOpenChange={setIsCreateOpen}
        onSubmit={handleCreate}
        initialValues={createInitial ?? undefined}
        title="从扫描结果创建数据源"
      />
    </div>
  )
}

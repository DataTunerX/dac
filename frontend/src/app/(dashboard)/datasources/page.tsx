"use client"

import { useState, useEffect, useMemo } from "react"
import { useRouter } from "next/navigation"
import useSWR from "swr"
import { api } from "@/lib/api"
import { getDescriptor, listDescriptorsAll } from "@/lib/descriptors-api"
import { listAgentsAll } from "@/lib/agents-api"
import type { DataDescriptorListResponse } from "@/lib/api-types"
import { Button } from "@/components/ui/button"
import { RbacButton, RbacWrapper } from "@/components/rbac"
import { PaginationBar } from "@/components/pagination-bar"
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Plus, Eye, Loader2, RefreshCw, Trash2, Box } from "lucide-react"
import { CreateDataSourceDialog } from "@/components/data-source-forms"
import { toast } from "sonner"
import { BrandIcon } from "@/components/brand-icon"

// --- Types ---
interface DataSource {
  id: string; 
  name: string;
  namespace: string;
  type: string;
  sourceType?: "mysql" | "postgres" | "git" | "minio" | "generic";
  status: string;
  isDeleting?: boolean;
  lastUpdated: string;
  raw: unknown;
}

interface CreateDataSourcePayload {
    namespace: string;
    name: string;
    type: string;
    host?: string;
    port?: string;
    user?: string;
    password?: string;
    database?: string;
    accessKey?: string;
    secretKey?: string;
    bucket?: string;
    path?: string;
    extractFiles?: string;
    promptsConfigMapName?: string;
    enableCodeRepo?: boolean;
    codeRepoType?: string;
    codeRepoPath?: string;
    codeRepoBranch?: string;
    codeRepoToken?: string;
}

type DependentResource = {
  kind: string
  name: string
  namespace: string
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return Boolean(v) && typeof v === "object" && !Array.isArray(v)
}

function normalizeSourceType(descriptorType: string, sourceType: string): "mysql" | "postgres" | "git" | "minio" | "generic" {
  const dt = String(descriptorType || "").trim().toLowerCase()
  const st = String(sourceType || "").trim().toLowerCase()

  if (dt === "structured-mysql" || st === "mysql") return "mysql"
  if (dt === "structured-postgres" || st === "postgres") return "postgres"
  if (dt === "code" || st === "github" || st === "gitee" || st === "gitea" || st === "gitlab" || st === "git") return "git"
  if (st === "minio") return "minio"
  return "generic"
}

function SourceIcon({ kind }: { kind: ReturnType<typeof normalizeSourceType> }) {
  if (kind === "git") return <BrandIcon slug="git" size={16} title="Git" color="#0f172a" />
  if (kind === "minio") return <BrandIcon slug="minio" size={16} />
  if (kind === "generic") return <Box className="w-4 h-4" />
  if (kind === "mysql") return <BrandIcon slug="mysql" size={16} />
  return <BrandIcon slug="postgresql" size={16} />
}

export default function DataSourcesPage() {
  const router = useRouter()
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  // Delete + dependency check state (same pattern as 配置管理)
  const [deleteTarget, setDeleteTarget] = useState<{ namespace: string; name: string } | null>(null)
  const [dependentResources, setDependentResources] = useState<DependentResource[]>([])
  const [showDependencyDialog, setShowDependencyDialog] = useState(false)
  const [checkingDependency, setCheckingDependency] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [deletingKeys, setDeletingKeys] = useState<Set<string>>(new Set())

  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(1)

  const descriptorsKey = useMemo(
    () => ["descriptors", page, pageSize] as const,
    [page, pageSize]
  )
  const { data: descriptorsData, error: descriptorsError, isLoading, mutate: mutateDescriptors } = useSWR<DataDescriptorListResponse>(
    descriptorsKey,
    async ([, p, ps]: readonly [string, number, number]) =>
      listDescriptorsAll({ offset: (p - 1) * ps, limit: ps })
  )

  const { dataSources: adaptedList, totalCount: rawTotal } = useMemo(() => {
    const items = descriptorsData?.items ?? []
    const total = descriptorsData?.totalCount ?? 0
    const adapted = items.map((item) => {
      const descriptorType = item.descriptor_type ?? ""
      const sources = item.sources ?? []
      const first = sources[0]
      const sourceType = first?.type ?? ""
      const iconKind = normalizeSourceType(descriptorType, sourceType)
      const overallPhase = item.overall_phase ?? "NotReady"
      const updatedAt = item.updated_at ?? ""
      return {
        id: item.name,
        name: item.name,
        namespace: item.namespace ?? "default",
        type: descriptorType.replace("structured-", "") || "unknown",
        sourceType: iconKind,
        status: (item.deleting || item.deletion_timestamp) ? "Deleting" : overallPhase,
        isDeleting: Boolean(item.deleting || item.deletion_timestamp),
        lastUpdated: updatedAt ? new Date(updatedAt).toLocaleString() : "-",
        raw: item,
      } as DataSource
    })
    return { dataSources: adapted, totalCount: total }
  }, [descriptorsData])

  const dataSources = adaptedList
  const totalCount = Number.isFinite(rawTotal) && rawTotal >= 0 ? rawTotal : dataSources.length

  useEffect(() => {
    if (descriptorsError) toast.error("获取数据源列表失败")
  }, [descriptorsError])

  const fetchData = () => mutateDescriptors()

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totalPages])

  const checkDependencies = async (namespace: string, name: string) => {
    setCheckingDependency(true)
    try {
      const deps: DependentResource[] = []

      // 1) Best-effort: backend may expose lineage via consumed_by on descriptor detail.
      try {
        const desc = await getDescriptor(namespace, name)
        const consumed = desc.consumed_by ?? []
        for (const c of consumed) {
          const depName = c.name
          if (!depName) continue
          deps.push({
            kind: "dac",
            name: depName,
            namespace: c.namespace ?? "default",
          })
        }
      } catch {
        // ignore: some backends may not support consumed_by
      }

      // 2) Check agents referencing this DD: dataPolicy.sourceNameSelector, activeDataDescriptors.
      try {
        const { items } = await listAgentsAll()
        for (const a of items) {
          const an = a.name ?? ""
          const ans = a.namespace ?? "default"
          if (!an) continue
          let hit = false
          const sel = a.dataPolicy?.sourceNameSelector ?? []
          if (sel.some((x) => x === name)) hit = true
          const ads = a.activeDataDescriptors ?? []
          if (ads.some((x) => x.name === name && (x.namespace ?? "default") === namespace)) hit = true
          if (hit) deps.push({ kind: "agent", name: an, namespace: ans })
        }
      } catch {
        // ignore: if agents API not available, we still rely on consumed_by
      }

      // Deduplicate
      const uniq = new Map<string, DependentResource>()
      for (const d of deps) {
        const k = `${d.kind}/${d.namespace}/${d.name}`
        if (!uniq.has(k)) uniq.set(k, d)
      }
      return Array.from(uniq.values())
    } catch (err) {
      console.error("check dd dependencies failed", err)
      toast.error("检查依赖关系失败")
      return []
    } finally {
      setCheckingDependency(false)
    }
  }

  const handleDeleteClick = async (namespace: string, name: string) => {
    const deps = await checkDependencies(namespace, name)
    if (deps.length > 0) {
      setDependentResources(deps)
      setShowDependencyDialog(true)
      return
    }
    setDeleteTarget({ namespace, name })
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setIsDeleting(true)
    try {
      const key = `${deleteTarget.namespace}/${deleteTarget.name}`
      setDeletingKeys((prev) => new Set(prev).add(key))
      await api.delete(`/namespaces/${encodeURIComponent(deleteTarget.namespace)}/descriptors/${encodeURIComponent(deleteTarget.name)}`)
      toast.success("数据源已删除")
      setDeleteTarget(null)

      // If we deleted the last item on the page, go back one page.
      const remaining = Math.max(0, totalCount - 1)
      const nextTotalPages = Math.max(1, Math.ceil(remaining / pageSize))
      if (page > nextTotalPages) setPage(nextTotalPages)
      await fetchData()
    } catch (err) {
      console.error("delete datasource failed", err)
      const e = err as { response?: { data?: { message?: string } } }
      toast.error(e.response?.data?.message || "删除失败")
    } finally {
      setIsDeleting(false)
    }
  }

  const handleCreate = async (data: CreateDataSourcePayload) => {
    try {
      const namespace = data.namespace?.trim() || "default"
      const promptsName = data.promptsConfigMapName?.trim() || ""
      const hasPrompts = Boolean(promptsName)

      const repoType = data.codeRepoType?.trim() || ""
      const repoPath = data.codeRepoPath?.trim() || ""
      const repoBranch = data.codeRepoBranch?.trim() || ""
      const repoToken = data.codeRepoToken?.trim() || ""
      const t = String(data.type || "").trim()
      const isCodeRepo = t === "coderepo"
      const hasCodeRepo =
        isCodeRepo || (Boolean(data.enableCodeRepo) && Boolean(repoType || repoPath || repoBranch || repoToken))

      const isStructuredDB = t === "mysql" || t === "postgres"
      // execution-engine 认 descriptorType === "code" 时走 code-agent 与 code 配置；代码类型统一用 code
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
          name: data.name,
          namespace,
          descriptorType,
          sources: [
            {
              name: data.name + "-source",
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
        fetchData()
        return
      }

      const metadata: Record<string, string> = {
        host: String(data.host ?? ""),
        port: String(data.port ?? ""),
      }
      if (t === "mysql" || t === "postgres") {
        metadata.user = String(data.user ?? "")
        metadata.password = String(data.password ?? "")
        metadata.database = String(data.database ?? "")
      } else if (t === "minio") {
        metadata.access_key = String(data.accessKey ?? "")
        metadata.secret_key = String(data.secretKey ?? "")
        metadata.bucket = String(data.bucket ?? "")
      } else if (t === "fileserver") {
        if (data.path) metadata.path = String(data.path)
      }

      const extractFiles = String(data.extractFiles ?? "")
        .split(/\r?\n|,/g)
        .map((s) => s.trim())
        .filter(Boolean)

      const payload = {
        name,
        namespace,
        descriptorType,
        sources: [
            {
                name: data.name + "-source",
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
                processing: { cleaning: [] }
            }
        ]
      }
      
      await api.post(`/namespaces/${namespace}/descriptors`, payload)
      toast.success("数据源创建成功")
      fetchData() 
    } catch (err) {
        console.error("Failed to create", err)
        const e = err as { response?: { data?: { message?: string } } }
        toast.error(e.response?.data?.message || "创建失败，请检查输入或日志")
        throw err
    }
  }

  const navigateToDetail = (ds: DataSource) => {
    router.push(`/datasources/${encodeURIComponent(ds.namespace)}/${encodeURIComponent(ds.name)}`)
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
      {/* Breadcrumb + actions (in-content, no extra bar) */}
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium text-content">
          <span className="text-content font-semibold">数据管理</span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" onClick={fetchData} disabled={isLoading} aria-label="刷新">
            <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
          </Button>
          <RbacButton 
            className="flex items-center gap-2" 
            onClick={() => setIsCreateOpen(true)}
            requiredRole="admin"
            fallbackTitle="无权限：仅管理员可创建"
          >
            <Plus className="w-4 h-4" />
            新建数据源
          </RbacButton>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-line bg-surface overflow-hidden">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-surface-muted">
                <TableHead className="whitespace-nowrap">名称</TableHead>
                <TableHead className="whitespace-nowrap">命名空间</TableHead>
                <TableHead className="whitespace-nowrap">类型</TableHead>
                <TableHead className="whitespace-nowrap">状态</TableHead>
                <TableHead className="whitespace-nowrap">最后更新</TableHead>
                <TableHead className="text-right whitespace-nowrap">操作</TableHead>
              </TableRow>
            </TableHeader>
          <TableBody>
            {isLoading && dataSources.length === 0 ? (
             <TableRow>
                <TableCell colSpan={6} className="h-24 text-center">
                    <div className="flex items-center justify-center gap-2 text-muted-foreground">
                        <Loader2 className="w-4 h-4 animate-spin" /> 加载中…
                    </div>
                </TableCell>
            </TableRow>
          ) : dataSources.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-content-muted py-10">
                暂无数据源
                <RbacWrapper requiredRole="admin">
                  <Button
                    variant="link"
                    className="ml-2 text-cta cursor-pointer"
                    onClick={() => setIsCreateOpen(true)}
                  >
                    去创建
                  </Button>
                </RbacWrapper>
              </TableCell>
            </TableRow>
          ) : (
            dataSources.map((ds) => (
              <TableRow
                key={ds.id}
                className={[
                  (ds.isDeleting || deletingKeys.has(`${ds.namespace}/${ds.name}`))
                    ? "opacity-60 cursor-not-allowed"
                    : "cursor-pointer hover:bg-surface-muted",
                ].join(" ")}
                onClick={() => {
                  if (ds.isDeleting || deletingKeys.has(`${ds.namespace}/${ds.name}`)) return
                  navigateToDetail(ds)
                }}
              >
                <TableCell className="font-medium flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-cta/10 flex items-center justify-center text-cta">
                    <SourceIcon kind={ds.sourceType ?? "generic"} />
                  </div>
                  {ds.name}
                </TableCell>
                <TableCell className="text-content-muted">{ds.namespace}</TableCell>
                <TableCell className="capitalize">{ds.type}</TableCell>
                <TableCell>
                  {(() => {
                    const raw = String(ds.status ?? "").trim()
                    // Normalize empty / "-" / "Unknown" into NotReady for display.
                    const key =
                      raw === "" || raw === "-" || raw.toLowerCase() === "unknown"
                        ? "NotReady"
                        : raw.replace(/\s+/g, "")
                    const label =
                      key === "Deleting"
                        ? "删除中"
                        : key === "NotReady"
                          ? "Not Ready"
                          : raw
                    const cls =
                      key === "Deleting"
                        ? "bg-orange-100 text-orange-800"
                        : key === "Ready" || key === "Active"
                        ? "bg-green-100 text-green-800"
                        : key === "Syncing"
                          ? "bg-cta/10 text-cta"
                          : key === "NotReady"
                            ? "bg-red-100 text-red-800"
                            : "bg-surface-muted text-content"
                    return (
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${cls}`}>
                        {label}
                      </span>
                    )
                  })()}
                </TableCell>
                <TableCell>{ds.lastUpdated}</TableCell>
                <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center justify-end gap-2">
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={ds.isDeleting || deletingKeys.has(`${ds.namespace}/${ds.name}`)}
                      onClick={() => navigateToDetail(ds)}
                      title={ds.isDeleting || deletingKeys.has(`${ds.namespace}/${ds.name}`) ? "删除中" : "查看"}
                      aria-label={ds.isDeleting || deletingKeys.has(`${ds.namespace}/${ds.name}`) ? "删除中" : "查看"}
                    >
                        <Eye className="w-4 h-4 text-content-muted" />
                    </Button>
                    <RbacWrapper requiredRole="admin">
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={checkingDependency || ds.isDeleting || deletingKeys.has(`${ds.namespace}/${ds.name}`)}
                        onClick={() => void handleDeleteClick(ds.namespace, ds.name)}
                        title="删除"
                        aria-label="删除"
                        className="text-red-600 hover:text-red-700"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </RbacWrapper>
                  </div>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
        </Table>
        </div>
      </div>

      <PaginationBar
        total={totalCount}
        page={page}
        pageSize={pageSize}
        pageSizeOptions={[10, 20, 50, 100]}
        isLoading={isLoading}
        onPageChange={setPage}
        onPageSizeChange={(n) => {
          setPageSize(n)
          setPage(1)
        }}
      />

      <CreateDataSourceDialog 
        open={isCreateOpen} 
        onOpenChange={setIsCreateOpen} 
        onSubmit={handleCreate} 
      />

      {/* 依赖关系提示弹窗（抄配置管理的交互） */}
      <AlertDialog open={showDependencyDialog} onOpenChange={setShowDependencyDialog}>
        <AlertDialogContent className="w-[min(96vw,56rem)] max-w-4xl">
          <AlertDialogHeader>
            <AlertDialogTitle>无法删除 - 存在依赖关系</AlertDialogTitle>
            <AlertDialogDescription>
              该数据源正在被以下 {dependentResources.length} 个 DAC 资源使用，无法删除。
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="mt-4 space-y-3 px-6">
            <div className="max-h-[320px] w-full overflow-auto rounded-md border border-line">
              <Table className="w-full table-fixed">
                <TableHeader>
                  <TableRow className="bg-surface-muted">
                    <TableHead className="w-auto">资源</TableHead>
                    <TableHead className="w-28">命名空间</TableHead>
                    <TableHead className="w-28 text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dependentResources.map((r, idx) => (
                    <TableRow key={`${r.kind}/${r.namespace}/${r.name}/${idx}`}>
                      <TableCell className="font-medium whitespace-normal break-all">
                        {r.kind} / {r.name}
                      </TableCell>
                      <TableCell className="text-content-muted">{r.namespace}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setShowDependencyDialog(false)
                            if (r.kind === "agent") {
                              router.push(`/agents/${encodeURIComponent(r.namespace)}/${encodeURIComponent(r.name)}`)
                            } else {
                              router.push(`/datasources/${encodeURIComponent(r.namespace)}/${encodeURIComponent(r.name)}`)
                            }
                          }}
                          className="text-cta hover:text-cta/90 whitespace-nowrap cursor-pointer"
                        >
                          查看详情 →
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="text-sm text-content">请先解除这些资源对该数据源的依赖，然后再删除。</div>
          </div>

          <AlertDialogFooter>
            <AlertDialogAction onClick={() => setShowDependencyDialog(false)}>知道了</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 删除确认弹窗 */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除数据源？</AlertDialogTitle>
            <AlertDialogDescription>
              此操作将永久删除该数据源（{deleteTarget?.namespace}/{deleteTarget?.name}）。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-red-600 hover:bg-red-700" disabled={isDeleting}>
              {isDeleting ? "删除中..." : "确认删除"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

"use client"

import Link from "next/link"
import { useCallback, useEffect, useMemo, useState } from "react"
import {
  getSystemConfiguration,
  listSystemConfigurationVersions,
  listSystemConfigurations,
  updateSystemConfiguration,
  type SystemConfigName,
} from "@/lib/system-config-api"
import { listConfigMaps } from "@/lib/configmaps-api"
import type {
  SystemConfigurationResponse,
  SystemConfigurationVersionResponse,
} from "@/lib/api-types"
import {
  emptyDataForConfig,
  isLlmConfigMapFieldKey,
  isReadonlySystemConfigKey,
  mergeFormData,
  SYSTEM_CONFIG_EXCLUDED_LLM_CONFIGMAPS,
  SYSTEM_CONFIG_META,
  SYSTEM_CONFIG_NAMESPACE,
  SYSTEM_CONFIG_NAMES,
} from "@/lib/system-config-meta"
import { getUserRole } from "@/lib/auth"
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
import { RbacButton, RbacWrapper } from "@/components/rbac"
import {
  Dialog,
  DialogContent,
  DialogFooter,
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
import { TableWrapper } from "@/components/ui/table-wrapper"
import { PaginationBar } from "@/components/pagination-bar"
import { toast } from "sonner"
import { Box, History, Loader2, Pencil, RefreshCw, X } from "lucide-react"
import axios from "axios"
import { cn } from "@/lib/utils"

type DialogTab = "current" | "history"
type EditorMode = "view" | "edit" | "create"

function apiErrorMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const body = err.response?.data as { message?: string } | undefined
    if (body?.message) return body.message
  }
  return fallback
}

function formatVersionTime(version: string, createdAt?: string): string {
  if (createdAt) {
    const d = new Date(createdAt)
    if (Number.isFinite(d.getTime())) return d.toLocaleString()
  }
  if (/^\d{14}/.test(version)) {
    const y = version.slice(0, 4)
    const m = version.slice(4, 6)
    const day = version.slice(6, 8)
    const h = version.slice(8, 10)
    const min = version.slice(10, 12)
    const s = version.slice(12, 14)
    return `${y}-${m}-${day} ${h}:${min}:${s}`
  }
  return version
}

function ConfigFieldsReadonly({
  name,
  data,
}: {
  name: SystemConfigName
  data: Record<string, string>
}) {
  return (
    <>
      {SYSTEM_CONFIG_META[name].groups.map((group, gi) => (
        <div key={gi} className="rounded-lg border border-line bg-surface p-4 space-y-3">
          <div className="space-y-3">
            {group.keys.map((key) => (
              <div key={key} className="space-y-1">
                <Label className="font-mono text-xs text-content-muted">{key}</Label>
                <div className="text-sm font-mono text-content break-all rounded-md bg-surface-muted px-3 py-2 border border-line">
                  {data[key]?.trim() || <span className="text-content-muted">（空）</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </>
  )
}

function LlmConfigMapField({
  fieldKey,
  value,
  options,
  isLoading,
  loadError,
  disabled,
  onChange,
}: {
  fieldKey: string
  value: string
  options: string[]
  isLoading: boolean
  loadError: string | null
  disabled: boolean
  onChange: (v: string) => void
}) {
  const selectValue = value.trim() || undefined

  return (
    <div className="space-y-1.5">
      <Label htmlFor={`field-${fieldKey}`} className="font-mono text-xs">
        {fieldKey}
      </Label>
      <Select value={selectValue} onValueChange={onChange} disabled={disabled || isLoading}>
        <SelectTrigger id={`field-${fieldKey}`} className="font-mono text-sm">
          <SelectValue placeholder={isLoading ? "加载 ConfigMap 列表…" : "选择 LLM ConfigMap"} />
        </SelectTrigger>
        <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
          {loadError ? (
            <SelectItem value="__error__" disabled>
              {loadError}
            </SelectItem>
          ) : options.length === 0 ? (
            <SelectItem value="__empty__" disabled>
              命名空间 {SYSTEM_CONFIG_NAMESPACE} 下暂无 LLM ConfigMap
            </SelectItem>
          ) : (
            options.map((name) => (
              <SelectItem key={name} value={name} className="font-mono">
                {name}
              </SelectItem>
            ))
          )}
        </SelectContent>
      </Select>
      {!disabled && (
        <p className="text-xs text-content-muted">
          从命名空间{" "}
          <span className="font-mono text-content">{SYSTEM_CONFIG_NAMESPACE}</span> 的 LLM ConfigMap
          中选择；也可在{" "}
          <Link
            href={`/configmaps?namespace=${encodeURIComponent(SYSTEM_CONFIG_NAMESPACE)}&type=llm&create=1`}
            className="text-btn-primary hover:underline"
            target="_blank"
          >
            配置管理
          </Link>{" "}
          中新建。
        </p>
      )}
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

const TEMPLATE_LIST_COLUMNS = [
  { id: "name", size: 200 },
  { id: "namespace", size: 140 },
  { id: "status", size: 120 },
  { id: "updated", size: 180 },
  { id: "actions", size: 120 },
] as const

const TEMPLATE_HISTORY_COLUMNS = [
  { id: "archived", size: 180 },
  { id: "version", size: 220 },
  { id: "actions", size: 120 },
] as const

export function TemplateManagementPanel() {
  const [mounted, setMounted] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [items, setItems] = useState<SystemConfigurationResponse[]>([])

  const [dialogOpen, setDialogOpen] = useState(false)
  const [activeName, setActiveName] = useState<SystemConfigName | null>(null)
  const [editorMode, setEditorMode] = useState<EditorMode>("view")
  const [dialogTab, setDialogTab] = useState<DialogTab>("current")
  const [isDialogLoading, setIsDialogLoading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  const [exists, setExists] = useState(false)
  const [resourceVersion, setResourceVersion] = useState("")
  const [formData, setFormData] = useState<Record<string, string>>({})
  const [isViewOnly, setIsViewOnly] = useState(true)

  const [versions, setVersions] = useState<SystemConfigurationVersionResponse[]>([])
  const [versionTotal, setVersionTotal] = useState(0)
  const [versionPage, setVersionPage] = useState(1)
  const [versionPageSize, setVersionPageSize] = useState(10)
  const [isLoadingVersions, setIsLoadingVersions] = useState(false)
  const [viewingVersion, setViewingVersion] = useState<SystemConfigurationVersionResponse | null>(null)

  const [configNamespace, setConfigNamespace] = useState(SYSTEM_CONFIG_NAMESPACE)
  const [llmConfigMapOptions, setLlmConfigMapOptions] = useState<string[]>([])
  const [isLoadingLlmConfigMaps, setIsLoadingLlmConfigMaps] = useState(false)
  const [llmConfigMapsError, setLlmConfigMapsError] = useState<string | null>(null)

  const itemByName = useMemo(() => {
    const map = new Map<string, SystemConfigurationResponse>()
    for (const it of items) map.set(it.name, it)
    return map
  }, [items])

  useEffect(() => {
    setMounted(true)
    setIsViewOnly(getUserRole() !== "admin")
  }, [])

  const loadList = useCallback(async () => {
    setIsLoading(true)
    try {
      const data = await listSystemConfigurations()
      setItems(data.items ?? [])
    } catch (e) {
      console.error("list system configurations failed", e)
      toast.error("加载模版列表失败")
      setItems([])
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadList()
  }, [loadList])

  const loadLlmConfigMapOptions = useCallback(async () => {
    setIsLoadingLlmConfigMaps(true)
    setLlmConfigMapsError(null)
    try {
      const { items } = await listConfigMaps(SYSTEM_CONFIG_NAMESPACE, { type: "llm" })
      const names = (items ?? [])
        .map((item) => item.name)
        .filter((name): name is string => Boolean(name) && !SYSTEM_CONFIG_EXCLUDED_LLM_CONFIGMAPS.has(name))
        .sort((a, b) => a.localeCompare(b))
      setLlmConfigMapOptions(names)
    } catch (e) {
      console.error("load llm configmaps failed", e)
      setLlmConfigMapOptions([])
      setLlmConfigMapsError("LLM ConfigMap 列表加载失败")
    } finally {
      setIsLoadingLlmConfigMaps(false)
    }
  }, [])

  useEffect(() => {
    if (!dialogOpen) return
    void loadLlmConfigMapOptions()
  }, [dialogOpen, loadLlmConfigMapOptions])

  const llmSelectOptions = useMemo(() => {
    const names = new Set(llmConfigMapOptions)
    if (activeName) {
      for (const group of SYSTEM_CONFIG_META[activeName].groups) {
        for (const key of group.keys) {
          if (!isLlmConfigMapFieldKey(key)) continue
          const v = formData[key]?.trim()
          if (v) names.add(v)
        }
      }
    }
    return Array.from(names).sort((a, b) => a.localeCompare(b))
  }, [llmConfigMapOptions, activeName, formData])

  const loadVersions = useCallback(
    async (name: SystemConfigName, page: number, pageSize: number) => {
      setIsLoadingVersions(true)
      try {
        const data = await listSystemConfigurationVersions(name, {
          offset: (page - 1) * pageSize,
          limit: pageSize,
        })
        setVersions(data.items ?? [])
        setVersionTotal(data.totalCount ?? 0)
      } catch (e) {
        console.error("list versions failed", e)
        toast.error("加载历史模版失败")
        setVersions([])
        setVersionTotal(0)
      } finally {
        setIsLoadingVersions(false)
      }
    },
    []
  )

  const loadEditor = async (name: SystemConfigName, mode: EditorMode, tab: DialogTab = "current") => {
    setActiveName(name)
    setEditorMode(mode)
    setDialogTab(tab)
    setDialogOpen(true)
    setViewingVersion(null)
    setVersionPage(1)
    setIsDialogLoading(true)
    try {
      const cfg = await getSystemConfiguration(name)
      setExists(Boolean(cfg.exists))
      setResourceVersion(cfg.resourceVersion ?? "")
      setConfigNamespace(cfg.namespace?.trim() || SYSTEM_CONFIG_NAMESPACE)
      setFormData(mergeFormData(name, cfg.data))
      await loadVersions(name, 1, versionPageSize)
    } catch (e) {
      console.error("load template failed", e)
      toast.error("加载模版详情失败")
      setDialogOpen(false)
    } finally {
      setIsDialogLoading(false)
    }
  }

  const startCreate = async (name: SystemConfigName) => {
    setExists(false)
    setResourceVersion("")
    setFormData(emptyDataForConfig(name))
    setEditorMode("create")
    await loadEditor(name, "create", "current")
  }

  const closeDialog = () => {
    setDialogOpen(false)
    setActiveName(null)
    setViewingVersion(null)
    setDialogTab("current")
    setEditorMode("view")
  }

  const refreshDialog = async () => {
    if (!activeName) return
    setIsDialogLoading(true)
    try {
      const cfg = await getSystemConfiguration(activeName)
      setExists(Boolean(cfg.exists))
      setResourceVersion(cfg.resourceVersion ?? "")
      setConfigNamespace(cfg.namespace?.trim() || SYSTEM_CONFIG_NAMESPACE)
      setFormData(mergeFormData(activeName, cfg.data))
      if (dialogTab === "history") {
        await loadVersions(activeName, versionPage, versionPageSize)
      }
      toast.success("已刷新")
    } catch (e) {
      toast.error(apiErrorMessage(e, "刷新失败"))
    } finally {
      setIsDialogLoading(false)
    }
  }

  const handleSave = async () => {
    if (!activeName || isViewOnly || editorMode === "view") return

    const payload: Record<string, string> = { ...emptyDataForConfig(activeName) }
    for (const key of Object.keys(payload)) {
      payload[key] = (formData[key] ?? "").trim()
    }

    setIsSaving(true)
    try {
      const updated = await updateSystemConfiguration(activeName, {
        data: payload,
        ...(exists && resourceVersion ? { resourceVersion } : {}),
      })
      const wasCreate = editorMode === "create" || !exists
      toast.success(wasCreate ? "模版已创建并生效" : "已保存；上一版已移入历史模版")
      setExists(true)
      setEditorMode("edit")
      setResourceVersion(updated.resourceVersion ?? "")
      setFormData(mergeFormData(activeName, updated.data))
      await loadList()
      await loadVersions(activeName, 1, versionPageSize)
      setVersionPage(1)
    } catch (e) {
      console.error("save template failed", e)
      if (axios.isAxiosError(e) && e.response?.status === 409) {
        toast.error("模版已被他人修改，请刷新后重试")
      } else {
        toast.error(apiErrorMessage(e, "保存失败"))
      }
    } finally {
      setIsSaving(false)
    }
  }

  useEffect(() => {
    if (!dialogOpen || !activeName || dialogTab !== "history") return
    void loadVersions(activeName, versionPage, versionPageSize)
  }, [dialogOpen, activeName, dialogTab, versionPage, versionPageSize, loadVersions])

  const meta = activeName ? SYSTEM_CONFIG_META[activeName] : null
  const isFormReadonly = isViewOnly || editorMode === "view"
  const dialogTitle = !activeName
    ? "模版详情"
    : editorMode === "create"
      ? `创建 ${activeName}`
      : editorMode === "edit"
        ? `编辑 ${activeName}`
        : activeName

  if (!mounted) {
    return <PageSpinner />
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="text-sm font-medium text-content">
          <span className="text-content font-semibold">模版中心</span>
        </div>
        <Button
          variant="outline"
          size="icon"
          onClick={() => void loadList()}
          disabled={isLoading}
          title="刷新"
          aria-label="刷新"
        >
          <RefreshCw className={cn("w-4 h-4", isLoading && "animate-spin")} />
        </Button>
      </div>

      <TableWrapper>
        <Table storageKey="template-management-list" columns={[...TEMPLATE_LIST_COLUMNS]}>
          <TableHeader>
            <TableRow className="bg-surface-muted">
              <TableHead columnId="name">名称</TableHead>
              <TableHead columnId="namespace">命名空间</TableHead>
              <TableHead columnId="status">状态</TableHead>
              <TableHead columnId="updated">最近更新</TableHead>
              <TableHead columnId="actions" className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {SYSTEM_CONFIG_NAMES.map((name) => {
              const cfg = itemByName.get(name)
              const inUse = Boolean(cfg?.exists)
              return (
                <TableRow key={name} className="hover:bg-surface-muted">
                  <TableCell columnId="name" className="font-medium font-mono text-content">{name}</TableCell>
                  <TableCell columnId="namespace" className="font-mono text-sm text-content-muted">
                    {cfg?.namespace?.trim() || SYSTEM_CONFIG_NAMESPACE}
                  </TableCell>
                  <TableCell columnId="status">
                    {inUse ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 text-xs">
                        使用中
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-200 text-xs">
                        未创建
                      </span>
                    )}
                  </TableCell>
                  <TableCell columnId="updated" className="text-content-muted">
                    {cfg?.createdAt ? new Date(cfg.createdAt).toLocaleString() : "—"}
                  </TableCell>
                  <TableCell columnId="actions" className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      {inUse ? (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => void loadEditor(name, "view", "current")}
                          >
                            查看
                          </Button>
                          <RbacWrapper requiredRole="admin">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => void loadEditor(name, "edit", "current")}
                            >
                              <Pencil className="w-3.5 h-3.5 mr-1" />
                              编辑
                            </Button>
                          </RbacWrapper>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => void loadEditor(name, "view", "history")}
                          >
                            <History className="w-3.5 h-3.5 mr-1" />
                            历史
                          </Button>
                        </>
                      ) : (
                        <RbacButton
                          variant="ghost"
                          size="sm"
                          requiredRole="admin"
                          fallbackTitle="无权限"
                          onClick={() => void startCreate(name)}
                        >
                          创建
                        </RbacButton>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </TableWrapper>

      {/* 查看 / 编辑 / 历史 */}
      <Dialog open={dialogOpen} onOpenChange={(v) => (!v ? closeDialog() : setDialogOpen(true))}>
        <DialogContent className="sm:max-w-[760px] max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50 shrink-0">
            <div className="flex items-center justify-between gap-3">
              <div>
                <DialogTitle>{dialogTitle}</DialogTitle>
                {activeName && (
                  <p className="text-xs text-content-muted mt-1 font-mono">
                    namespace: {configNamespace}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => void refreshDialog()}
                  disabled={isDialogLoading}
                  title="刷新"
                  aria-label="刷新"
                >
                  <RefreshCw className={cn("w-4 h-4", isDialogLoading && "animate-spin")} />
                </Button>
                <Button variant="ghost" size="icon" className="h-8 w-8" onClick={closeDialog} aria-label="关闭">
                  <X className="w-4 h-4" />
                </Button>
              </div>
            </div>

            <div className="flex gap-2 mt-4">
              <Button
                type="button"
                size="sm"
                variant={dialogTab === "current" ? "default" : "outline"}
                className={dialogTab === "current" ? "bg-btn-primary" : ""}
                onClick={() => {
                  setDialogTab("current")
                  setViewingVersion(null)
                }}
              >
                <Box className="w-4 h-4 mr-1.5" />
                当前模版
              </Button>
              <Button
                type="button"
                size="sm"
                variant={dialogTab === "history" ? "default" : "outline"}
                className={dialogTab === "history" ? "bg-btn-primary" : ""}
                disabled={!exists}
                onClick={() => {
                  setDialogTab("history")
                  setViewingVersion(null)
                }}
              >
                <History className="w-4 h-4 mr-1.5" />
                历史模版
              </Button>
            </div>
          </DialogHeader>

          <div className="flex-1 min-h-0 overflow-y-auto px-6 py-6">
            {isDialogLoading ? (
              <PageSpinner />
            ) : dialogTab === "current" ? (
              <div className="space-y-4">
                {activeName &&
                  meta?.groups.map((group, gi) => (
                    <div key={gi} className="rounded-lg border border-line bg-surface p-4 space-y-4">
                      <div className="grid grid-cols-1 gap-4">
                        {group.keys.map((key) =>
                          isLlmConfigMapFieldKey(key) ? (
                            <LlmConfigMapField
                              key={key}
                              fieldKey={key}
                              value={formData[key] ?? ""}
                              options={llmSelectOptions}
                              isLoading={isLoadingLlmConfigMaps}
                              loadError={llmConfigMapsError}
                              disabled={isFormReadonly || isReadonlySystemConfigKey(key)}
                              onChange={(v) => setFormData((prev) => ({ ...prev, [key]: v }))}
                            />
                          ) : (
                            <div key={key} className="space-y-1.5">
                              <Label htmlFor={`field-${key}`} className="font-mono text-xs">
                                {key}
                              </Label>
                              <Input
                                id={`field-${key}`}
                                value={formData[key] ?? ""}
                                onChange={(e) =>
                                  setFormData((prev) => ({ ...prev, [key]: e.target.value }))
                                }
                                disabled={isFormReadonly || isReadonlySystemConfigKey(key)}
                                placeholder="registry/namespace/image:tag"
                                className="font-mono text-sm"
                              />
                            </div>
                          )
                        )}
                      </div>
                    </div>
                  ))}
              </div>
            ) : viewingVersion && activeName ? (
              <div className="space-y-4">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="text-sm font-medium text-content">历史模版快照</div>
                    <div className="text-xs text-content-muted font-mono mt-0.5">
                      {formatVersionTime(viewingVersion.version, viewingVersion.createdAt)}
                    </div>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => setViewingVersion(null)}>
                    返回列表
                  </Button>
                </div>
                <ConfigFieldsReadonly name={activeName} data={viewingVersion.data ?? {}} />
              </div>
            ) : (
              <div className="space-y-4">
                <TableWrapper>
                  <Table storageKey="template-history-list" columns={[...TEMPLATE_HISTORY_COLUMNS]}>
                    <TableHeader>
                      <TableRow className="bg-surface-muted">
                        <TableHead columnId="archived">归档时间</TableHead>
                        <TableHead columnId="version">版本 ID</TableHead>
                        <TableHead columnId="actions" className="text-right">操作</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {versions.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={3} className="text-center text-content-muted py-8">
                            {isLoadingVersions ? "加载中…" : "暂无历史模版（首次保存当前模版后产生）"}
                          </TableCell>
                        </TableRow>
                      ) : (
                        versions.map((v) => (
                          <TableRow key={v.version}>
                            <TableCell columnId="archived" className="text-content">
                              {formatVersionTime(v.version, v.createdAt)}
                            </TableCell>
                            <TableCell columnId="version" className="font-mono text-xs text-content-muted max-w-[200px] truncate">
                              {v.version}
                            </TableCell>
                            <TableCell columnId="actions" className="text-right">
                              <Button variant="ghost" size="sm" onClick={() => setViewingVersion(v)}>
                                查看
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </TableWrapper>
                <PaginationBar
                  total={versionTotal}
                  page={versionPage}
                  pageSize={versionPageSize}
                  pageSizeOptions={[10, 20, 50]}
                  isLoading={isLoadingVersions}
                  onPageChange={setVersionPage}
                  onPageSizeChange={(n) => {
                    setVersionPageSize(n)
                    setVersionPage(1)
                  }}
                />
              </div>
            )}
          </div>

          {dialogTab === "current" && !isFormReadonly && (
            <DialogFooter className="px-6 py-4 border-t border-line bg-surface-muted/50 shrink-0">
              <Button variant="outline" onClick={closeDialog}>
                取消
              </Button>
              <RbacButton requiredRole="admin" onClick={() => void handleSave()} disabled={isSaving || isDialogLoading}>
                {isSaving ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    保存中…
                  </>
                ) : editorMode === "create" || !exists ? (
                  "创建并生效"
                ) : (
                  "保存并归档旧版"
                )}
              </RbacButton>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

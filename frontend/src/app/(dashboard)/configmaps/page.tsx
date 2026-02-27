"use client"

import { Suspense, useEffect, useMemo, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { RbacButton, RbacWrapper } from "@/components/rbac"
import { getUserRole } from "@/lib/auth" // still needed for loadConfigIntoDialog logic
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { PaginationBar } from "@/components/pagination-bar"
import { toast } from "sonner"
import { Plus, RefreshCw, Pencil, Trash2, Settings2, Loader2, Bot, FileText, X, Eye } from "lucide-react"
import { BrandIcon, type BrandSlug } from "@/components/brand-icon"

type ConfigMapType = "llm" | "prompts"
type DialogMode = "view" | "edit" | "create"

type ConfigMapItem = {
  name: string
  namespace: string
  labels?: Record<string, string>
  data?: Record<string, string>
  created_at?: string
}

type NamespaceItem = {
  name: string
  created_at?: string
}

interface DependentAgent {
  name: string
  namespace: string
  created_at?: string
}

type DependentKind = "agent" | "descriptor"

type DependentResource = {
  kind: DependentKind
  name: string
  namespace: string
}

function safeItems(x: unknown): ConfigMapItem[] {
  if (!Array.isArray(x)) return []
  return x
    .map((it): ConfigMapItem | null => {
      const r = typeof it === "object" && it !== null ? (it as Record<string, unknown>) : {}
      const name = typeof r.name === "string" ? r.name : ""
      const namespace = typeof r.namespace === "string" ? r.namespace : ""
      const labels = (typeof r.labels === "object" && r.labels !== null) ? (r.labels as Record<string, string>) : undefined
      const data = (typeof r.data === "object" && r.data !== null) ? (r.data as Record<string, string>) : undefined
      const created_at = typeof r.created_at === "string" ? r.created_at : undefined
      if (!name || !namespace) return null
      return { name, namespace, labels, data, created_at }
    })
    .filter((x): x is ConfigMapItem => Boolean(x))
}

function safeNamespaces(x: unknown): NamespaceItem[] {
  if (!Array.isArray(x)) return []
  return x
    .map((it): NamespaceItem | null => {
      const r = typeof it === "object" && it !== null ? (it as Record<string, unknown>) : {}
      const name = typeof r.name === "string" ? r.name : ""
      if (!name) return null
      const created_at = typeof r.created_at === "string" ? r.created_at : undefined
      return { name, created_at }
    })
    .filter((x): x is NamespaceItem => Boolean(x))
}

function toTextAreaValue(v: string | undefined) {
  return typeof v === "string" ? v : ""
}

function isValidJSON(input: string): { ok: true } | { ok: false; error: string } {
  const raw = input.trim()
  if (!raw) return { ok: true }
  try {
    JSON.parse(raw)
    return { ok: true }
  } catch (e) {
    const msg = e instanceof Error ? e.message : "invalid JSON"
    return { ok: false, error: msg }
  }
}

function typeLabel(t: ConfigMapType): string {
  return t === "llm" ? "模型管理" : "提示词"
}

function normalizeLlmBrand(providerRaw: string, modelRaw: string): { kind: "brand"; slug: BrandSlug; title: string } | { kind: "mono"; text: string; cls: string; title: string } | { kind: "generic" } {
  const provider = String(providerRaw || "").trim().toLowerCase()
  const model = String(modelRaw || "").trim().toLowerCase()

  if (provider.includes("anthropic") || model.includes("claude")) {
    return { kind: "brand", slug: "anthropic", title: "Anthropic" }
  }
  if (provider.includes("openai") || provider.includes("openai_compatible") || model.startsWith("gpt") || model.includes("gpt-")) {
    return { kind: "brand", slug: "openai", title: "OpenAI" }
  }
  if (provider.includes("google") || model.includes("gemini")) {
    return { kind: "brand", slug: "google", title: "Google" }
  }
  if (provider.includes("alibaba") || provider.includes("qwen") || model.includes("qwen")) {
    return { kind: "brand", slug: "alibabacloud", title: "Alibaba Cloud" }
  }
  if (model.includes("deepseek")) {
    return { kind: "mono", text: "DS", cls: "bg-indigo-100 text-indigo-700", title: "DeepSeek" }
  }
  if (model.includes("qwen")) {
    return { kind: "mono", text: "QW", cls: "bg-orange-100 text-orange-700", title: "Qwen" }
  }
  return { kind: "generic" }
}

function toProviderLabel(providerRaw: string, modelRaw: string): string {
  const provider = String(providerRaw || "").trim()
  return provider || "-"
}

function ConfigMapsContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const pendingCreate = useRef<{ ns?: string; type?: ConfigMapType } | null>(null)
  const pendingOpen = useRef<{ ns?: string; type?: ConfigMapType; name?: string; mode?: DialogMode } | null>(null)
  const loadSeqRef = useRef(0)

  // Fix hydration mismatch for Radix UI components
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    setMounted(true)
  }, [])

  const [namespace, setNamespace] = useState("default")
  const [type, setType] = useState<ConfigMapType>("llm")
  const [items, setItems] = useState<ConfigMapItem[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState(false)
  const [editingName, setEditingName] = useState<string | null>(null)
  const [dialogMode, setDialogMode] = useState<DialogMode>("create")
  const [dialogNsSelectOpen, setDialogNsSelectOpen] = useState(false)
  const [dialogTypeSelectOpen, setDialogTypeSelectOpen] = useState(false)

  const [namespaces, setNamespaces] = useState<NamespaceItem[]>([])
  const [isLoadingNs, setIsLoadingNs] = useState(false)
  const [nsLoadError, setNsLoadError] = useState<string | null>(null)
  
  // 删除和依赖检查相关状态
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [deleteNamespace, setDeleteNamespace] = useState<string>("default")
  const [dependentAgents, setDependentAgents] = useState<DependentResource[]>([])
  const [showDependencyDialog, setShowDependencyDialog] = useState(false)
  const [checkingDependency, setCheckingDependency] = useState(false)

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totalPages])

  useEffect(() => {
    // Any filter change should reset pagination to the first page.
    setPage(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespace, type])

  // form state (shared)
  const [name, setName] = useState("")
  const [dialogNamespace, setDialogNamespace] = useState("default")
  const [dialogType, setDialogType] = useState<ConfigMapType>("llm")

  // llm fields
  const [llmProvider, setLlmProvider] = useState("openai_compatible")
  const [llmBaseUrl, setLlmBaseUrl] = useState("")
  const [llmModel, setLlmModel] = useState("")
  const [llmApiKey, setLlmApiKey] = useState("")

  // prompts fields
  const [promptsFewshots, setPromptsFewshots] = useState("")
  const [promptsBackground, setPromptsBackground] = useState("")

  const title = useMemo(() => {
    if (dialogMode === "view") return "配置详情"
    if (dialogMode === "edit") return "编辑配置"
    return "新建配置"
  }, [dialogMode])

  const resetForm = () => {
    setEditingName(null)
    setName("")
    setDialogNamespace(namespace)
    setDialogType(type)
    setLlmProvider("openai_compatible")
    setLlmBaseUrl("")
    setLlmModel("")
    setLlmApiKey("")
    setPromptsFewshots("")
    setPromptsBackground("")
    setDialogNsSelectOpen(false)
    setDialogTypeSelectOpen(false)
  }

  const closeDialogSafely = () => {
    // Close any open Select popovers first to avoid Radix aria-hidden warnings
    // during dialog close/unmount transitions.
    setDialogNsSelectOpen(false)
    setDialogTypeSelectOpen(false)
    // Defer dialog close to next frame so SelectContent can unmount cleanly.
    requestAnimationFrame(() => setOpen(false))
  }

  const load = async () => {
    const mySeq = ++loadSeqRef.current
    setIsLoading(true)
    try {
      const ns = (namespace || "default").trim() || "default"
      const res = await api.get(`/namespaces/${ns}/configmaps`, {
        params: {
          type,
          offset: (page - 1) * pageSize,
          limit: pageSize,
        },
      })
      const data = res.data?.data ?? res.data
      const list = safeItems(data?.items as unknown)
      const total = Number(data?.totalCount ?? data?.total ?? 0)
      // Prevent out-of-order responses from overwriting the latest filter state.
      if (mySeq === loadSeqRef.current) {
        setItems(list)
        setTotalCount(Number.isFinite(total) && total >= 0 ? total : list.length)
      }
    } catch (e) {
      console.error("load configmaps failed", e)
      if (mySeq === loadSeqRef.current) {
        setItems([])
        setTotalCount(0)
      }
      toast.error("加载 ConfigMap 失败")
    } finally {
      if (mySeq === loadSeqRef.current) {
        setIsLoading(false)
      }
    }
  }

  useEffect(() => {
    // Clear stale rows immediately when filters change to avoid "UI shows Prompts but rows are LLM" confusion.
    setItems([])
    setTotalCount(0)
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespace, type, page, pageSize])

  const openCreate = () => {
    setDialogMode("create")
    resetForm()
    setDialogNamespace(namespace)
    setDialogType(type)
    setOpen(true)
  }

  const loadNamespaces = async () => {
    if (isLoadingNs) return
    setIsLoadingNs(true)
    setNsLoadError(null)
    try {
      const res = await api.get("/namespaces")
      // interceptor unwraps data, so res.data is the payload containing items
      const raw = res.data?.items || res.data?.data?.items
      const list = safeNamespaces(raw as unknown)
      setNamespaces(list)
    } catch (e) {
      console.error("load namespaces failed", e)
      setNamespaces([])
      setNsLoadError("命名空间加载失败")
    } finally {
      setIsLoadingNs(false)
    }
  }

  useEffect(() => {
    void loadNamespaces()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Support deep-link:
  // - /configmaps?namespace=xxx&type=llm|prompts&create=1
  // - /configmaps?namespace=xxx&type=prompts&name=cm-name&mode=view|edit
  useEffect(() => {
    const ns = (searchParams.get("namespace") || "").trim()
    const t = (searchParams.get("type") || "").trim()
    const create = searchParams.get("create")
    const cmName = (searchParams.get("name") || "").trim()
    const modeRaw = (searchParams.get("mode") || "").trim()

    const nextNs = ns || undefined
    const nextType: ConfigMapType | undefined = t === "llm" || t === "prompts" ? (t as ConfigMapType) : undefined
    const nextMode: DialogMode | undefined = modeRaw === "edit" || modeRaw === "view" ? (modeRaw as DialogMode) : undefined

    // Keep state in sync with URL query (do not "init once", otherwise hydration/navigation may miss params).
    if (nextNs) setNamespace(nextNs)
    if (nextType) setType(nextType)

    if (create === "1") {
      // defer open until state is applied, so dialog shows correct ns/type
      pendingCreate.current = { ns: nextNs, type: nextType }
    }

    if (cmName) {
      // defer open until namespace/type state is applied
      pendingOpen.current = { ns: nextNs, type: nextType, name: cmName, mode: nextMode || "view" }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  useEffect(() => {
    if (!pendingCreate.current) return
    const wantNs = pendingCreate.current.ns
    const wantType = pendingCreate.current.type
    const nsOk = !wantNs || wantNs === namespace
    const typeOk = !wantType || wantType === type
    if (!nsOk || !typeOk) return

    pendingCreate.current = null
    openCreate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespace, type])

  useEffect(() => {
    if (!pendingOpen.current) return
    const wantNs = pendingOpen.current.ns
    const wantType = pendingOpen.current.type
    const wantName = (pendingOpen.current.name || "").trim()
    const wantMode = pendingOpen.current.mode || "view"
    const nsOk = !wantNs || wantNs === namespace
    const typeOk = !wantType || wantType === type
    if (!nsOk || !typeOk || !wantName) return

    pendingOpen.current = null
    void loadConfigIntoDialog(wantName, wantMode)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespace, type])

  const loadConfigIntoDialog = async (cmName: string, mode: DialogMode) => {
    try {
      // Force 'view' mode for non-admin users even if 'edit' was requested
      const userRole = getUserRole()
      const safeMode = userRole !== "admin" ? "view" : mode;
      
      const ns = (namespace || "default").trim() || "default"
      const res = await api.get(`/namespaces/${ns}/configmaps/${encodeURIComponent(cmName)}`)
      // Note: api interceptor unwraps response.data.data into res.data
      const r = (res.data || {}) as Record<string, unknown>
      const data = (typeof r.data === "object" && r.data !== null) ? (r.data as Record<string, string>) : {}
      const labels = (typeof r.labels === "object" && r.labels !== null) ? (r.labels as Record<string, string>) : {}
      const rawType = typeof r.type === "string" ? r.type : ""
      const labelType = labels["dac.io/config-type"]
      
      const cmType = labelType || rawType || "llm"

      setDialogMode(safeMode)
      setEditingName(cmName)
      setName(cmName)
      setDialogNamespace(ns)
      setDialogType(cmType === "prompts" ? "prompts" : "llm")

      if ((cmType === "prompts" ? "prompts" : "llm") === "llm") {
        // execution-engine samples use provider: "openai_compatible"
        // keep backward-compat mapping from "openai" to "openai_compatible"
        const p = (data["provider"] || "openai_compatible").trim()
        setLlmProvider(p === "openai" ? "openai_compatible" : p)
        setLlmBaseUrl(data["base-url"] || "")
        setLlmModel(data["model"] || "")
        // api-key is redacted by backend; keep blank unless user wants to change it
        setLlmApiKey("")
      } else {
        setPromptsFewshots(data["fewshots.json"] || "")
        setPromptsBackground(data["background_knowledge.json"] || "")
      }

      setOpen(true)
    } catch (e) {
      console.error("open edit failed", e)
      toast.error("加载 ConfigMap 详情失败")
    }
  }

  const openView = async (cmName: string) => {
    await loadConfigIntoDialog(cmName, "view")
  }

  const openEdit = async (cmName: string) => {
    await loadConfigIntoDialog(cmName, "edit")
  }

  const submit = async () => {
    const ns = (dialogNamespace || "default").trim() || "default"
    const cmName = name.trim()
    if (!cmName) {
      toast.error("请填写 ConfigMap 名称")
      return
    }

    // Prompts configmap requires JSON strings for consumers (execution-engine will json.Unmarshal).
    // Validate on submit to avoid creating an invalid config.
    if (dialogType === "prompts") {
      const r1 = isValidJSON(promptsFewshots)
      if (!r1.ok) {
        toast.error(`fewshots.json 不是合法 JSON：${r1.error}`)
        return
      }
      const r2 = isValidJSON(promptsBackground)
      if (!r2.ok) {
        toast.error(`background_knowledge.json 不是合法 JSON：${r2.error}`)
        return
      }
    }

    const llmProviderValue = (() => {
      const p = (llmProvider || "").trim()
      if (!p) return "openai_compatible"
      return p === "openai" ? "openai_compatible" : p
    })()

    const data: Record<string, string> =
      dialogType === "llm"
        ? {
            provider: llmProviderValue,
            ...(llmBaseUrl.trim() ? { "base-url": llmBaseUrl.trim() } : {}),
            ...(llmModel.trim() ? { model: llmModel.trim() } : {}),
            // optional: if blank, backend will preserve existing api-key on update
            ...(llmApiKey.trim() ? { "api-key": llmApiKey.trim() } : {}),
          }
        : {
            ...(promptsFewshots.trim() ? { "fewshots.json": promptsFewshots } : {}),
            ...(promptsBackground.trim() ? { "background_knowledge.json": promptsBackground } : {}),
          }

    try {
      if (editingName) {
        await api.put(`/namespaces/${ns}/configmaps/${encodeURIComponent(editingName)}`, {
          type: dialogType,
          data,
        })
        toast.success("更新成功")
      } else {
        await api.post(`/namespaces/${ns}/configmaps`, {
          name: cmName,
          type: dialogType,
          data,
        })
        toast.success("创建成功")
      }
      setOpen(false)
      resetForm()
      // Keep page in sync with where the resource was created/edited
      setNamespace(ns)
      setType(dialogType)
      await load()
    } catch (e) {
      console.error("submit configmap failed", e)
      toast.error(editingName ? "更新失败" : "创建失败")
    }
  }

  // 检查是否有智能体依赖此配置
  const checkDependencies = async (cmName: string, cmNamespace: string) => {
    setCheckingDependency(true)
    try {
      const dependent: DependentResource[] = []

      if (type === "llm") {
        // LLM ConfigMap 由智能体引用：`model.plannerLLM` / `model.expertLLM`
        const res = await api.get("/agents")
        // NOTE: @/lib/api.ts unwraps `{ code, message, data }`, so res.data is the inner payload.
        const data = (res.data?.data ?? res.data) as unknown
        const r = (typeof data === "object" && data !== null) ? (data as Record<string, unknown>) : {}
        const agents = (r.items ?? r.data ?? data) as unknown
        const list = Array.isArray(agents) ? agents : []
        for (const agent of list) {
          const a = (agent ?? {}) as Record<string, unknown>
          const model = (a.model ?? {}) as Record<string, unknown>
          const planner = typeof model.plannerLLM === "string" ? model.plannerLLM : ""
          const expert = typeof model.expertLLM === "string" ? model.expertLLM : ""
          if (planner === cmName || expert === cmName) {
            dependent.push({
              kind: "agent",
              name: String(a.name ?? ""),
              namespace: String(a.namespace ?? "default"),
            })
          }
        }
      } else {
        // Prompts ConfigMap 由 DataDescriptor 引用：`sources[].Prompts.ConfigMapName`
        const res = await api.get("/descriptors")
        const data = (res.data?.data ?? res.data) as unknown
        const r = (typeof data === "object" && data !== null) ? (data as Record<string, unknown>) : {}
        const descriptors = (r.items ?? r.data ?? data) as unknown
        const list = Array.isArray(descriptors) ? descriptors : []
        for (const dd of list) {
          const r = (dd ?? {}) as Record<string, unknown>
          const ns = String(r.namespace ?? "default")
          // 只阻止删除同 namespace 的配置（ConfigMap namespaced）
          if (ns !== cmNamespace) continue

          const sourcesRaw = r.sources
          const sources = Array.isArray(sourcesRaw) ? sourcesRaw : []
          const uses = sources.some((s) => {
            const src = (s ?? {}) as Record<string, unknown>
            const prompts = (src.Prompts ?? {}) as Record<string, unknown>
            const cm = typeof prompts.ConfigMapName === "string" ? prompts.ConfigMapName : ""
            return cm === cmName
          })

          if (uses) {
            dependent.push({
              kind: "descriptor",
              name: String(r.name ?? ""),
              namespace: ns,
            })
          }
        }
      }

      return dependent
    } catch (err) {
      console.error("Failed to check dependencies", err)
      toast.error("检查依赖关系失败")
      return []
    } finally {
      setCheckingDependency(false)
    }
  }

  // 点击删除按钮时，先检查依赖
  const handleDeleteClick = async (cmName: string, cmNamespace: string) => {
    const deps = await checkDependencies(cmName, cmNamespace)
    
    if (deps.length > 0) {
      // 有依赖，显示依赖列表弹窗
      setDependentAgents(deps)
      setShowDependencyDialog(true)
    } else {
      // 无依赖，显示删除确认弹窗
      setDeleteId(cmName)
      setDeleteNamespace(cmNamespace)
    }
  }

  const handleDelete = async () => {
    if (deleteId) {
      try {
        await api.delete(`/namespaces/${deleteNamespace}/configmaps/${encodeURIComponent(deleteId)}`)
        toast.success("配置已删除")
        setDeleteId(null)
        await load()
      } catch (e) {
        console.error("delete configmap failed", e)
        const err = e as { response?: { data?: { message?: string } } }
        toast.error(err.response?.data?.message || "删除失败")
      }
    }
  }

  const isViewMode = dialogMode === "view"

  if (!mounted) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    )
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div className="text-sm font-medium text-slate-600">
          <span className="text-slate-900 font-semibold">配置管理</span>
        </div>

        <div className="flex items-center gap-2">
          {/* Filters (move to top bar for better aesthetics) */}
          <div className="hidden md:flex items-center gap-2 mr-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-slate-500">命名空间</span>
              {namespaces.length > 0 ? (
                <Select value={namespace} onValueChange={setNamespace} disabled={isLoadingNs}>
                  <SelectTrigger className="h-9 w-44">
                    <SelectValue placeholder="选择命名空间" />
                  </SelectTrigger>
                  <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                    {nsLoadError ? (
                      <SelectItem value="__error__" disabled>
                        {nsLoadError}
                      </SelectItem>
                    ) : isLoadingNs ? (
                      <SelectItem value="__loading__" disabled>
                        加载中...
                      </SelectItem>
                    ) : null}
                    {namespaces.map((ns) => (
                      <SelectItem key={ns.name} value={ns.name}>
                        {ns.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  className="h-9 w-44"
                  value={namespace}
                  onChange={(e) => setNamespace(e.target.value)}
                  placeholder="default"
                />
              )}
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-slate-500">类型</span>
              <Select value={type} onValueChange={(v) => setType(v as ConfigMapType)}>
                <SelectTrigger className="h-9 w-36">
                  <SelectValue placeholder="选择类型" />
                </SelectTrigger>
                <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                  <SelectItem value="llm">模型管理</SelectItem>
                  <SelectItem value="prompts">提示词</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <Button variant="outline" size="icon" onClick={() => void load()} disabled={isLoading} title="刷新">
            <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
          </Button>
          <RbacButton 
            className="flex items-center gap-2 bg-[#1e293b] hover:bg-[#0f172a] text-white" 
            onClick={openCreate}
            requiredRole="admin"
            fallbackTitle="无权限：仅管理员可创建"
          >
            <Plus className="w-4 h-4" />
            新建配置
          </RbacButton>
        </div>
      </div>

      {/* Table card */}
      <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-slate-50">
              <TableHead>名称</TableHead>
              <TableHead>命名空间</TableHead>
              <TableHead>{type === "llm" ? "提供方" : "配置概览"}</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-slate-500 py-10">
                  {isLoading ? "加载中..." : "暂无数据"}
                </TableCell>
              </TableRow>
            ) : (
              items.map((cm) => (
                <TableRow
                  key={`${cm.namespace}/${cm.name}`}
                  className="cursor-pointer hover:bg-slate-50"
                  onClick={() => void openView(cm.name)}
                >
                  <TableCell className="font-medium flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600">
                        {(() => {
                          if (type !== "llm") return <FileText className="w-4 h-4" />
                          const provider = cm.data?.provider || ""
                          const model = cm.data?.model || ""
                          const b = normalizeLlmBrand(provider, model)
                          if (b.kind === "brand") return <BrandIcon slug={b.slug} size={16} title={b.title} />
                          if (b.kind === "mono") {
                            return (
                              <span
                                className={`inline-flex items-center justify-center w-5 h-5 rounded ${b.cls} text-[10px] font-semibold leading-none`}
                                title={b.title}
                              >
                                {b.text}
                              </span>
                            )
                          }
                          return <Bot className="w-4 h-4" />
                        })()}
                      </div>
                      {cm.name}
                  </TableCell>
                  <TableCell className="text-slate-500">{cm.namespace}</TableCell>
                  <TableCell className="text-slate-700">
                    {type === "llm"
                      ? toProviderLabel(cm.data?.provider || "", cm.data?.model || "")
                      : (() => {
                          const few = String(cm.data?.["fewshots.json"] || "").trim()
                          const bg = String(cm.data?.["background_knowledge.json"] || "").trim()
                          const hasFew = few.length > 0
                          const hasBg = bg.length > 0
                          if (!hasFew && !hasBg) {
                            return <span className="text-slate-400">未配置</span>
                          }
                          return (
                            <span className="inline-flex items-center gap-2">
                              {hasFew ? <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-50 text-slate-700 border border-slate-200 text-xs">fewshots</span> : null}
                              {hasBg ? <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-50 text-slate-700 border border-slate-200 text-xs">background</span> : null}
                            </span>
                          )
                        })()}
                  </TableCell>
                  <TableCell className="text-slate-600">
                    {cm.created_at ? new Date(cm.created_at).toLocaleString() : "-"}
                  </TableCell>
                  <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-2">
                      <Button variant="ghost" size="icon" onClick={() => void openEdit(cm.name)} title="编辑">
                        <RbacWrapper requiredRole="admin">
                          <Pencil className="w-4 h-4 text-slate-600" />
                        </RbacWrapper>
                        <RbacWrapper requiredRole="admin" inverse>
                          <Eye className="w-4 h-4 text-slate-600" />
                        </RbacWrapper>
                      </Button>
                      <RbacWrapper requiredRole="admin">
                        <Button 
                          variant="ghost" 
                          size="icon" 
                          onClick={() => void handleDeleteClick(cm.name, cm.namespace)}
                          disabled={checkingDependency}
                          title="删除"
                        >
                          <Trash2 className="w-4 h-4 text-red-500" />
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

      <Dialog
        open={open}
        onOpenChange={(v) => {
          if (!v) {
            closeDialogSafely()
            resetForm()
            return
          }
          setOpen(true)
        }}
      >
      <DialogContent className="sm:max-w-[720px] max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
            <div className="flex items-center justify-between gap-3">
              <DialogTitle>{title}</DialogTitle>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-slate-500 hover:text-slate-900"
                onClick={closeDialogSafely}
                aria-label="关闭"
                title="关闭"
              >
                <X className="w-4 h-4" />
              </Button>
            </div>
          </DialogHeader>

          <div className="space-y-4 flex-1 min-h-0 overflow-y-auto px-6 py-6">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5 sm:col-span-2">
                <Label>名称</Label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={Boolean(editingName) || isViewMode}
                  placeholder="例如：llm-deepseek-v3"
                />
              </div>
              <div className="space-y-1.5">
                <Label>命名空间</Label>
                {isViewMode || editingName ? (
                  <Input value={dialogNamespace} disabled />
                ) : namespaces.length > 0 ? (
                  <Select
                    open={dialogNsSelectOpen}
                    onOpenChange={setDialogNsSelectOpen}
                    value={dialogNamespace}
                    onValueChange={setDialogNamespace}
                    disabled={isLoadingNs}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="选择命名空间" />
                    </SelectTrigger>
                    <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                      {nsLoadError ? (
                        <SelectItem value="__error__" disabled>
                          {nsLoadError}
                        </SelectItem>
                      ) : isLoadingNs ? (
                        <SelectItem value="__loading__" disabled>
                          加载中...
                        </SelectItem>
                      ) : null}
                      {namespaces.map((ns) => (
                        <SelectItem key={ns.name} value={ns.name}>
                          {ns.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input value={dialogNamespace} onChange={(e) => setDialogNamespace(e.target.value)} placeholder="default" />
                )}
              </div>
              <div className="space-y-1.5">
                <Label>类型</Label>
                {isViewMode || editingName ? (
                  <Input value={typeLabel(dialogType)} disabled />
                ) : (
                  <Select
                    open={dialogTypeSelectOpen}
                    onOpenChange={setDialogTypeSelectOpen}
                    value={dialogType}
                    onValueChange={(v) => setDialogType(v as ConfigMapType)}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="选择类型" />
                    </SelectTrigger>
                    <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                      <SelectItem value="llm">模型管理</SelectItem>
                      <SelectItem value="prompts">提示词</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              </div>
            </div>

            {dialogType === "llm" ? (
              <div className="rounded-lg border border-slate-200 bg-white p-4 space-y-4">
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">模型配置</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <Label>Provider</Label>
                    <Input value={llmProvider} onChange={(e) => setLlmProvider(e.target.value)} placeholder="openai_compatible" disabled={isViewMode} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Model</Label>
                    <Input value={llmModel} onChange={(e) => setLlmModel(e.target.value)} placeholder="例如：gpt-4.1 / deepseek-chat" disabled={isViewMode} />
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label>Base URL（可选）</Label>
                    <Input value={llmBaseUrl} onChange={(e) => setLlmBaseUrl(e.target.value)} placeholder="例如：https://api.openai.com/v1" disabled={isViewMode} />
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label>API Key（可选；编辑时留空表示不修改）</Label>
                    <Input value={llmApiKey} onChange={(e) => setLlmApiKey(e.target.value)} placeholder="sk-..." disabled={isViewMode} />
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-slate-200 bg-white p-4 space-y-4">
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">提示词配置</div>
                <div className="space-y-2">
                  <Label>fewshots.json（可选）</Label>
                  <textarea
                    className="w-full min-h-[140px] rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                    value={toTextAreaValue(promptsFewshots)}
                    onChange={(e) => setPromptsFewshots(e.target.value)}
                    placeholder='例如：[{"query":"查找年龄大于30岁的用户","answer":"SELECT name, age FROM users WHERE age > 30"}]'
                    disabled={isViewMode}
                  />
                </div>
                <div className="space-y-2">
                  <Label>background_knowledge.json（可选）</Label>
                  <textarea
                    className="w-full min-h-[140px] rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                    value={toTextAreaValue(promptsBackground)}
                    onChange={(e) => setPromptsBackground(e.target.value)}
                    placeholder='例如：[{"description":"年度总额采用年末值进行处理。举例来说，如果想知道2023年的贷款总额，只需要查询2023年的记录中，看看月份最大的那个月的数据就是2023年的贷款总额。"}]'
                    disabled={isViewMode}
                  />
                </div>
              </div>
            )}
          </div>

          {!isViewMode && (
            <DialogFooter className="px-6 py-4 border-t border-slate-100 bg-slate-50/50 mt-0">
              <Button variant="outline" onClick={closeDialogSafely}>
                取消
              </Button>
              <Button onClick={() => void submit()}>
                {editingName ? "保存" : "创建"}
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>

      {/* 依赖关系提示弹窗 */}
      <AlertDialog open={showDependencyDialog} onOpenChange={setShowDependencyDialog}>
        <AlertDialogContent className="w-[min(96vw,56rem)] max-w-4xl">
          <AlertDialogHeader>
            <AlertDialogTitle>无法删除 - 存在依赖关系</AlertDialogTitle>
            <AlertDialogDescription>
              该配置正在被以下 {dependentAgents.length} 个资源使用，无法删除。
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="mt-4 space-y-3 px-6">
            <div className="max-h-[320px] w-full overflow-auto rounded-md border border-slate-200">
              <Table className="w-full table-fixed">
                <TableHeader>
                  <TableRow className="bg-slate-50">
                    <TableHead className="w-auto">资源</TableHead>
                    <TableHead className="w-28">命名空间</TableHead>
                    <TableHead className="w-28 text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dependentAgents.map((agent) => (
                    <TableRow key={`${agent.kind}/${agent.namespace}/${agent.name}`}>
                      <TableCell className="font-medium whitespace-normal break-all">
                        {agent.kind === "agent" ? "智能体" : "数据源"} / {agent.name}
                      </TableCell>
                      <TableCell className="text-slate-500">{agent.namespace}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setShowDependencyDialog(false)
                            router.push(
                              agent.kind === "agent"
                                ? `/agents/${agent.namespace}/${agent.name}`
                                : `/datasources/${agent.namespace}/${agent.name}`
                            )
                          }}
                          className="text-blue-600 hover:text-blue-800 whitespace-nowrap"
                        >
                          查看详情 →
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <div className="text-sm text-slate-600">
              请先解除这些资源对该配置的引用，然后再删除此配置。
            </div>
          </div>

          <AlertDialogFooter>
            <AlertDialogAction>知道了</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 删除确认弹窗 */}
      <AlertDialog open={!!deleteId} onOpenChange={(open) => !open && setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除配置?</AlertDialogTitle>
            <AlertDialogDescription>
              此操作将永久删除该配置 ({deleteId})。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-red-600 hover:bg-red-700">
              确认删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// Next.js requires useSearchParams() to be wrapped in Suspense.
export default function ConfigMapsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center p-8">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      }
    >
      <ConfigMapsContent />
    </Suspense>
  )
}



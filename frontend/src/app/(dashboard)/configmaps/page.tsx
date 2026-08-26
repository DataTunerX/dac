"use client"

import { Suspense, useEffect, useMemo, useRef, useState, useDeferredValue } from "react"
import useSWR from "swr"
import { useRouter, useSearchParams } from "next/navigation"
import { api } from "@/lib/api"
import { listConfigMaps, getConfigMap, listAllConfigMaps, listAllConfigMapsAcrossNamespaces } from "@/lib/configmaps-api"
import { listAgentsAll } from "@/lib/agents-api"
import { ListPageSearch } from "@/components/list-page-search"
import { filterListByQuery } from "@/lib/filter-list-by-query"
import { listAllDescriptors } from "@/lib/descriptors-api"
import { apiFetcher } from "@/lib/swr"
import { Button } from "@/components/ui/button"
import { RbacButton, RbacWrapper } from "@/components/rbac"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { TableWrapper } from "@/components/ui/table-wrapper"
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
const CONFIGMAPS_LIST_COLUMNS = [
  { id: "name", size: 220 },
  { id: "namespace", size: 140 },
  { id: "summary", size: 220 },
  { id: "created", size: 180 },
  { id: "actions", size: 120 },
] as const

const CONFIGMAPS_DEPENDENT_COLUMNS = [
  { id: "resource", size: 240 },
  { id: "namespace", size: 112 },
  { id: "actions", size: 112 },
] as const

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

  // 1. Model checks first (most reliable)
  if (model.includes("claude")) {
    return { kind: "brand", slug: "anthropic", title: "Anthropic" }
  }
  if (model.startsWith("gpt") || model.includes("gpt-")) {
    return { kind: "brand", slug: "openai", title: "OpenAI" }
  }
  if (model.includes("gemini")) {
    return { kind: "brand", slug: "google", title: "Google" }
  }
  if (model.includes("qwen")) {
    return { kind: "brand", slug: "alibabacloud", title: "Alibaba Cloud" }
  }
  if (model.includes("deepseek")) {
    return { kind: "mono", text: "DS", cls: "bg-indigo-100 text-indigo-700", title: "DeepSeek" }
  }

  // 2. Provider fallback
  if (provider.includes("anthropic")) {
    return { kind: "brand", slug: "anthropic", title: "Anthropic" }
  }
  if (provider.includes("google")) {
    return { kind: "brand", slug: "google", title: "Google" }
  }
  if (provider.includes("alibaba") || provider.includes("dashscope") || provider.includes("bailian")) {
    return { kind: "brand", slug: "alibabacloud", title: "Alibaba Cloud" }
  }

  // 3. Last resort: openai (catches openai and openai_compatible)
  if (provider.includes("openai") || provider.includes("openai_compatible")) {
    return { kind: "brand", slug: "openai", title: "OpenAI" }
  }

  // 4. Default: generic
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

  const [namespace, setNamespace] = useState("")
  const [namespaceInitialized, setNamespaceInitialized] = useState(false)
  const [type, setType] = useState<ConfigMapType>("llm")
  const [items, setItems] = useState<ConfigMapItem[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(1)
  const [searchQuery, setSearchQuery] = useState("")
  const deferredSearch = useDeferredValue(searchQuery)
  const isSearchMode = searchQuery.trim() !== ""
  const [open, setOpen] = useState(false)
  const [editingName, setEditingName] = useState<string | null>(null)
  const [dialogMode, setDialogMode] = useState<DialogMode>("create")
  const [dialogNsSelectOpen, setDialogNsSelectOpen] = useState(false)

  // Namespaces: SWR for dedup/cache (Vercel React Best Practices 4.3)
  const { data: nsData, error: nsError, isLoading: isLoadingNs } = useSWR<{ items?: unknown; data?: { items?: unknown } }>("/namespaces", apiFetcher)
  const namespaces = useMemo(() => safeNamespaces(nsData?.items ?? (nsData as { data?: { items?: unknown } })?.data?.items ?? []), [nsData])
  const nsLoadError = nsError ? "命名空间加载失败" : null

  // Default to "全部命名空间" once the namespace list is loaded.
  useEffect(() => {
    if (!namespaceInitialized && namespaces.length > 0 && !isLoadingNs) {
      setNamespace("all")
      setNamespaceInitialized(true)
    }
  }, [namespaceInitialized, namespaces, isLoadingNs])

  // 删除和依赖检查相关状态
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [deleteNamespace, setDeleteNamespace] = useState<string>("")
  const [dependentAgents, setDependentAgents] = useState<DependentResource[]>([])
  const [showDependencyDialog, setShowDependencyDialog] = useState(false)
  const [checkingDependency, setCheckingDependency] = useState(false)

  const allCmKey = isSearchMode
    ? (["configmaps-all", namespace, type, namespaces] as const)
    : null
  const { data: allCmRaw, isLoading: isLoadingAllCm } = useSWR(
    allCmKey,
    async ([, ns, t, nsList]: readonly ["configmaps-all", string, ConfigMapType, NamespaceItem[]]) => {
      if (ns === "all") {
        return listAllConfigMapsAcrossNamespaces(nsList.map((n) => n.name), { type: t })
      }
      return listAllConfigMaps(ns, { type: t })
    }
  )

  const allCmItems = useMemo(
    () => safeItems(allCmRaw ?? []),
    [allCmRaw]
  )

  const sourceItems = isSearchMode ? allCmItems : items

  const displayedItems = useMemo(
    () =>
      filterListByQuery(sourceItems, deferredSearch, (cm) => {
        const data = cm.data ?? {}
        return [
          cm.name,
          cm.namespace,
          data.provider,
          data.model,
          data["base-url"],
        ]
          .filter(Boolean)
          .join(" ")
      }),
    [sourceItems, deferredSearch]
  )

  const paginationTotal = isSearchMode ? displayedItems.length : totalCount
  const totalPages = Math.max(1, Math.ceil(paginationTotal / pageSize))

  const tableItems = useMemo(() => {
    if (!isSearchMode) return displayedItems
    const start = (page - 1) * pageSize
    return displayedItems.slice(start, start + pageSize)
  }, [isSearchMode, displayedItems, page, pageSize])

  const tableLoading = isSearchMode ? isLoadingAllCm : isLoading

  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totalPages])

  useEffect(() => {
    // Any filter change should reset pagination to the first page.
    setPage(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespace, type])

  useEffect(() => {
    setPage(1)
  }, [deferredSearch])

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
  }

  const closeDialogSafely = () => {
    // Close any open Select popovers first to avoid Radix aria-hidden warnings
    // during dialog close/unmount transitions.
    setDialogNsSelectOpen(false)
    // Defer dialog close to next frame so SelectContent can unmount cleanly.
    requestAnimationFrame(() => setOpen(false))
  }

  const load = async () => {
    const mySeq = ++loadSeqRef.current
    setIsLoading(true)
    try {
      const ns = namespace || (namespaceInitialized ? namespaces[0]?.name || "default" : "default")
      const isAll = ns === "all"
      if (isAll) {
        // Fetch all namespaces and merge results
        const nsList = namespaces.map((n) => n.name)
        const allItems = await listAllConfigMapsAcrossNamespaces(nsList, { type })
        const total = allItems.length
        const start = (page - 1) * pageSize
        const paged = allItems.slice(start, start + pageSize)
        if (mySeq === loadSeqRef.current) {
          setItems(paged)
          setTotalCount(total)
        }
      } else {
        const data = await listConfigMaps(ns, {
          type,
          offset: (page - 1) * pageSize,
          limit: pageSize,
        })
        const list = data.items ?? []
        const total = data.totalCount ?? 0
        if (mySeq === loadSeqRef.current) {
          setItems(list)
          setTotalCount(Number.isFinite(total) && total >= 0 ? total : list.length)
        }
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
    if (isSearchMode) return
    // Wait until namespace has been auto-selected from the loaded list.
    if (!namespace && !namespaceInitialized) return
    // Clear stale rows immediately when filters change to avoid "UI shows Prompts but rows are LLM" confusion.
    setItems([])
    setTotalCount(0)
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespace, type, page, pageSize, isSearchMode])

  const openCreate = () => {
    setDialogMode("create")
    resetForm()
    const ns = namespace === "all" ? (namespaces[0]?.name || "default") : namespace
    setDialogNamespace(ns)
    setDialogType(type)
    setOpen(true)
  }

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
    void loadConfigIntoDialog(wantName, wantNs || namespace, wantMode)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespace, type])

  const loadConfigIntoDialog = async (cmName: string, cmNamespace: string, mode: DialogMode) => {
    try {
      const ns = (cmNamespace || namespace || "default").trim() || "default"
      const r = await getConfigMap(ns, cmName)
      const data = r.data ?? {}
      const labels = r.labels ?? {}
      const labelType = labels["dac.io/config-type"]
      const cmType = labelType || "llm"

      setDialogMode(mode)
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

  const openView = async (cmName: string, cmNamespace: string) => {
    await loadConfigIntoDialog(cmName, cmNamespace, "view")
  }

  const openEdit = async (cmName: string, cmNamespace: string) => {
    await loadConfigIntoDialog(cmName, cmNamespace, "edit")
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
        const p = dialogType === "llm" ? "llm-configmaps" : "prompt-configmaps"
        await api.put(`/namespaces/${ns}/${p}/${encodeURIComponent(editingName)}`, {
          type: dialogType,
          data,
        })
        toast.success("更新成功")
      } else {
        const p = dialogType === "llm" ? "llm-configmaps" : "prompt-configmaps"
        await api.post(`/namespaces/${ns}/${p}`, {
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
        // LLM ConfigMap 由智能体引用：model.plannerLLM / model.expertLLM
        const { items: list } = await listAgentsAll()
        for (const a of list) {
          const model = a.model
          const planner = model?.plannerLLM ?? ""
          const expert = model?.expertLLM ?? ""
          if (planner === cmName || expert === cmName) {
            dependent.push({
              kind: "agent",
              name: a.name ?? "",
              namespace: a.namespace ?? "default",
            })
          }
        }
      } else {
        // Prompts ConfigMap 由 DataDescriptor 引用：sources[].prompts.configMapName
        const list = await listAllDescriptors()
        for (const dd of list) {
          const ns = dd.namespace ?? "default"
          if (ns !== cmNamespace) continue
          const sources = dd.sources ?? []
          const uses = sources.some((s) => {
            const configMapName = s.prompts?.configMapName ?? ""
            return configMapName === cmName
          })
          if (uses) {
            dependent.push({
              kind: "descriptor",
              name: dd.name ?? "",
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
        const p = type === "llm" ? "llm-configmaps" : "prompt-configmaps"
        await api.delete(`/namespaces/${deleteNamespace}/${p}/${encodeURIComponent(deleteId)}`)
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

  const permissionPrefix = type === "llm" ? "llmconfig" : "promptconfig"

  if (!mounted) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <Loader2 className="h-6 w-6 animate-spin text-content-muted" />
      </div>
    )
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="text-sm font-medium text-content">
          <span className="text-content font-semibold">{typeLabel(type)}</span>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2">
          <ListPageSearch
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="搜索名称…"
          />
          {/* Filters (move to top bar for better aesthetics) */}
          <div className="hidden md:flex items-center gap-2 mr-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-content-muted">命名空间</span>
              {namespaces.length > 0 ? (
                <Select value={namespace} onValueChange={setNamespace} disabled={isLoadingNs}>
                  <SelectTrigger className="h-9 w-44">
                    <SelectValue placeholder="选择命名空间" />
                  </SelectTrigger>
                  <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                    <SelectItem value="all">全部命名空间</SelectItem>
                    {nsLoadError ? (
                      <SelectItem value="__error__" disabled>
                        {nsLoadError}
                      </SelectItem>
                    ) : isLoadingNs ? (
                      <SelectItem value="__loading__" disabled>
                        加载中…
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

          </div>

          <Button variant="outline" size="icon" onClick={() => void load()} disabled={isLoading} title="刷新" aria-label="刷新">
            <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
          </Button>
          <RbacButton 
            className="flex items-center gap-2" 
            onClick={openCreate}
            requiredPermission={`${permissionPrefix}:create`}
          >
            <Plus className="w-4 h-4" />
            新建配置
          </RbacButton>
        </div>
      </div>

      {/* Table card */}
      <TableWrapper>
        <Table storageKey="configmaps-list" columns={[...CONFIGMAPS_LIST_COLUMNS]}>
          <TableHeader>
            <TableRow className="bg-surface-muted">
              <TableHead columnId="name">名称</TableHead>
              <TableHead columnId="namespace">命名空间</TableHead>
              <TableHead columnId="summary">{type === "llm" ? "提供方" : "配置概览"}</TableHead>
              <TableHead columnId="created">创建时间</TableHead>
              <TableHead columnId="actions" className="text-right">操作</TableHead>
              </TableRow>
          </TableHeader>
          <TableBody>
            {tableItems.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-content-muted py-10">
                  {tableLoading
                    ? "加载中…"
                    : sourceItems.length === 0
                      ? "暂无数据"
                      : deferredSearch.trim()
                        ? "未找到匹配的配置"
                        : "暂无数据"}
                </TableCell>
              </TableRow>
            ) : (
              tableItems.map((cm) => (
                <TableRow
                  key={`${cm.namespace}/${cm.name}`}
                  className="cursor-pointer hover:bg-surface-muted"
                  onClick={() => void openView(cm.name, cm.namespace)}
                >
                  <TableCell columnId="name" className="font-medium flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-cta/10 flex items-center justify-center text-cta">
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
                  <TableCell columnId="namespace" className="text-content-muted">{cm.namespace}</TableCell>
                  <TableCell columnId="summary" className="text-content">
                    {type === "llm"
                      ? toProviderLabel(cm.data?.provider || "", cm.data?.model || "")
                      : (() => {
                          const few = String(cm.data?.["fewshots.json"] || "").trim()
                          const bg = String(cm.data?.["background_knowledge.json"] || "").trim()
                          const hasFew = few.length > 0
                          const hasBg = bg.length > 0
                          if (!hasFew && !hasBg) {
                            return <span className="text-content-muted">未配置</span>
                          }
                          return (
                            <span className="inline-flex items-center gap-2">
                              {hasFew ? <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-surface-muted text-content border border-line text-xs">fewshots</span> : null}
                              {hasBg ? <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-surface-muted text-content border border-line text-xs">background</span> : null}
                            </span>
                          )
                        })()}
                  </TableCell>
                  <TableCell columnId="created" className="text-content">
                    {cm.created_at ? new Date(cm.created_at).toLocaleString() : "-"}
                  </TableCell>
                  <TableCell columnId="actions" className="text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-2">
                      <Button variant="ghost" size="icon" onClick={() => void openEdit(cm.name, cm.namespace)} title="编辑" aria-label="编辑">
                        <RbacWrapper requiredPermission={`${permissionPrefix}:update`}>
                          <Pencil className="w-4 h-4 text-content" />
                        </RbacWrapper>
                        <RbacWrapper requiredPermission={`${permissionPrefix}:update`} inverse>
                          <Eye className="w-4 h-4 text-content" />
                        </RbacWrapper>
                      </Button>
                      <RbacWrapper requiredPermission={`${permissionPrefix}:delete`}>
                        <Button 
                          variant="ghost" 
                          size="icon" 
                          onClick={() => void handleDeleteClick(cm.name, cm.namespace)}
                          disabled={checkingDependency}
                          title="删除"
                          aria-label="删除"
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
      </TableWrapper>

      <PaginationBar
        total={paginationTotal}
        page={page}
        pageSize={pageSize}
        pageSizeOptions={[10, 20, 50, 100]}
        isLoading={tableLoading}
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
          <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50">
            <div className="flex items-center justify-between gap-3">
              <DialogTitle>{title}</DialogTitle>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-content-muted hover:text-content"
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
                          加载中…
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
                <Input value={typeLabel(dialogType)} disabled />
              </div>
            </div>

            {dialogType === "llm" ? (
              <div className="rounded-lg border border-line bg-surface p-4 space-y-4">
                <div className="text-xs font-semibold text-content-muted uppercase tracking-wider">模型配置</div>
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
              <div className="rounded-lg border border-line bg-surface p-4 space-y-4">
                <div className="text-xs font-semibold text-content-muted uppercase tracking-wider">提示词配置</div>
                <div className="space-y-2">
                  <Label>fewshots.json（可选）</Label>
                  <textarea
                    className="w-full min-h-[140px] rounded-md border border-line bg-surface px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-cta/20"
                    value={toTextAreaValue(promptsFewshots)}
                    onChange={(e) => setPromptsFewshots(e.target.value)}
                    placeholder='例如：[{"query":"查找年龄大于30岁的用户","answer":"SELECT name, age FROM users WHERE age > 30"}]'
                    disabled={isViewMode}
                  />
                </div>
                <div className="space-y-2">
                  <Label>background_knowledge.json（可选）</Label>
                  <textarea
                    className="w-full min-h-[140px] rounded-md border border-line bg-surface px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-cta/20"
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
            <DialogFooter className="px-6 py-4 border-t border-line bg-surface-muted/50 mt-0">
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
            <TableWrapper className="max-h-[320px] overflow-auto rounded-md">
              <Table storageKey="configmaps-dependent-resources" columns={[...CONFIGMAPS_DEPENDENT_COLUMNS]}>
                <TableHeader>
                  <TableRow className="bg-surface-muted">
                    <TableHead columnId="resource">资源</TableHead>
                    <TableHead columnId="namespace">命名空间</TableHead>
                    <TableHead columnId="actions" className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dependentAgents.map((agent) => (
                    <TableRow key={`${agent.kind}/${agent.namespace}/${agent.name}`}>
                      <TableCell columnId="resource" className="font-medium whitespace-normal break-all">
                        {agent.kind === "agent" ? "智能体" : "数据源"} / {agent.name}
                      </TableCell>
                      <TableCell columnId="namespace" className="text-content-muted">{agent.namespace}</TableCell>
                      <TableCell columnId="actions" className="text-right">
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
                          className="text-cta hover:text-cta/90 whitespace-nowrap cursor-pointer"
                        >
                          查看详情 →
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableWrapper>

            <div className="text-sm text-content">
              请先解除这些资源对该配置的引用，然后再删除此配置。
            </div>
          </div>

          <AlertDialogFooter>
            <AlertDialogAction onClick={() => setShowDependencyDialog(false)}>知道了</AlertDialogAction>
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
          <Loader2 className="h-6 w-6 animate-spin text-content-muted" />
        </div>
      }
    >
      <ConfigMapsContent />
    </Suspense>
  )
}



"use client"

import { useEffect, useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import * as z from "zod"
import { Eye, EyeOff, Loader2, Plug } from "lucide-react"
import { listNamespaces } from "@/lib/namespaces-api"
import { listConfigMaps } from "@/lib/configmaps-api"
import { probeDataSource, type ProbeRequest } from "@/lib/datasource-probe-api"
import { getGPUAvailability, type GPUAvailabilityResponse } from "@/lib/environment-api"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import Link from "next/link"

// --- Schemas ---

const dataSourceSchema = z.object({
  name: z.string().min(2, "名称至少 2 个字符"),
  namespace: z.string().min(1, "命名空间必填"),
  // NOTE: this is the underlying data source type (NOT descriptorType)
  // Supported by backend + execution-engine today: mysql/postgres/minio/fileserver
  // coderepo is modeled as an independent source (no host/port).
  type: z.enum(["mysql", "postgres", "minio", "fileserver", "coderepo"], { message: "请选择类型" }),
  host: z.string().optional(),
  port: z.string().optional(),

  // DB
  user: z.string().optional(),
  password: z.string().optional(),
  // Multi-database: a single DataDescriptor can fan out into one logical source
  // per selected database. Empty array means "user hasn't selected anything yet";
  // the cross-field validator below enforces non-empty for mysql/postgres.
  databases: z.array(z.string().min(1, "数据库名不能为空")).optional(),

  // MinIO
  accessKey: z.string().optional(),
  secretKey: z.string().optional(),
  bucket: z.string().optional(),

  // Fileserver
  path: z.string().optional(),
  // MinIO / Fileserver: objects to extract (one per line)
  extractFiles: z.string().optional(),

  // Optional: prompts configmap
  promptsConfigMapName: z.string().optional(),
  gpuEnabled: z.enum(["yes", "no"]),

  // Code repo config (only for type=coderepo)
  codeRepoType: z.string().optional(),
  codeRepoPath: z.string().optional(),
  codeRepoBranch: z.string().optional(),
  codeRepoToken: z.string().optional(),
})
  .superRefine((v, ctx) => {
    // Connection fields required for non-coderepo types
    if (v.type !== "coderepo") {
      if (!v.host?.trim()) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["host"], message: "主机必填" })
      }
      if (!v.port?.trim()) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["port"], message: "端口必填" })
      }
    }

    // Type-specific required fields
    if (v.type === "mysql" || v.type === "postgres") {
      if (!v.user?.trim()) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["user"], message: "用户名必填" })
      }
      if (!v.password?.trim()) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["password"], message: "密码必填" })
      }
      const dbs = (v.databases ?? []).map((s) => s.trim()).filter(Boolean)
      if (dbs.length === 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["databases"],
          message: "请至少选择或填写一个数据库",
        })
      }
      const seen = new Set<string>()
      for (const d of dbs) {
        if (seen.has(d)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["databases"],
            message: `数据库 "${d}" 重复`,
          })
          break
        }
        seen.add(d)
      }
    }
    if (v.type === "minio") {
      if (!v.accessKey?.trim()) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["accessKey"], message: "Access Key 必填" })
      }
      if (!v.secretKey?.trim()) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["secretKey"], message: "Secret Key 必填" })
      }
      if (!v.bucket?.trim()) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["bucket"], message: "Bucket 必填" })
      }
      // NOTE: data-sinkers MinIO extractor scans the entire bucket and ignores
      // extract.files / extract.prefix, so we do not collect or validate an
      // object list in the UI. The payload still emits extract.files = [] to
      // satisfy the CR schema.
    }

    if (v.type === "fileserver") {
      // data-sinkers fileserver extractor requires extract.files
      if (!v.extractFiles?.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["extractFiles"],
          message: "请填写要抽取的文件列表（每行一个路径）",
        })
      }
    }

    if (v.type === "coderepo") {
      if (!v.codeRepoType?.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["codeRepoType"],
          message: "请选择仓库类型",
        })
      }
      if (!v.codeRepoPath?.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["codeRepoPath"],
          message: "仓库地址必填",
        })
      }
      if (!v.codeRepoBranch?.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["codeRepoBranch"],
          message: "分支必填",
        })
      }
    }
  })

export type DataSourceFormValues = z.infer<typeof dataSourceSchema>

const defaultFormValues: DataSourceFormValues = {
  name: "",
  namespace: "default",
  type: "mysql",
  host: "",
  port: "3306",
  user: "",
  password: "",
  databases: [],
  accessKey: "",
  secretKey: "",
  bucket: "",
  path: "",
  extractFiles: "",
  promptsConfigMapName: "",
  gpuEnabled: "no",
  codeRepoType: "",
  codeRepoPath: "",
  codeRepoBranch: "main",
  codeRepoToken: "",
}

// --- Components ---

type DatabaseMultiSelectProps = {
  value: string[]
  onChange: (next: string[]) => void
  buildProbeRequest: () => { ok: true; req: ProbeRequest } | { ok: false; reason: string }
  disabled?: boolean
}

/**
 * DatabaseMultiSelect lets the operator probe a live MySQL / PostgreSQL instance
 * and pick one or more databases (or fall back to manual entry).
 *
 * Probe lifecycle is owned locally; the parent only sees the resulting string[].
 * This keeps react-hook-form integration trivial (it remains a controlled value)
 * while encapsulating all probe state (loading, error, available list, server meta).
 */
function DatabaseMultiSelect({
  value,
  onChange,
  buildProbeRequest,
  disabled,
}: DatabaseMultiSelectProps) {
  const [isProbing, setIsProbing] = useState(false)
  const [probeError, setProbeError] = useState<string | null>(null)
  const [available, setAvailable] = useState<string[] | null>(null)
  const [meta, setMeta] = useState<{ version?: string; latencyMs: number } | null>(null)
  const [manualInput, setManualInput] = useState("")

  const selectedSet = useMemo(() => new Set(value), [value])

  // The chip pool is the union of probed databases and currently-selected
  // databases. Probed entries persist in the pool whether selected or not, so
  // operators can toggle them on and off. Manually-typed entries only appear
  // while they remain selected; deselecting a manual entry removes it from
  // both the selection and the pool.
  const knownList = useMemo(() => {
    const seen = new Set<string>()
    const out: string[] = []
    if (available) {
      for (const name of available) {
        if (!seen.has(name)) {
          seen.add(name)
          out.push(name)
        }
      }
    }
    for (const name of value) {
      if (!seen.has(name)) {
        seen.add(name)
        out.push(name)
      }
    }
    return out
  }, [available, value])

  const handleProbe = async () => {
    const built = buildProbeRequest()
    if (!built.ok) {
      setProbeError(built.reason)
      setAvailable(null)
      setMeta(null)
      return
    }
    setIsProbing(true)
    setProbeError(null)
    try {
      const res = await probeDataSource(built.req)
      setAvailable(res.databases ?? [])
      setMeta({ version: res.version, latencyMs: res.latencyMs })
    } catch (e: unknown) {
      const err = e as { response?: { data?: { message?: string } }; message?: string }
      setProbeError(err?.response?.data?.message || err?.message || "测试连接失败")
      setAvailable(null)
      setMeta(null)
    } finally {
      setIsProbing(false)
    }
  }

  const toggle = (name: string) => {
    if (selectedSet.has(name)) {
      onChange(value.filter((v) => v !== name))
    } else {
      onChange([...value, name])
    }
  }

  const addManual = () => {
    const trimmed = manualInput.trim()
    if (!trimmed) {
      return
    }
    if (selectedSet.has(trimmed)) {
      setManualInput("")
      return
    }
    onChange([...value, trimmed])
    setManualInput("")
  }

  const hasProbed = available !== null
  const probeButtonLabel = hasProbed ? "重新探测" : "探测数据库"

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="space-y-0.5">
          <FormLabel className="m-0">数据库</FormLabel>
          <div className="text-xs text-content-muted">
            每个选中的数据库会创建一个独立的数据源
          </div>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handleProbe}
          disabled={disabled || isProbing}
        >
          {isProbing ? (
            <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
          ) : (
            <Plug className="h-3.5 w-3.5 mr-1.5" />
          )}
          {probeButtonLabel}
        </Button>
      </div>

      {meta && (
        <div className="text-xs text-content-muted">
          连接成功{meta.version ? ` · ${meta.version}` : ""} · {meta.latencyMs}ms
        </div>
      )}

      {probeError && <div className="text-xs text-destructive">{probeError}</div>}

      <div className="rounded-md border border-line bg-surface p-3 space-y-2">
        <div className="flex items-center justify-between text-xs text-content-muted">
          <span>
            {hasProbed
              ? "点击切换选中状态"
              : "尚未探测，可点击右上方按钮探测，或在下方手动添加"}
          </span>
          <span>
            已选 {value.length}
            {knownList.length > 0 ? ` / 共 ${knownList.length}` : ""}
          </span>
        </div>

        {knownList.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {knownList.map((name) => {
              const isSelected = selectedSet.has(name)
              return (
                <button
                  type="button"
                  key={name}
                  onClick={() => toggle(name)}
                  className={cn(
                    "px-2 py-1 rounded-md border text-xs cursor-pointer transition-colors",
                    isSelected
                      ? "border-cta bg-cta/10 text-cta"
                      : "border-line bg-surface text-content hover:border-cta/50"
                  )}
                >
                  {name}
                </button>
              )
            })}
          </div>
        ) : (
          <div className="text-xs text-content-muted py-1">
            {hasProbed
              ? "探测未发现可用业务数据库，请在下方手动添加"
              : "暂无候选数据库"}
          </div>
        )}

        <div className="flex gap-2 pt-1">
          <Input
            placeholder="手动添加数据库名"
            value={manualInput}
            onChange={(e) => setManualInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                addManual()
              }
            }}
          />
          <Button type="button" variant="outline" onClick={addManual} disabled={!manualInput.trim()}>
            添加
          </Button>
        </div>
      </div>
    </div>
  )
}

export function CreateDataSourceDialog({ 
  open, 
  onOpenChange,
  onSubmit,
  initialValues,
  title,
}: { 
  open: boolean; 
  onOpenChange: (open: boolean) => void;
  onSubmit: (data: DataSourceFormValues) => void | Promise<void>;
  initialValues?: Partial<DataSourceFormValues>;
  title?: string;
}) {
  const [namespaces, setNamespaces] = useState<string[]>([])
  const [isLoadingNs, setIsLoadingNs] = useState(false)
  const [nsLoadError, setNsLoadError] = useState<string | null>(null)

  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  
  const [promptsSelectOpen, setPromptsSelectOpen] = useState(false)
  const [promptsConfigMaps, setPromptsConfigMaps] = useState<{ name: string }[]>([])
  const [isLoadingPrompts, setIsLoadingPrompts] = useState(false)
  const [promptsLoadError, setPromptsLoadError] = useState<string | null>(null)
  const [gpuAvailability, setGPUAvailability] = useState<GPUAvailabilityResponse | null>(null)
  const [isLoadingGPU, setIsLoadingGPU] = useState(false)
  const [gpuLoadError, setGPULoadError] = useState<string | null>(null)

  const form = useForm<DataSourceFormValues>({
    resolver: zodResolver(dataSourceSchema),
    defaultValues: defaultFormValues,
  })

  const defaultPortByType = useMemo(
    () => ({
      mysql: "3306",
      postgres: "5432",
      minio: "9000",
      fileserver: "8000",
      coderepo: "",
    }),
    []
  )

  const handleSubmit = async (data: DataSourceFormValues) => {
    if (isSubmitting) return
    setIsSubmitting(true)
    try {
      await onSubmit(data)
      onOpenChange(false)
      form.reset(defaultFormValues)
      setShowPassword(false)
    } finally {
      setIsSubmitting(false)
    }
  }

  const typeValue = form.watch("type")
  const namespaceValue = form.watch("namespace")
  const gpuSelectable = Boolean(gpuAvailability?.available)

  const loadNamespaces = async () => {
    if (isLoadingNs) return
    setIsLoadingNs(true)
    setNsLoadError(null)
    try {
      const res = await listNamespaces()
      const adapted = (res.items ?? []).map((x) => x.name).filter(Boolean)
      setNamespaces(adapted)
    } catch (e) {
      console.error("Failed to load namespaces", e)
      setNamespaces([])
      setNsLoadError("命名空间加载失败")
    } finally {
      setIsLoadingNs(false)
    }
  }

  useEffect(() => {
    if (open) {
      void loadNamespaces()
      void loadGPUAvailability()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (open) {
      form.reset({
        ...defaultFormValues,
        ...(initialValues || {}),
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialValues])

  useEffect(() => {
    if (open && !gpuSelectable) {
      form.setValue("gpuEnabled", "no", { shouldValidate: true })
    }
  }, [form, gpuSelectable, open])

  const loadGPUAvailability = async () => {
    if (isLoadingGPU) return
    setIsLoadingGPU(true)
    setGPULoadError(null)
    try {
      const availability = await getGPUAvailability()
      setGPUAvailability(availability)
      if (!availability.available) {
        form.setValue("gpuEnabled", "no", { shouldValidate: true })
      }
    } catch (e) {
      console.error("Failed to load GPU availability", e)
      setGPUAvailability(null)
      setGPULoadError("无法确认 GPU 环境，已默认使用 CPU")
      form.setValue("gpuEnabled", "no", { shouldValidate: true })
    } finally {
      setIsLoadingGPU(false)
    }
  }

  const loadPromptsConfigMaps = async (namespace: string) => {
    if (isLoadingPrompts) return
    setIsLoadingPrompts(true)
    setPromptsLoadError(null)
    try {
      const ns = (namespace || "default").trim() || "default"
      const data = await listConfigMaps(ns, { type: "prompts" })
      const adapted = (data.items ?? []).map((x) => ({ name: x.name })).filter((x) => x.name)
      setPromptsConfigMaps(adapted)
    } catch (e) {
      console.error("Failed to load prompts configmaps", e)
      setPromptsConfigMaps([])
      setPromptsLoadError("提示词配置加载失败，请稍后重试")
    } finally {
      setIsLoadingPrompts(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[720px] max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
        <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50">
          <DialogTitle>{title || "新建数据源"}</DialogTitle>
          <DialogDescription>
            配置连接信息以创建新的数据源（系统会基于该数据源生成指纹与知识分片）。
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="flex flex-col min-h-0 flex-1">
            <div className="space-y-4 flex-1 min-h-0 overflow-y-auto px-6 py-6">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>名称</FormLabel>
                      <FormControl>
                        <Input placeholder="例如：datadescriptor-00003（唯一标识）" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="namespace"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>命名空间</FormLabel>
                      <FormControl>
                        {namespaces.length > 0 ? (
                          <Select
                            value={field.value || "default"}
                            onValueChange={field.onChange}
                            disabled={isSubmitting || isLoadingNs}
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
                                <SelectItem key={ns} value={ns}>
                                  {ns}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : (
                          <Input placeholder="default" {...field} />
                        )}
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="gpuEnabled"
                render={({ field }) => {
                  const on = field.value === "yes"
                  const disabled = isSubmitting || isLoadingGPU || !gpuSelectable
                  return (
                    <FormItem>
                      <div className="flex items-center justify-between gap-4 rounded-lg border border-line px-4 py-3">
                        <div className="space-y-1 min-w-0 flex-1">
                          <FormLabel className="text-sm font-medium text-content cursor-default">
                            是否启用 GPU
                          </FormLabel>
                          <FormDescription className="text-xs">
                            {isLoadingGPU
                              ? "正在检查集群 GPU 能力…"
                              : gpuSelectable
                                ? `检测到 ${gpuAvailability?.nodeCount ?? 0} 个 GPU 节点，共 ${gpuAvailability?.totalGPUs ?? 0} 张 GPU，可按需启用。`
                                : gpuLoadError || "当前环境未检测到 GPU，已固定为不使用 GPU。"}
                          </FormDescription>
                        </div>
                        <FormControl>
                          <button
                            type="button"
                            role="switch"
                            aria-checked={on}
                            aria-label="是否启用 GPU"
                            disabled={disabled}
                            onClick={() => {
                              if (disabled) return
                              field.onChange(on ? "no" : "yes")
                            }}
                            className={cn(
                              "relative h-6 w-11 shrink-0 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cta focus-visible:ring-offset-2 focus-visible:ring-offset-surface",
                              on ? "bg-cta" : "bg-surface-muted ring-1 ring-inset ring-line",
                              disabled && "opacity-50 cursor-not-allowed"
                            )}
                          >
                            <span
                              className={cn(
                                "pointer-events-none absolute top-0.5 left-0.5 block h-5 w-5 rounded-full bg-surface shadow-sm transition-transform",
                                on && "translate-x-5"
                              )}
                            />
                          </button>
                        </FormControl>
                      </div>
                      <FormMessage />
                    </FormItem>
                  )
                }}
              />
            
              <div className="space-y-4">
                <div className="text-xs font-semibold text-content-muted">连接配置</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="type"
                    render={({ field }) => {
                      // Whether this row has a meaningful "second column".
                      // For mysql/postgres we render the multi-database picker as
                      // its own full-width section below, and for coderepo there
                      // is no second cell at all — so let the type select span
                      // the full row in those cases.
                      const hasSecondCell = typeValue === "minio" || typeValue === "fileserver"
                      return (
                        <FormItem className={cn(!hasSecondCell && "sm:col-span-2")}>
                          <FormLabel>类型</FormLabel>
                          <Select
                            onValueChange={(v) => {
                              field.onChange(v)
                              const nextDefault = defaultPortByType[v as keyof typeof defaultPortByType]
                              // If user hasn't customized port (still on known defaults), update it.
                              const curPort = form.getValues("port") || ""
                              if (Object.values(defaultPortByType).includes(curPort) && nextDefault) {
                                form.setValue("port", nextDefault, { shouldValidate: true })
                              }
                            }}
                            key={field.value}
                            value={field.value}
                            disabled={!!initialValues?.type}
                          >
                            <FormControl>
                              <SelectTrigger className="w-full">
                                <SelectValue placeholder="选择数据库类型" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                              <SelectItem value="mysql">MySQL</SelectItem>
                              <SelectItem value="postgres">Postgres</SelectItem>
                              <SelectItem value="minio">MinIO</SelectItem>
                              <SelectItem value="fileserver">Fileserver</SelectItem>
                              <SelectItem value="coderepo">代码仓库</SelectItem>
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )
                    }}
                  />
                  {typeValue === "minio" ? (
                    <FormField
                      control={form.control}
                      name="bucket"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Bucket</FormLabel>
                          <FormControl>
                            <Input placeholder="例如：lake" {...field} />
                          </FormControl>
                          <FormDescription>整个 bucket 会被自动扫描，无需指定对象列表</FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  ) : typeValue === "fileserver" ? (
                    <FormField
                      control={form.control}
                      name="path"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>路径（可选）</FormLabel>
                          <FormControl>
                            <Input placeholder="例如：/data/docs" {...field} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  ) : null}
                </div>

                {typeValue !== "coderepo" ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <FormField
                      control={form.control}
                      name="host"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>主机</FormLabel>
                          <FormControl>
                            <Input placeholder="例如：mysql-server 或 127.0.0.1" {...field} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="port"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>端口</FormLabel>
                          <FormControl>
                            <Input inputMode="numeric" placeholder="例如：3306" {...field} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                ) : null}

                {typeValue === "fileserver" ? (
                  <FormField
                    control={form.control}
                    name="extractFiles"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>抽取文件列表</FormLabel>
                        <FormControl>
                          <Textarea
                            rows={5}
                            placeholder={"每行一个文件路径，例如：\n/data/docs/a.pdf\n/data/docs/b.txt"}
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                ) : null}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {typeValue === "mysql" || typeValue === "postgres" ? (
                    <>
                      <FormField
                        control={form.control}
                        name="user"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>用户名</FormLabel>
                            <FormControl>
                              <Input placeholder="例如：root" autoComplete="username" {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="password"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>密码</FormLabel>
                            <FormControl>
                              <div className="relative">
                                <Input
                                  type={showPassword ? "text" : "password"}
                                  placeholder="输入密码"
                                  autoComplete="current-password"
                                  className="pr-10"
                                  {...field}
                                />
                                <button
                                  type="button"
                                  className={cn(
                                    "absolute right-2 top-1/2 -translate-y-1/2 rounded-sm p-1 text-content-muted hover:text-content cursor-pointer",
                                    isSubmitting && "pointer-events-none opacity-50"
                                  )}
                                  onClick={() => setShowPassword((v) => !v)}
                                  aria-label={showPassword ? "隐藏密码" : "显示密码"}
                                >
                                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                </button>
                              </div>
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </>
                  ) : typeValue === "minio" ? (
                    <>
                      <FormField
                        control={form.control}
                        name="accessKey"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Access Key</FormLabel>
                            <FormControl>
                              <Input placeholder="例如：minioadmin" {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="secretKey"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Secret Key</FormLabel>
                            <FormControl>
                              <div className="relative">
                                <Input
                                  type={showPassword ? "text" : "password"}
                                  placeholder="输入 Secret Key"
                                  className="pr-10"
                                  {...field}
                                />
                                <button
                                  type="button"
                                  className={cn(
                                    "absolute right-2 top-1/2 -translate-y-1/2 rounded-sm p-1 text-content-muted hover:text-content cursor-pointer",
                                    isSubmitting && "pointer-events-none opacity-50"
                                  )}
                                  onClick={() => setShowPassword((v) => !v)}
                                  aria-label={showPassword ? "隐藏" : "显示"}
                                >
                                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                </button>
                              </div>
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </>
                  ) : null}
                </div>

                {typeValue === "mysql" || typeValue === "postgres" ? (
                  <FormField
                    control={form.control}
                    name="databases"
                    render={({ field }) => (
                      <FormItem>
                        <FormControl>
                          <DatabaseMultiSelect
                            value={field.value ?? []}
                            onChange={(next) =>
                              field.onChange(next.length > 0 ? next : [])
                            }
                            disabled={isSubmitting}
                            buildProbeRequest={() => {
                              // Validate just enough to attempt a probe; the full
                              // form will still re-validate on submit.
                              const v = form.getValues()
                              const portNum = Number(v.port)
                              if (!v.host?.trim()) {
                                return { ok: false, reason: "请先填写主机" }
                              }
                              if (!v.port?.trim() || !Number.isFinite(portNum) || portNum <= 0 || portNum > 65535) {
                                return { ok: false, reason: "请先填写有效的端口 (1-65535)" }
                              }
                              if (!v.user?.trim()) {
                                return { ok: false, reason: "请先填写用户名" }
                              }
                              if (!v.password?.trim()) {
                                return { ok: false, reason: "请先填写密码" }
                              }
                              return {
                                ok: true,
                                req: {
                                  type: v.type,
                                  host: v.host.trim(),
                                  port: portNum,
                                  user: v.user.trim(),
                                  password: v.password,
                                },
                              }
                            }}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                ) : null}

                {typeValue === "coderepo" ? (
                  <div className="rounded-md border border-line bg-surface p-3 space-y-3">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <FormField
                        control={form.control}
                        name="codeRepoType"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>仓库类型</FormLabel>
                            <Select onValueChange={field.onChange} value={field.value || ""}>
                              <FormControl>
                                <SelectTrigger className="w-full">
                                  <SelectValue placeholder="选择类型" />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                                <SelectItem value="github">GitHub</SelectItem>
                                <SelectItem value="gitlab">GitLab</SelectItem>
                                <SelectItem value="gitee">Gitee</SelectItem>
                              </SelectContent>
                            </Select>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      <FormField
                        control={form.control}
                        name="codeRepoBranch"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>分支</FormLabel>
                            <FormControl>
                              <Input placeholder="main" {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </div>

                    <FormField
                      control={form.control}
                      name="codeRepoPath"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>仓库地址</FormLabel>
                          <FormControl>
                            <Input placeholder="例如：https://github.com/org/repo" {...field} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="codeRepoToken"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>访问令牌</FormLabel>
                          <FormControl>
                            <Input type="password" placeholder="可选：私有仓库需要 token" {...field} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                ) : null}
              </div>

              <div className="pt-2 border-t border-line">
                <div className="text-xs font-semibold text-content-muted mb-2">提示词（可选）</div>
                <FormField
                  control={form.control}
                  name="promptsConfigMapName"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>ConfigMap</FormLabel>
                      <FormControl>
                        <Select
                          value={field.value || "__none__"}
                          onValueChange={(v) => field.onChange(v === "__none__" ? "" : v)}
                          onOpenChange={async (next) => {
                            setPromptsSelectOpen(next)
                            if (next) {
                              await loadPromptsConfigMaps(namespaceValue || "default")
                            }
                          }}
                          open={promptsSelectOpen}
                          disabled={isSubmitting}
                        >
                          <SelectTrigger className="w-full bg-surface">
                            <SelectValue placeholder="选择提示词 ConfigMap（不选则不启用）" />
                          </SelectTrigger>
                          <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                            <SelectItem value="__none__">不启用</SelectItem>
                            {promptsLoadError ? (
                              <SelectItem value="__error__" disabled>
                                {promptsLoadError}
                              </SelectItem>
                            ) : isLoadingPrompts && promptsConfigMaps.length === 0 ? (
                              <SelectItem value="__loading__" disabled>
                                加载中…
                              </SelectItem>
                            ) : promptsConfigMaps.length === 0 ? (
                              <SelectItem value="__empty__" disabled>
                                暂无可用提示词配置（请先创建 Prompts ConfigMap）
                              </SelectItem>
                            ) : null}
                            {promptsConfigMaps.map((cm) => (
                              <SelectItem key={cm.name} value={cm.name}>
                                {cm.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </FormControl>
                      {(promptsLoadError || promptsConfigMaps.length === 0) && (
                        <div className="text-xs text-content-muted">
                          没有可选项？
                          <Link
                            className="ml-1 text-cta hover:text-cta/90 hover:underline cursor-pointer"
                            href={`/configmaps?namespace=${encodeURIComponent((namespaceValue || "default").trim() || "default")}&type=prompts&create=1`}
                          >
                            去创建 Prompts ConfigMap
                          </Link>
                        </div>
                      )}
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
            </div>

            <DialogFooter className="px-6 py-4 border-t border-line bg-surface-muted/50 mt-0">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={isSubmitting}
              >
                取消
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "创建中..." : "创建数据源"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

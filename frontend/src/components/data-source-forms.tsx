"use client"

import { useEffect, useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import * as z from "zod"
import { ChevronDown, Eye, EyeOff } from "lucide-react"
import { api } from "@/lib/api"
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
  database: z.string().optional(),

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
      if (!v.database?.trim()) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["database"], message: "数据库名必填" })
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
      // data-sinkers MinIO extractor requires extract.files
      if (!v.extractFiles?.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["extractFiles"],
          message: "请填写要抽取的对象列表（每行一个 object key）",
        })
      }
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

type DataSourceFormValues = z.infer<typeof dataSourceSchema>

const defaultFormValues: DataSourceFormValues = {
  name: "",
  namespace: "default",
  type: "mysql",
  host: "",
  port: "3306",
  user: "",
  password: "",
  database: "",
  accessKey: "",
  secretKey: "",
  bucket: "",
  path: "",
  extractFiles: "",
  promptsConfigMapName: "",
  codeRepoType: "",
  codeRepoPath: "",
  codeRepoBranch: "main",
  codeRepoToken: "",
}

// --- Components ---

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

  const loadNamespaces = async () => {
    if (isLoadingNs) return
    setIsLoadingNs(true)
    setNsLoadError(null)
    try {
      const res = await api.get("/namespaces")
      // Interceptor unwraps the response data, so res.data is the payload
      const items = (res.data?.items || res.data?.data?.items || []) as unknown
      const list = Array.isArray(items) ? items : []
      const adapted = list
        .map((x: unknown) => {
          const r = typeof x === "object" && x !== null ? (x as Record<string, unknown>) : {}
          return typeof r.name === "string" ? r.name : ""
        })
        .filter((x) => x)
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

  const loadPromptsConfigMaps = async (namespace: string) => {
    if (isLoadingPrompts) return
    setIsLoadingPrompts(true)
    setPromptsLoadError(null)
    try {
      const ns = (namespace || "default").trim() || "default"
      const res = await api.get(`/namespaces/${ns}/configmaps`, { params: { type: "prompts" } })
      // NOTE: @/lib/api.ts unwraps the standard response envelope `{ code, message, data }`,
      // so `res.data` is already the inner payload: `{ items, totalCount, ... }`.
      const data = (res.data?.data ?? res.data) as unknown
      const r = (typeof data === "object" && data !== null) ? (data as Record<string, unknown>) : {}
      const items = (r.items ?? []) as unknown
      const list = Array.isArray(items) ? items : []
      const adapted = list
        .map((x: unknown) => {
          const r = (typeof x === "object" && x !== null) ? (x as Record<string, unknown>) : {}
          const name = typeof r.name === "string" ? r.name : ""
          return { name }
        })
        .filter((x) => x.name)
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
        <DialogHeader className="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
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
                                  加载中...
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
            
              <div className="space-y-4">
                <div className="text-xs font-semibold text-slate-500">连接配置</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="type"
                    render={({ field }) => (
                      <FormItem>
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
                    )}
                  />
                  {typeValue === "mysql" || typeValue === "postgres" ? (
                    <FormField
                      control={form.control}
                      name="database"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>数据库名</FormLabel>
                          <FormControl>
                            <Input placeholder="例如：corporate_hr" {...field} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  ) : typeValue === "minio" ? (
                    <FormField
                      control={form.control}
                      name="bucket"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Bucket</FormLabel>
                          <FormControl>
                            <Input placeholder="例如：lake" {...field} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  ) : typeValue !== "coderepo" ? (
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

                {typeValue === "minio" || typeValue === "fileserver" ? (
                  <FormField
                    control={form.control}
                    name="extractFiles"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{typeValue === "minio" ? "抽取对象" : "抽取文件列表"}</FormLabel>
                        <FormControl>
                          <Textarea
                            rows={5}
                            placeholder={
                              typeValue === "minio"
                                ? "每行一个 object key（相对 bucket 路径），例如：\nfolder/a.pdf\nerp/exports/customers.csv"
                                : "每行一个文件路径，例如：\n/data/docs/a.pdf\n/data/docs/b.txt"
                            }
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
                                    "absolute right-2 top-1/2 -translate-y-1/2 rounded-sm p-1 text-slate-500 hover:text-slate-700",
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
                                    "absolute right-2 top-1/2 -translate-y-1/2 rounded-sm p-1 text-slate-500 hover:text-slate-700",
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

                {typeValue === "coderepo" ? (
                  <div className="rounded-md border border-slate-200 bg-white p-3 space-y-3">
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
                                <SelectItem value="gitea">Gitea</SelectItem>
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

              <div className="pt-2 border-t border-slate-100">
                <div className="text-xs font-semibold text-slate-500 mb-2">提示词（可选）</div>
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
                          <SelectTrigger className="w-full bg-white">
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
                                加载中...
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
                        <div className="text-xs text-slate-500">
                          没有可选项？
                          <Link
                            className="ml-1 text-blue-600 hover:text-blue-700 hover:underline"
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

            <DialogFooter className="px-6 py-4 border-t border-slate-100 bg-slate-50/50 mt-0">
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

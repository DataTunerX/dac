"use client"

import { useEffect, useMemo, useState } from "react"
import { ChevronDown, ChevronRight, Loader2, Rocket } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { getApiErrorMessage } from "@/lib/api-error"
import type {
  CreateTDBPipelineRunRequest,
  TDBPipelineOptionsResponse,
} from "@/lib/api-types"
import { createTDBPipelineRun } from "@/lib/tdb-pipeline-api"

type SourceType = "s3" | "pvc"

/**
 * Every field the controller's create-run contract accepts. Numeric fields are
 * held as strings so an empty box means "omit it" and the controller applies
 * its own default, rather than DAC sending a 0.
 */
type FormState = {
  targetId: string
  gatewayUrl: string
  domainProfile: string
  sourceType: SourceType
  sourceUri: string
  claimName: string
  path: string
  collection: string
  image: string
  llmProfile: string
  datasetId: string
  sourceVersion: string
  idempotencyKey: string
  forceReingest: boolean
  generateQa: boolean
  autoEval: boolean
  llmGrade: boolean
  autopromote: boolean
  mergeEvery: string
  maxConcurrent: string
  startStaggerSeconds: string
  startStaggerJitterSeconds: string
  questionWorkers: string
  questionRepairTimeoutSeconds: string
  runsPrefix: string
  statusPrefix: string
  attemptStatusPrefix: string
  strict: boolean
  callbackUrl: string
  callbackEvents: string
  metadata: string
}

function initialState(options: TDBPipelineOptionsResponse): FormState {
  const firstNonTest = options.targets.find((t) => !t.test) ?? options.targets[0]
  return {
    targetId: firstNonTest?.id ?? "",
    gatewayUrl: "",
    domainProfile: "",
    sourceType: "s3",
    sourceUri: "",
    claimName: "",
    path: "",
    collection: firstNonTest?.collection || firstNonTest?.domain || options.defaults.collection,
    image: options.defaults.image,
    llmProfile: options.defaults.llm_profile,
    datasetId: "",
    sourceVersion: "",
    idempotencyKey: "",
    forceReingest: false,
    generateQa: true,
    autoEval: true,
    llmGrade: true,
    autopromote: true,
    mergeEvery: "",
    maxConcurrent: "",
    startStaggerSeconds: "",
    startStaggerJitterSeconds: "",
    questionWorkers: "",
    questionRepairTimeoutSeconds: "",
    runsPrefix: options.defaults.runs_prefix,
    statusPrefix: options.defaults.status_prefix,
    attemptStatusPrefix: options.defaults.attempt_status_prefix,
    strict: true,
    callbackUrl: "",
    callbackEvents: "",
    metadata: "",
  }
}

/** Empty box -> undefined so the field is omitted from the request entirely. */
function optionalNumber(raw: string): number | undefined {
  const trimmed = raw.trim()
  if (!trimmed) return undefined
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : undefined
}

function hasInvalidNumber(raw: string): boolean {
  const trimmed = raw.trim()
  return trimmed !== "" && !Number.isFinite(Number(trimmed))
}

type TDBPipelineCreateDialogProps = {
  open: boolean
  options: TDBPipelineOptionsResponse | undefined
  onOpenChange: (open: boolean) => void
  /** Called after the controller accepts the run so the list can refresh. */
  onCreated: () => void
}

/**
 * Create-run dialog. Picking a target and a source is enough to submit: the
 * gateway, domain profile and artifact prefixes come from the deployment's
 * configuration and the idempotency key is derived server-side. Everything else
 * the controller accepts is available under 高级选项.
 */
export function TDBPipelineCreateDialog({
  open,
  options,
  onOpenChange,
  onCreated,
}: TDBPipelineCreateDialogProps) {
  const [form, setForm] = useState<FormState | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  useEffect(() => {
    if (open && options) setForm(initialState(options))
    if (!open) {
      setForm(null)
      setAdvancedOpen(false)
    }
  }, [open, options])

  const selectedTarget = useMemo(
    () => options?.targets.find((t) => t.id === form?.targetId),
    [options, form?.targetId]
  )

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  /**
   * Changing the target also re-derives the collection, because the collection
   * shapes stream IDs and the artifact path -- carrying "academic_papers" over
   * to a museum target would file the content in the wrong place.
   */
  function selectTarget(targetId: string) {
    const next = options?.targets.find((t) => t.id === targetId)
    setForm((prev) =>
      prev
        ? {
            ...prev,
            targetId,
            collection: next?.collection || next?.domain || prev.collection,
          }
        : prev
    )
  }

  function validate(state: FormState): string | null {
    if (!state.targetId) return "请选择入库目标"
    if (state.sourceType === "s3") {
      if (!state.sourceUri.trim().startsWith("s3://")) {
        return "源地址需为 s3:// 开头的对象或前缀"
      }
    } else {
      if (!state.claimName.trim()) return "请填写源 PVC 名称"
      if (!state.path.trim().startsWith("/")) return "PVC 路径需为绝对路径"
    }
    if (!state.collection.trim()) return "请填写集合名称"

    const numericFields: Array<[string, string]> = [
      ["开放层谓词合并间隔", state.mergeEvery],
      ["最大并发", state.maxConcurrent],
      ["启动错峰秒数", state.startStaggerSeconds],
      ["启动错峰抖动秒数", state.startStaggerJitterSeconds],
      ["问题并发数", state.questionWorkers],
      ["单题修复超时", state.questionRepairTimeoutSeconds],
    ]
    for (const [label, raw] of numericFields) {
      if (hasInvalidNumber(raw)) return `${label}需为数字`
    }

    if (state.metadata.trim()) {
      try {
        const parsed = JSON.parse(state.metadata)
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          return "元数据需为 JSON 对象"
        }
      } catch {
        return "元数据不是合法的 JSON"
      }
    }
    return null
  }

  function buildBody(state: FormState): CreateTDBPipelineRunRequest {
    const metadata: Record<string, unknown> = {
      submittedFrom: "dac-data-management",
      sourceKind: state.sourceType,
    }
    if (state.metadata.trim()) {
      Object.assign(metadata, JSON.parse(state.metadata) as Record<string, unknown>)
    }

    const events = state.callbackEvents
      .split(",")
      .map((e) => e.trim())
      .filter(Boolean)

    return {
      source:
        state.sourceType === "s3"
          ? { type: "s3", uri: state.sourceUri.trim() }
          : { type: "pvc", claim_name: state.claimName.trim(), path: state.path.trim() },
      target: {
        target_id: state.targetId,
        gateway_url: state.gatewayUrl.trim() || undefined,
        domain_profile: state.domainProfile.trim() || undefined,
      },
      collection: state.collection.trim(),
      image: state.image,
      options: {
        llm_profile: state.llmProfile,
        generate_qa: state.generateQa,
        auto_eval: state.autoEval,
        llm_grade: state.llmGrade,
        open_layer_predicate_autopromote: state.autopromote,
        open_layer_predicate_merge_every: optionalNumber(state.mergeEvery),
        max_concurrent: optionalNumber(state.maxConcurrent),
        start_stagger_seconds: optionalNumber(state.startStaggerSeconds),
        start_stagger_jitter_seconds: optionalNumber(state.startStaggerJitterSeconds),
        question_workers: optionalNumber(state.questionWorkers),
        question_repair_timeout_seconds: optionalNumber(state.questionRepairTimeoutSeconds),
      },
      artifact_upload: {
        runs_prefix: state.runsPrefix.trim(),
        status_prefix: state.statusPrefix.trim(),
        attempt_status_prefix: state.attemptStatusPrefix.trim(),
        strict: state.strict,
      },
      callback: state.callbackUrl.trim()
        ? { url: state.callbackUrl.trim(), events: events.length ? events : undefined }
        : undefined,
      metadata,
      dataset_id: state.datasetId.trim() || undefined,
      source_version: state.sourceVersion.trim() || undefined,
      // The controller dedupes on the idempotency key, so re-submitting an
      // unchanged source normally returns the original run. A unique key is
      // what makes it actually run again.
      idempotency_key:
        state.idempotencyKey.trim() ||
        (state.forceReingest ? `force-${Date.now()}-${state.targetId}` : undefined),
    }
  }

  async function handleSubmit() {
    if (!form) return
    const problem = validate(form)
    if (problem) {
      toast.error(problem)
      return
    }

    setSubmitting(true)
    try {
      const run = await createTDBPipelineRun(buildBody(form))
      toast.success(`任务已提交：${run.run_id}`)
      onOpenChange(false)
      onCreated()
    } catch (err) {
      toast.error(getApiErrorMessage(err, "提交入库任务失败"))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Flex column with only the middle scrolling, so the submit footer stays reachable. */}
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader className="shrink-0 border-b border-line bg-surface pb-4">
          <DialogTitle>新建 TDB 入库任务</DialogTitle>
          <DialogDescription>
            提交后由 TDB Pipeline Controller 异步执行，可在列表中查看进度、暂停或重试。
          </DialogDescription>
        </DialogHeader>

        {!form || !options ? (
          <div className="flex flex-1 items-center justify-center py-10 text-content-muted">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : (
          <div className="flex-1 space-y-5 overflow-y-auto px-6 py-4">
            <div className="space-y-2">
              <Label>入库目标</Label>
              <Select value={form.targetId} onValueChange={selectTarget}>
                <SelectTrigger>
                  <SelectValue placeholder="选择领域" />
                </SelectTrigger>
                <SelectContent>
                  {options.targets.map((target) => (
                    <SelectItem key={target.id} value={target.id}>
                      {target.label}
                      {target.test ? "（测试）" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedTarget ? (
                <p className="text-xs text-content-muted">
                  网关 {selectedTarget.gateway_url}
                  {selectedTarget.skill_agent
                    ? ` · 与技能 ${selectedTarget.skill_agent} 共用同一 TDB`
                    : " · 暂无对应技能"}
                </p>
              ) : null}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>源类型</Label>
                <Select
                  value={form.sourceType}
                  onValueChange={(v) => update("sourceType", v as SourceType)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="s3">S3 / MinIO</SelectItem>
                    <SelectItem value="pvc">PVC</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="tdb-collection">集合名称</Label>
                <Input
                  id="tdb-collection"
                  value={form.collection}
                  onChange={(e) => update("collection", e.target.value)}
                />
              </div>
            </div>

            {form.sourceType === "s3" ? (
              <div className="space-y-2">
                <Label htmlFor="tdb-source-uri">源地址</Label>
                <Input
                  id="tdb-source-uri"
                  placeholder="s3://archaeology-source/papers/ActaAnthropologicaSinica/"
                  value={form.sourceUri}
                  onChange={(e) => update("sourceUri", e.target.value)}
                />
                <p className="text-xs text-content-muted">非 .md 结尾的地址按前缀批量处理。</p>
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="tdb-claim">源 PVC</Label>
                  <Input
                    id="tdb-claim"
                    value={form.claimName}
                    onChange={(e) => update("claimName", e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="tdb-path">PVC 内绝对路径</Label>
                  <Input
                    id="tdb-path"
                    placeholder="/data/papers"
                    value={form.path}
                    onChange={(e) => update("path", e.target.value)}
                  />
                </div>
              </div>
            )}

            <ToggleRow
              id="tdb-force"
              label="强制重新入库（同一来源已入库过时仍再跑一次）"
              checked={form.forceReingest}
              onChange={(v) => update("forceReingest", v)}
            />

            <div>
              <button
                type="button"
                onClick={() => setAdvancedOpen((v) => !v)}
                className="flex items-center gap-1 text-sm font-medium text-content-muted hover:text-content cursor-pointer"
              >
                {advancedOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                高级选项
              </button>
            </div>

            {advancedOpen ? (
              <div className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label>流水线镜像</Label>
                    <Select value={form.image} onValueChange={(v) => update("image", v)}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {options.images.map((image) => (
                          <SelectItem key={image} value={image}>
                            {image.split("/").pop()}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>LLM 配置</Label>
                    <Select value={form.llmProfile} onValueChange={(v) => update("llmProfile", v)}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {options.llm_profiles.map((profile) => (
                          <SelectItem key={profile} value={profile}>
                            {profile}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
            <fieldset className="space-y-3 rounded-lg border border-line p-4">
                  <legend className="px-1 text-sm font-medium text-content">流水线选项</legend>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <ToggleRow id="tdb-generate-qa" label="生成 QA 集" checked={form.generateQa} onChange={(v) => update("generateQa", v)} />
                    <ToggleRow id="tdb-auto-eval" label="自动评估与修复" checked={form.autoEval} onChange={(v) => update("autoEval", v)} />
                    <ToggleRow id="tdb-llm-grade" label="LLM 评分" checked={form.llmGrade} onChange={(v) => update("llmGrade", v)} />
                    <ToggleRow id="tdb-autopromote" label="开放层谓词自动提升" checked={form.autopromote} onChange={(v) => update("autopromote", v)} />
                  </div>
                </fieldset>
            <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="tdb-dataset">数据集标识（可选）</Label>
                    <Input
                      id="tdb-dataset"
                      placeholder="用于生成幂等键，留空则取源地址"
                      value={form.datasetId}
                      onChange={(e) => update("datasetId", e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="tdb-version">源版本（可选）</Label>
                    <Input
                      id="tdb-version"
                      placeholder="ETag 或修订号，源内容变化时更新"
                      value={form.sourceVersion}
                      onChange={(e) => update("sourceVersion", e.target.value)}
                    />
                  </div>
                </div>
            <fieldset className="space-y-3 rounded-lg border border-line p-4">
                  <legend className="px-1 text-sm font-medium text-content">产物上传</legend>
                  <div className="space-y-2">
                    <Label htmlFor="tdb-runs-prefix">运行产物前缀</Label>
                    <Input id="tdb-runs-prefix" value={form.runsPrefix} onChange={(e) => update("runsPrefix", e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="tdb-status-prefix">状态前缀</Label>
                    <Input id="tdb-status-prefix" value={form.statusPrefix} onChange={(e) => update("statusPrefix", e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="tdb-attempt-prefix">单次尝试状态前缀</Label>
                    <Input id="tdb-attempt-prefix" value={form.attemptStatusPrefix} onChange={(e) => update("attemptStatusPrefix", e.target.value)} />
                  </div>
                  <ToggleRow
                    id="tdb-strict"
                    label="严格上传（strict，控制器尚未接线）"
                    checked={form.strict}
                    onChange={(v) => update("strict", v)}
                  />
                </fieldset>
                <fieldset className="space-y-3 rounded-lg border border-line p-4">
                  <legend className="px-1 text-sm font-medium text-content">目标覆盖</legend>
                  <p className="text-xs text-content-muted">
                    留空则使用所选目标的配置。填写的网关必须在 DAC 与控制器的白名单内。
                  </p>
                  <div className="space-y-2">
                    <Label htmlFor="tdb-gateway">网关地址</Label>
                    <Input
                      id="tdb-gateway"
                      placeholder={selectedTarget?.gateway_url ?? "http://10.124.48.91:8989"}
                      value={form.gatewayUrl}
                      onChange={(e) => update("gatewayUrl", e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="tdb-profile">领域配置路径</Label>
                    <Input
                      id="tdb-profile"
                      placeholder={selectedTarget?.domain_profile ?? "pipeline/profiles/archeology.v2.json"}
                      value={form.domainProfile}
                      onChange={(e) => update("domainProfile", e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="tdb-idempotency">幂等键覆盖</Label>
                    <Input
                      id="tdb-idempotency"
                      placeholder="留空则由服务端按 数据集:源版本:领域:集合 生成"
                      value={form.idempotencyKey}
                      onChange={(e) => update("idempotencyKey", e.target.value)}
                    />
                  </div>
                </fieldset>

                <fieldset className="space-y-3 rounded-lg border border-line p-4">
                  <legend className="px-1 text-sm font-medium text-content">调度与并发</legend>
                  <p className="text-xs text-content-muted">
                    留空使用控制器默认值。并发与错峰参数控制器当前只存储、尚未生效，实际上限为
                    集群 4 / 每领域 2 / 每运行 2。
                  </p>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <NumberField id="tdb-merge-every" label="开放层谓词合并间隔" placeholder="1" value={form.mergeEvery} onChange={(v) => update("mergeEvery", v)} />
                    <NumberField id="tdb-max-concurrent" label="最大并发（暂未生效）" placeholder="2" value={form.maxConcurrent} onChange={(v) => update("maxConcurrent", v)} />
                    <NumberField id="tdb-stagger" label="启动错峰秒数（暂未生效）" placeholder="300" value={form.startStaggerSeconds} onChange={(v) => update("startStaggerSeconds", v)} />
                    <NumberField id="tdb-stagger-jitter" label="错峰抖动秒数（暂未生效）" placeholder="60" value={form.startStaggerJitterSeconds} onChange={(v) => update("startStaggerJitterSeconds", v)} />
                    <NumberField id="tdb-question-workers" label="问题并发数" placeholder="控制器默认" value={form.questionWorkers} onChange={(v) => update("questionWorkers", v)} />
                    <NumberField id="tdb-question-timeout" label="单题修复超时（秒）" placeholder="控制器默认" value={form.questionRepairTimeoutSeconds} onChange={(v) => update("questionRepairTimeoutSeconds", v)} />
                  </div>
                </fieldset>

                <fieldset className="space-y-3 rounded-lg border border-line p-4">
                  <legend className="px-1 text-sm font-medium text-content">回调</legend>
                  <p className="text-xs text-content-muted">
                    控制器的回调域名白名单默认拒绝；未加入白名单时填写会导致提交返回 403。留空则由 DAC 轮询状态。
                  </p>
                  <div className="space-y-2">
                    <Label htmlFor="tdb-callback-url">回调地址</Label>
                    <Input
                      id="tdb-callback-url"
                      placeholder="http://dac-apiserver.dac.svc.cluster.local/api/v1/..."
                      value={form.callbackUrl}
                      onChange={(e) => update("callbackUrl", e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="tdb-callback-events">回调事件（逗号分隔，留空为全部）</Label>
                    <Input
                      id="tdb-callback-events"
                      value={form.callbackEvents}
                      onChange={(e) => update("callbackEvents", e.target.value)}
                    />
                  </div>
                </fieldset>

                <div className="space-y-2">
                  <Label htmlFor="tdb-metadata">元数据（JSON 对象，可选）</Label>
                  <Textarea
                    id="tdb-metadata"
                    rows={4}
                    className="font-mono text-xs"
                    placeholder={'{\n  "sourceBucket": "archaeology-source",\n  "llmModel": "gpt-5.6-luna"\n}'}
                    value={form.metadata}
                    onChange={(e) => update("metadata", e.target.value)}
                  />
                </div>
              </div>
            ) : null}
          </div>
        )}

        <DialogFooter className="shrink-0 border-t border-line">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={submitting || !form}>
            {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Rocket className="mr-2 h-4 w-4" />}
            提交任务
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function NumberField({
  id,
  label,
  placeholder,
  value,
  onChange,
}: {
  id: string
  label: string
  placeholder?: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        inputMode="numeric"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}

function ToggleRow({
  id,
  label,
  checked,
  onChange,
}: {
  id: string
  label: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <input
        id={id}
        type="checkbox"
        className="h-4 w-4 rounded border-line accent-brand"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <Label htmlFor={id} className="cursor-pointer text-sm font-normal">
        {label}
      </Label>
    </div>
  )
}

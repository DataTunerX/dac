"use client"

import { useEffect, useState, useMemo, useRef } from "react"
import useSWR from "swr"
import { useForm, useWatch } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import * as z from "zod"
import { Loader2, X, Zap } from "lucide-react"
import { toast } from "sonner"

import { api } from "@/lib/api"
import { listNamespaces } from "@/lib/namespaces-api"
import { listAllDescriptors } from "@/lib/descriptors-api"
import { listSemanticGroups } from "@/lib/semantic-groups-api"
import { listConfigMaps } from "@/lib/configmaps-api"
import {
  listSkillNamespaces,
  listSkills,
  getSkill,
} from "@/lib/skills-api"
import type {
  NamespaceListResponse,
  DataDescriptorResponse,
  SemanticGroupResponse,
  ConfigMapResponse,
  AgentCardResponse,
  AgentSkillResponse,
  SkillRef,
  SkillPolicy,
  SkillInfoResponse,
  SkillNamespaceResponse,
} from "@/lib/api-types"
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
import { Badge } from "@/components/ui/badge"

const formSchema = z
  .object({
    name: z.string().min(2, "名称至少 2 个字符"),
    namespace: z.string().min(1, "命名空间必填"),
    description: z.string().optional(),
    dataSourceType: z.enum(["descriptor", "semantic-group", "skill"]),
    dataSourceId: z.string().optional(),
    // skill 类型只用 expertModel；plannerModel 提交时同步同值以满足 CRD 必填
    plannerModel: z.string().optional(),
    expertModel: z.string().optional(),
    expertAgentMaxSteps: z.string().optional(),
    orchestratorAgentMaxLoops: z.string().optional(),
  })
  .superRefine((data, ctx) => {
    // skill 类型不绑定 DD/SG，无需 dataSourceId
    if (data.dataSourceType !== "skill" && !(data.dataSourceId || "").trim()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "请选择数据源",
        path: ["dataSourceId"],
      })
    }
    if (data.dataSourceType === "skill") {
      if (!(data.expertModel || "").trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "请选择模型",
          path: ["expertModel"],
        })
      }
    } else {
      if (!(data.plannerModel || "").trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "请选择规划模型",
          path: ["plannerModel"],
        })
      }
      if (!(data.expertModel || "").trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "请选择专家模型",
          path: ["expertModel"],
        })
      }
    }
  })

type FormValues = z.infer<typeof formSchema>

export type CreateAgentPayload = FormValues & {
  skills: Skill[]
  expertAgentMaxSteps?: string
  orchestratorAgentMaxLoops?: string
  /** Dedicated skill binding or normal/DS DAC local attachments. */
  skillPolicy?: SkillPolicy
}

type Skill = {
  id: string
  name: string
  description: string
  tags: string
  examples: string
}

type DataDescriptor = {
  id: string
  name: string
  namespace: string
  descriptorType: string
  phase: string
}

type LLMConfig = {
  name: string
  data: Record<string, unknown> | undefined
}

type SemanticGroup = {
  id: string
  group_name: string
  agent_card?: string
}

/** Map API skill shape (or parsed JSON) to form Skill; returns null if invalid */
function skillFromRaw(s: AgentSkillResponse | Record<string, unknown>): Skill | null {
  const raw = typeof s === "object" && s !== null ? s : {}
  const r = raw as Record<string, unknown>
  const id = (typeof r.id === "string" ? r.id : "").trim()
  const name = (typeof r.name === "string" ? r.name : "").trim()
  const description = (typeof r.description === "string" ? r.description : "").trim()
  const tagsRaw = r.tags
  const tags = Array.isArray(tagsRaw)
    ? tagsRaw.filter((t): t is string => typeof t === "string").join(",")
    : typeof tagsRaw === "string"
      ? tagsRaw
      : ""
  const examplesRaw = r.examples
  const examples = Array.isArray(examplesRaw)
    ? examplesRaw.filter((e): e is string => typeof e === "string").join("\n")
    : typeof examplesRaw === "string"
      ? examplesRaw
      : ""
  const finalId = id || name
  const finalName = name || finalId
  if (finalId || finalName) {
    return { id: finalId, name: finalName, description, tags, examples }
  }
  return null
}

export function CreateAgentDialog({
  open,
  onOpenChange,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (data: CreateAgentPayload) => Promise<void>
}) {
  const [dataDescriptors, setDataDescriptors] = useState<DataDescriptor[]>([])
  const [semanticGroups, setSemanticGroups] = useState<SemanticGroup[]>([])
  const [isLoadingDD, setIsLoadingDD] = useState(false)
  const [isLoadingSG, setIsLoadingSG] = useState(false)
  const [ddError, setDdError] = useState<string | null>(null)
  const [sgError, setSgError] = useState<string | null>(null)

  // skill DAC: skillPolicy 为可编辑绑定；agentCard.skills 由 detail 派生只读
  const [skillPolicySkills, setSkillPolicySkills] = useState<SkillRef[]>([])
  const [skillHubNamespaces, setSkillHubNamespaces] = useState<SkillNamespaceResponse[]>([])
  const [skillPickerNs, setSkillPickerNs] = useState("default")
  const [skillCatalog, setSkillCatalog] = useState<SkillInfoResponse[]>([])
  const [isLoadingSkillNs, setIsLoadingSkillNs] = useState(false)
  const [isLoadingSkillCatalog, setIsLoadingSkillCatalog] = useState(false)
  const [skillCatalogError, setSkillCatalogError] = useState<string | null>(null)
  const [skillDetailLoading, setSkillDetailLoading] = useState(false)
  const [skillDetailFailed, setSkillDetailFailed] = useState(false)
  const [skillDetailErrorMsg, setSkillDetailErrorMsg] = useState<string | null>(null)
  const [localAttachmentsEnabled, setLocalAttachmentsEnabled] = useState(false)

  // Namespaces: SWR when dialog open for dedup/cache with configmaps page
  const { data: nsData, isLoading: isLoadingNs } = useSWR<NamespaceListResponse>(
    open ? "/namespaces" : null,
    () => listNamespaces()
  )
  const namespaces = useMemo(() => nsData?.items?.map((n) => n.name) ?? [], [nsData])

  const [isSubmitting, setIsSubmitting] = useState(false)
  const [sourceOpen, setSourceOpen] = useState(false)

  const [skills, setSkills] = useState<Skill[]>([
    {
      id: "GeneralQA",
      name: "GeneralQA",
      description: "通用问答能力",
      tags: "qa",
      examples: "帮我分析这份数据",
    },
  ])

  const [llmConfigs, setLlmConfigs] = useState<LLMConfig[]>([])
  const [isLoadingLLM, setIsLoadingLLM] = useState(false)
  const [llmError, setLlmError] = useState<string | null>(null)

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      name: "",
      plannerModel: "",
      expertModel: "",
      namespace: "default",
      dataSourceType: "descriptor",
      dataSourceId: "",
      description: "",
      expertAgentMaxSteps: "1",
      orchestratorAgentMaxLoops: "0",
    },
  })
  const resetAll = () => {
    setSourceOpen(false)
    lastAutoName.current = ""
    lastAutoDesc.current = ""
    setFingerprintState({ key: "", status: "idle" })
    setSkillPolicySkills([])
    setLocalAttachmentsEnabled(false)
    setSkillPickerNs("default")
    setSkillCatalog([])
    setSkillCatalogError(null)
    setSkillDetailFailed(false)
    setSkillDetailErrorMsg(null)
    setSkillVersionsByKey({})
    setSkills([
      {
        id: "GeneralQA",
        name: "GeneralQA",
        description: "通用问答能力",
        tags: "qa",
        examples: "帮我分析这份数据",
      },
    ])
    setNameTouched(false)
    setDescTouched(false)
    form.reset({
      name: "",
      plannerModel: "",
      expertModel: "",
      namespace: "default",
      dataSourceType: "descriptor",
      dataSourceId: "",
      description: "",
      expertAgentMaxSteps: "1",
      orchestratorAgentMaxLoops: "0",
    })
  }

  const handleOpenChange = (next: boolean) => {
    if (!next) resetAll()
    onOpenChange(next)
  }

  const namespace = useWatch({ control: form.control, name: "namespace" })
  const dataSourceType = useWatch({ control: form.control, name: "dataSourceType" })
  const plannerModel = useWatch({ control: form.control, name: "plannerModel" })
  const expertModel = useWatch({ control: form.control, name: "expertModel" })
  const name = useWatch({ control: form.control, name: "name" })
  const description = useWatch({ control: form.control, name: "description" })
  const dataSourceId = useWatch({ control: form.control, name: "dataSourceId" })

  // State for user interaction tracking (to avoid overwriting user input)
  const [nameTouched, setNameTouched] = useState(false)
  const [descTouched, setDescTouched] = useState(false)
  const lastAutoName = useRef("")
  const lastAutoDesc = useRef("")
  const lastErrorRef = useRef("")

  const [fingerprintState, setFingerprintState] = useState<{
    key: string
    status: "idle" | "loading" | "ready" | "error"
    error?: string
    agentCard?: { name?: string; description?: string }
    rawAgentCard?: string
  }>({ key: "", status: "idle" })

  /** availableVersions keyed by `${namespace}/${name}` for version picker */
  const [skillVersionsByKey, setSkillVersionsByKey] = useState<Record<string, string[]>>({})

  useEffect(() => {
    if (!open) return
    if (dataSourceType === "descriptor") {
      form.setValue("orchestratorAgentMaxLoops", "0", { shouldDirty: false, shouldTouch: false })
      form.setValue("expertAgentMaxSteps", "1", { shouldDirty: false, shouldTouch: false })
    } else if (dataSourceType === "skill") {
      // skill 单容器默认：与设计示例对齐
      // maxSteps=30：skill 的 ReAct 循环（检索 → 深挖 → provenance → 扩展轮次 → 归纳）
      // 通常需要 20+ 步；10 会在归纳前触发 max_steps_exceeded，导致 skill 被判定失败并
      // 从候选中剔除，最终整体 declined。
      form.setValue("orchestratorAgentMaxLoops", "2", { shouldDirty: false, shouldTouch: false })
      form.setValue("expertAgentMaxSteps", "30", { shouldDirty: false, shouldTouch: false })
    } else {
      form.setValue("orchestratorAgentMaxLoops", "1", { shouldDirty: false, shouldTouch: false })
      form.setValue("expertAgentMaxSteps", "1", { shouldDirty: false, shouldTouch: false })
    }
  }, [open, dataSourceType, form])

  // Enter skill branch: clear DD/SG-derived skills; AgentCard skills filled from hub detail only
  useEffect(() => {
    if (!open || dataSourceType !== "skill") return
    setSkills([])
    setFingerprintState({ key: "", status: "idle" })
    form.setValue("dataSourceId", "", { shouldDirty: false })
    if (!form.getValues("namespace")) {
      form.setValue("namespace", "default", { shouldValidate: true })
    }
  }, [open, dataSourceType]) // eslint-disable-line react-hooks/exhaustive-deps

  const selectedPlannerModel: string = String(llmConfigs.find((c) => c.name === plannerModel)?.data?.model ?? "")
  const selectedExpertModel: string = String(llmConfigs.find((c) => c.name === expertModel)?.data?.model ?? "")

  const targetDataSource = useMemo(() => {
    if (!dataSourceId || dataSourceType === "skill") return ""
    if (dataSourceType === "descriptor") {
      const dd = dataDescriptors.find((d) => d.id === dataSourceId)
      if (!dd) return ""
      const ns = (dd.namespace || "default").trim() || "default"
      const name = dd.name
      return `descriptor:${ns}/${name}`
    } else {
      const sg = semanticGroups.find((s) => s.id === dataSourceId)
      if (!sg) return ""
      return `semantic-group:${sg.id}`
    }
  }, [dataSourceId, dataSourceType, dataDescriptors, semanticGroups])

  const fingerprintError = fingerprintState.key === targetDataSource ? fingerprintState.error : ""
  const isFingerprintLoading = fingerprintState.key === targetDataSource && fingerprintState.status === "loading"

  const selectedSkillKeySet = useMemo(() => {
    return new Set(skillPolicySkills.map((s) => `${s.namespace}/${s.name}`))
  }, [skillPolicySkills])

  const loadSkillNamespaces = async () => {
    if (isLoadingSkillNs) return
    setIsLoadingSkillNs(true)
    try {
      const res = await listSkillNamespaces()
      const items = res.items ?? []
      setSkillHubNamespaces(items)
      if (items.length > 0 && !items.find((n) => n.id === skillPickerNs)) {
        setSkillPickerNs(items[0]?.id || "default")
      }
    } catch (err) {
      console.error("Failed to list skill namespaces:", err)
      setSkillHubNamespaces([])
    } finally {
      setIsLoadingSkillNs(false)
    }
  }

  const loadSkillCatalog = async (ns: string) => {
    setIsLoadingSkillCatalog(true)
    setSkillCatalogError(null)
    try {
      const res = await listSkills(ns)
      setSkillCatalog(res.items ?? [])
    } catch (err) {
      console.error("Failed to list skills:", err)
      setSkillCatalog([])
      setSkillCatalogError("技能列表加载失败，请稍后重试")
    } finally {
      setIsLoadingSkillCatalog(false)
    }
  }

  // Load Skill Hub catalog for a dedicated skill DAC or optional local attachments.
  useEffect(() => {
    if (!open || (dataSourceType !== "skill" && !localAttachmentsEnabled)) return
    void loadSkillNamespaces()
  }, [open, dataSourceType, localAttachmentsEnabled]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (
      !open ||
      (dataSourceType !== "skill" && !localAttachmentsEnabled) ||
      !skillPickerNs
    ) return
    void loadSkillCatalog(skillPickerNs)
  }, [open, dataSourceType, localAttachmentsEnabled, skillPickerNs]) // eslint-disable-line react-hooks/exhaustive-deps

  // skillPolicy → agentCard.skills：对每个 SkillRef 拉 hub detail；失败则阻止提交
  useEffect(() => {
    if (!open || dataSourceType !== "skill") return

    if (skillPolicySkills.length === 0) {
      setSkills([])
      setSkillDetailFailed(false)
      setSkillDetailErrorMsg(null)
      setSkillDetailLoading(false)
      return
    }

    let cancelled = false
    setSkillDetailLoading(true)
    setSkillDetailFailed(false)
    setSkillDetailErrorMsg(null)

    ;(async () => {
      const nextSkills: Skill[] = []
      let failed = false
      let failMsg: string | null = null

      for (const ref of skillPolicySkills) {
        try {
          const detail = await getSkill(
            ref.namespace,
            ref.name,
            ref.version || undefined
          )
          if (cancelled) return
          const key = `${ref.namespace}/${ref.name}`
          if (detail.availableVersions?.length) {
            setSkillVersionsByKey((prev) => ({
              ...prev,
              [key]: detail.availableVersions,
            }))
          }
          nextSkills.push({
            id: detail.name || ref.name,
            name: detail.name || ref.name,
            description: detail.description || "",
            tags: "",
            examples: "",
          })
        } catch (err) {
          // Frontend: detail 拉取失败导致无法联动 AgentCard
          console.error(
            `skill detail fetch failed for ${ref.namespace}/${ref.name}@${ref.version || "latest"}:`,
            err
          )
          failed = true
          failMsg = `技能详情加载失败：${ref.namespace}/${ref.name}（无法联动 AgentCard skills）`
          break
        }
      }

      if (cancelled) return

      if (failed) {
        setSkillDetailFailed(true)
        setSkillDetailErrorMsg(failMsg)
        setSkills([])
        toast.error(failMsg || "技能详情加载失败")
      } else {
        setSkillDetailFailed(false)
        setSkillDetailErrorMsg(null)
        setSkills(nextSkills)
      }
      setSkillDetailLoading(false)
    })()

    return () => {
      cancelled = true
    }
  }, [open, dataSourceType, skillPolicySkills])

  const addSkillRef = (skill: SkillInfoResponse) => {
    // 同一 DAC 内 SkillRef.name 必须唯一（跨 namespace 也不允许重名）
    const dup = skillPolicySkills.find((s) => s.name === skill.name)
    if (dup) {
      toast.error(
        `技能名「${skill.name}」已选择（来自 ${dup.namespace}），同一智能体内不允许重名`
      )
      return
    }
    const ns = skill.namespace || skillPickerNs
    const key = `${ns}/${skill.name}`
    setSkillVersionsByKey((prev) => ({
      ...prev,
      [key]: skill.availableVersions ?? [],
    }))
    setSkillPolicySkills((prev) => [
      ...prev,
      {
        namespace: ns,
        name: skill.name,
        version: "",
      },
    ])
  }

  const removeSkillRef = (skillName: string, skillNs: string) => {
    const key = `${skillNs}/${skillName}`
    setSkillVersionsByKey((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
    setSkillPolicySkills((prev) =>
      prev.filter((s) => !(s.name === skillName && s.namespace === skillNs))
    )
  }

  const updateSkillRefVersion = (skillName: string, skillNs: string, version: string) => {
    setSkillPolicySkills((prev) =>
      prev.map((s) =>
        s.name === skillName && s.namespace === skillNs ? { ...s, version } : s
      )
    )
  }

  // Load Data Descriptors
  const loadDataDescriptors = async () => {
    if (isLoadingDD) return
    setIsLoadingDD(true)
    setDdError(null)
    try {
      const items = await listAllDescriptors()
      const mapped: DataDescriptor[] = items.map((item: DataDescriptorResponse) => ({
        id: item.name ?? "",
        name: item.name ?? "",
        namespace: item.namespace ?? "",
        descriptorType: item.descriptor_type ?? "",
        phase: item.overall_phase ?? "",
      })).filter((item) => item.id)
      setDataDescriptors(mapped)
    } catch (err) {
      console.error("Failed to fetch data descriptors:", err)
      setDataDescriptors([])
      setDdError("数据源加载失败，请稍后重试")
    } finally {
      setIsLoadingDD(false)
    }
  }

  // Load Semantic Groups
  const loadSemanticGroups = async () => {
    if (isLoadingSG) return
    setIsLoadingSG(true)
    setSgError(null)
    try {
      const { items } = await listSemanticGroups({ limit: 1000, offset: 0 })
      const adapted = items.map((item: SemanticGroupResponse) => ({
        id: String(item.id ?? ""),
        group_name: String(item.group_name ?? ""),
        agent_card: typeof (item as SemanticGroupResponse & { agent_card?: string }).agent_card === "string"
          ? (item as SemanticGroupResponse & { agent_card?: string }).agent_card
          : undefined,
      })).filter((s) => s.id)
      setSemanticGroups(adapted)
    } catch (err) {
      console.error("Failed to fetch semantic groups:", err)
      setSemanticGroups([])
      setSgError("语义组加载失败，请稍后重试")
    } finally {
      setIsLoadingSG(false)
    }
  }

  // Load LLM ConfigMaps
  const loadLlmConfigs = async (ns: string) => {
    if (isLoadingLLM) return
    setIsLoadingLLM(true)
    setLlmError(null)
    try {
      const namespace = (ns || "default").trim() || "default"
      const { items } = await listConfigMaps(namespace, { type: "llm" })
      const list: LLMConfig[] = items.map((item: ConfigMapResponse) => ({
        name: item.name ?? "",
        data: item.data as Record<string, unknown> | undefined,
      })).filter((i) => i.name)
      setLlmConfigs(list)
      
      // Default both planner and expert to the same first available ConfigMap.
      if (list.length > 0) {
        const first = list[0]?.name || ""
        const currentPlanner = form.getValues("plannerModel")
        const currentExpert = form.getValues("expertModel")
        if (!currentPlanner || !list.find((c) => c.name === currentPlanner)) {
          form.setValue("plannerModel", first)
        }
        if (!currentExpert || !list.find((c) => c.name === currentExpert)) {
          form.setValue("expertModel", first)
        }
      }
    } catch (err) {
      console.error("Failed to load LLM configmaps", err)
      setLlmConfigs([])
      setLlmError("模型配置加载失败，请稍后重试")
    } finally {
      setIsLoadingLLM(false)
    }
  }

  // Initialize: run independent fetches in parallel (namespaces via SWR when open)
  useEffect(() => {
    if (!open) return
    void Promise.all([
      loadDataDescriptors(),
      loadSemanticGroups(),
      loadLlmConfigs(namespace || "default"),
    ]).catch(() => {
      // Each load* already sets error state; avoid unhandled rejection
    })
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  // When dataSourceId changes, update namespace field
  useEffect(() => {
    if (!open || !dataSourceId) return
    
    // If semantic group, default to 'default' or let user choose (currently default)
    if (dataSourceType === "semantic-group") {
        if (!namespace) {
            form.setValue("namespace", "default", { shouldValidate: true })
        }
        return
    }

    const dd = dataDescriptors.find((d) => d.id === dataSourceId)
    const ns = (dd?.namespace || "default").trim() || "default"
    if (ns !== (namespace || "").trim()) {
      form.setValue("namespace", ns, { shouldValidate: true })
    }
  }, [open, dataSourceId, dataSourceType, dataDescriptors]) // eslint-disable-line react-hooks/exhaustive-deps

  // When namespace changes, reload LLM configs
  useEffect(() => {
    if (open) {
      loadLlmConfigs(namespace || "default")
    }
  }, [open, namespace]) // eslint-disable-line react-hooks/exhaustive-deps

  // Repair invalid selections when namespace LLM list changes; default both to the same first CM.
  useEffect(() => {
    if (!open) return
    if (llmConfigs.length === 0) return

    const names = new Set(llmConfigs.map((c) => c.name))
    const first = llmConfigs[0]?.name || ""
    if (!first) return

    if (!names.has(plannerModel || "")) {
      form.setValue("plannerModel", first, { shouldValidate: true, shouldDirty: false })
    }
    if (!expertModel || !names.has(expertModel)) {
      form.setValue("expertModel", first, { shouldValidate: true, shouldDirty: false })
    }
  }, [open, llmConfigs, plannerModel, expertModel, form])

  // Fetch SemanticDomain.agent_card when targetDataSource changes
  useEffect(() => {
    if (!open || !targetDataSource) return

    setFingerprintState({ key: targetDataSource, status: "loading" })
    
    // Reset to defaults when switching source
    setSkills([
      {
        id: "GeneralQA",
        name: "GeneralQA",
        description: "通用问答能力",
        tags: "qa",
        examples: "帮我分析这份数据",
      },
    ])
    setNameTouched(false)
    setDescTouched(false)
    lastAutoName.current = ""
    lastAutoDesc.current = ""
    form.setValue("name", "", { shouldValidate: true, shouldDirty: false, shouldTouch: false })
    form.setValue("description", "", { shouldValidate: true, shouldDirty: false, shouldTouch: false })

    if (dataSourceType === "semantic-group") {
        const sg = semanticGroups.find(s => s.id === dataSourceId)
        if (!sg) {
            setFingerprintState({ key: targetDataSource, status: "error", error: "找不到语义组信息" })
            return
        }
        
        const agentCardStr = sg.agent_card || ""
        if (!agentCardStr) {
            const msg = "该语义组未配置 agent_card"
            setFingerprintState({ key: targetDataSource, status: "error", error: msg })
            toast.error(msg)
            return
        }

        try {
            const agentCard = JSON.parse(agentCardStr) as AgentCardResponse
            setFingerprintState({
                key: targetDataSource,
                status: "ready",
                agentCard: { name: agentCard.name, description: agentCard.description },
                rawAgentCard: agentCardStr,
            })
            if (Array.isArray(agentCard?.skills)) {
                const newSkills = agentCard.skills
                  .map((s) => skillFromRaw(s))
                  .filter((s): s is Skill => s != null)
                if (newSkills.length > 0) setSkills(newSkills)
            }
        } catch {
            const msg = "agent_card 不是合法 JSON"
            setFingerprintState({ key: targetDataSource, status: "error", error: msg })
            toast.error(msg)
        }
        return
    }

    // Descriptor logic
    const [_, path] = targetDataSource.split(":") // remove prefix
    const [ns, name] = path.split("/")

    const controller = new AbortController()

    ;(async () => {
      try {
        const res = await api.get(
          `/namespaces/${encodeURIComponent(ns)}/descriptors/${encodeURIComponent(name)}/semantic-domain`,
          { signal: controller.signal }
        )
        const data = res.data?.data || null
        const agentCardStr = typeof data?.agent_card === "string" ? data.agent_card : ""

        if (!agentCardStr) {
          const msg = "未获取到 agent_card（请先为该数据源生成 semantic domain）"
          setFingerprintState({ key: targetDataSource, status: "error", error: msg })
          const errKey = `${targetDataSource}:${msg}`
          if (lastErrorRef.current !== errKey) {
            lastErrorRef.current = errKey
            toast.error(msg)
          }
          return
        }

        let agentCard: AgentCardResponse
        try {
          agentCard = JSON.parse(agentCardStr) as AgentCardResponse
        } catch {
          const msg = "agent_card 不是合法 JSON（请检查 semantic domain 内容）"
          setFingerprintState({ key: targetDataSource, status: "error", error: msg })
          const errKey = `${targetDataSource}:${msg}`
          if (lastErrorRef.current !== errKey) {
            lastErrorRef.current = errKey
            toast.error(msg)
          }
          return
        }

        const agentName = (agentCard.name ?? "").trim()
        const agentDesc = (agentCard.description ?? "").trim()

        if (!agentName && !agentDesc) {
            const msg = "agent_card 中缺少 name/description（请检查 semantic domain 内容）"
            setFingerprintState({ key: targetDataSource, status: "error", error: msg })
            const errKey = `${targetDataSource}:${msg}`
            if (lastErrorRef.current !== errKey) {
              lastErrorRef.current = errKey
              toast.error(msg)
            }
            return
        }

        setFingerprintState({
          key: targetDataSource,
          status: "ready",
          agentCard: { name: agentName, description: agentDesc },
          rawAgentCard: agentCardStr,
        })

        if (Array.isArray(agentCard?.skills)) {
          const newSkills = agentCard.skills
            .map((s) => skillFromRaw(s))
            .filter((s): s is Skill => s != null)
          if (newSkills.length > 0) setSkills(newSkills)
        }

      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") return
        const msg = "Semantic Domain 获取失败（请检查 data-services 或 Go 网关接口）"
        setFingerprintState({ key: targetDataSource, status: "error", error: msg })
        const errKey = `${targetDataSource}:${msg}`
        if (lastErrorRef.current !== errKey) {
          lastErrorRef.current = errKey
          toast.error(msg)
        }
      }
    })()

    return () => controller.abort()
  }, [open, targetDataSource, dataSourceType, semanticGroups]) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-fill form fields from agent_card if user hasn't touched them
  useEffect(() => {
    if (!open || fingerprintState.key !== targetDataSource || fingerprintState.status !== "ready") return

    const baseName = fingerprintState.agentCard?.name?.trim() || ""
    const newDesc = fingerprintState.agentCard?.description?.trim() || ""

    // 拼接: name-dd/sg-短uuid，避免同名冲突
    if (!nameTouched && baseName && baseName !== lastAutoName.current) {
        const shortType = dataSourceType === "descriptor" ? "dd" : "sg"
        const shortId = Math.random().toString(36).substring(2, 10) // 8位随机字符
        const fullName = `${baseName}-${shortType}-${shortId}`
        form.setValue("name", fullName, { shouldValidate: true, shouldDirty: false, shouldTouch: false })
        lastAutoName.current = baseName
    }

    if (!descTouched && (description || "").trim() !== newDesc && newDesc !== lastAutoDesc.current) {
        form.setValue("description", newDesc, { shouldValidate: true, shouldDirty: false, shouldTouch: false })
        lastAutoDesc.current = newDesc
    }
  }, [open, fingerprintState, targetDataSource]) // eslint-disable-line react-hooks/exhaustive-deps


  const handleSubmit = async (values: FormValues) => {
    if (isSubmitting) return
    setIsSubmitting(true)
    try {
      // skill 分支入口：dataPolicy 空；skillPolicy + 只读 agentCard.skills 一并提交
      if (dataSourceType === "skill") {
        if (skillPolicySkills.length === 0) {
          toast.error("请至少选择一个技能")
          return
        }
        if (skillDetailLoading) {
          toast.error("技能详情加载中，请稍后")
          return
        }
        if (skillDetailFailed || skills.length !== skillPolicySkills.length) {
          toast.error(skillDetailErrorMsg || "技能详情未就绪，无法提交（AgentCard skills 联动失败）")
          return
        }
        const llm = values.expertModel
        await onSubmit({
          ...values,
          namespace: values.namespace || "default",
          // skill 使用 expertLLM；plannerLLM 同步同值仅满足 CRD 双字段必填
          plannerModel: llm,
          expertModel: llm,
          skills,
          skillPolicy: { skills: skillPolicySkills },
          expertAgentMaxSteps: values.expertAgentMaxSteps || "10",
          orchestratorAgentMaxLoops: values.orchestratorAgentMaxLoops || "2",
        })
        handleOpenChange(false)
        return
      }

      if (dataSourceType === "descriptor") {
        const dd = dataDescriptors.find((d) => d.id === values.dataSourceId)
        // Ensure namespace matches the datasource's namespace
        const ns = (dd?.namespace || values.namespace || "default").trim() || "default"
        
        if (fingerprintState.key !== targetDataSource) {
            toast.error("agent_card 状态异常，请重新选择数据源")
            return
        }
        if (fingerprintState.status === "loading") {
            toast.error("agent_card 加载中，请稍后")
            return
        }
        if (fingerprintState.status !== "ready") {
            toast.error(fingerprintState.error || "未获取到 agent_card（请先为该数据源生成 semantic domain）")
            return
        }

        await onSubmit({
            ...values,
            namespace: ns,
            skills,
            skillPolicy:
              localAttachmentsEnabled && skillPolicySkills.length > 0
                ? { skills: skillPolicySkills }
                : undefined,
            expertAgentMaxSteps: values.expertAgentMaxSteps || "1",
            orchestratorAgentMaxLoops: values.orchestratorAgentMaxLoops || "0",
        })
      } else {
        // Semantic Group
        if (fingerprintState.status !== "ready") {
            toast.error(fingerprintState.error || "语义组信息不完整")
            return
        }
        
        await onSubmit({
            ...values,
            namespace: values.namespace || "default", // Semantic Group defaults to 'default' or user selection if we expose it
            skills,
            skillPolicy:
              localAttachmentsEnabled && skillPolicySkills.length > 0
                ? { skills: skillPolicySkills }
                : undefined,
            expertAgentMaxSteps: values.expertAgentMaxSteps || "1",
            orchestratorAgentMaxLoops: values.orchestratorAgentMaxLoops || "1",
        })
      }

      // Reset form
      handleOpenChange(false)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[720px] max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
        <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50">
          <DialogTitle>新建智能体</DialogTitle>
          <DialogDescription>
            创建一个新的智能体，绑定数据源并指定使用的大模型。
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="flex flex-col min-h-0 flex-1">
            <div className="space-y-4 flex-1 min-h-0 overflow-y-auto px-6 py-6">
              {/* Basic & Binding Info Group */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="dataSourceType"
                  render={({ field }) => (
                    <FormItem className="sm:col-span-2">
                      <FormLabel>数据源类型</FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={(val) => {
                          field.onChange(val)
                          form.setValue("dataSourceId", "") // Reset ID when type changes
                          if (val !== "skill") {
                            setSkillPolicySkills([])
                            setSkillVersionsByKey({})
                            setLocalAttachmentsEnabled(false)
                          }
                        }}
                        disabled={isSubmitting}
                      >
                        <FormControl>
                          <SelectTrigger className="w-full">
                            <SelectValue placeholder="选择数据源类型" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="descriptor">Data Descriptor (单一数据源)</SelectItem>
                          <SelectItem value="semantic-group">Semantic Group (语义组)</SelectItem>
                          <SelectItem value="skill">Skill（技能）</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* skill 分支：隐藏 DD/SG，展示 skill-hub 多选 */}
                {dataSourceType === "skill" ? (
                  <div className="sm:col-span-2 space-y-3 rounded-lg border border-line bg-surface p-4">
                    <div className="text-xs font-semibold text-content-muted">技能绑定</div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <div className="text-xs text-content-muted">技能命名空间</div>
                        <Select
                          value={skillPickerNs}
                          onValueChange={setSkillPickerNs}
                          disabled={isSubmitting || isLoadingSkillNs}
                        >
                          <SelectTrigger className="w-full">
                            <SelectValue placeholder="选择技能命名空间" />
                          </SelectTrigger>
                          <SelectContent>
                            {(skillHubNamespaces.length > 0
                              ? skillHubNamespaces
                              : [{ id: "default", visibility: "public" }]
                            ).map((ns) => (
                              <SelectItem key={ns.id} value={ns.id}>
                                {ns.id}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1">
                        <div className="text-xs text-content-muted">从目录添加技能</div>
                        <Select
                          key={`add-skill-${skillPolicySkills.length}-${skillPickerNs}`}
                          onValueChange={(val) => {
                            const skill = skillCatalog.find((s) => s.name === val)
                            if (skill) addSkillRef(skill)
                          }}
                          disabled={isSubmitting || isLoadingSkillCatalog}
                        >
                          <SelectTrigger className="w-full">
                            <SelectValue
                              placeholder={
                                isLoadingSkillCatalog
                                  ? "加载中…"
                                  : skillCatalogError
                                    ? skillCatalogError
                                    : "选择要添加的技能"
                              }
                            />
                          </SelectTrigger>
                          <SelectContent>
                            {skillCatalogError ? (
                              <SelectItem value="__error__" disabled>
                                {skillCatalogError}
                              </SelectItem>
                            ) : skillCatalog.length === 0 ? (
                              <SelectItem value="__empty__" disabled>
                                该命名空间暂无技能
                              </SelectItem>
                            ) : (
                              skillCatalog.map((s) => {
                                const selected = selectedSkillKeySet.has(
                                  `${s.namespace || skillPickerNs}/${s.name}`
                                )
                                return (
                                  <SelectItem
                                    key={`${s.namespace}/${s.name}`}
                                    value={s.name}
                                    disabled={selected}
                                  >
                                    {s.name}
                                    {selected ? "（已选）" : ""}
                                  </SelectItem>
                                )
                              })
                            )}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>

                    {skillPolicySkills.length === 0 ? (
                      <div className="text-sm text-content-muted">请至少选择一个技能包</div>
                    ) : (
                      <div className="space-y-2">
                        {skillPolicySkills.map((ref) => {
                          const key = `${ref.namespace}/${ref.name}`
                          const versions = skillVersionsByKey[key] ?? []
                          return (
                            <div
                              key={key}
                              className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface-muted/30 px-3 py-2"
                            >
                              <Badge variant="outline" className="font-mono text-xs">
                                {ref.namespace}
                              </Badge>
                              <span className="text-sm font-medium">{ref.name}</span>
                              <Select
                                value={ref.version || "__latest__"}
                                onValueChange={(val) =>
                                  updateSkillRefVersion(
                                    ref.name,
                                    ref.namespace,
                                    val === "__latest__" ? "" : val
                                  )
                                }
                                disabled={isSubmitting}
                              >
                                <SelectTrigger className="h-8 w-[140px]">
                                  <SelectValue placeholder="版本" />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="__latest__">最新</SelectItem>
                                  {versions.map((v) => (
                                    <SelectItem key={v} value={v}>
                                      {v}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="ml-auto h-8 w-8 text-content-muted hover:text-red-600"
                                disabled={isSubmitting}
                                onClick={() => removeSkillRef(ref.name, ref.namespace)}
                                aria-label="移除技能"
                              >
                                <X className="h-4 w-4" />
                              </Button>
                            </div>
                          )
                        })}
                      </div>
                    )}
                    {skillDetailLoading ? (
                      <div className="flex items-center gap-2 text-xs text-content-muted">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        正在拉取技能详情以联动 AgentCard…
                      </div>
                    ) : null}
                    {skillDetailErrorMsg ? (
                      <div className="text-xs text-red-600">{skillDetailErrorMsg}</div>
                    ) : null}
                  </div>
                ) : (
                <FormField
                  control={form.control}
                  name="dataSourceId"
                  render={({ field }) => (
                    <FormItem className="sm:col-span-2">
                      <FormLabel>
                        {dataSourceType === "descriptor" ? "关联数据源" : "关联语义组"}
                      </FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={(val) => {
                          field.onChange(val)
                        }}
                        onOpenChange={async (open) => {
                          setSourceOpen(open)
                          if (open) {
                            if (dataSourceType === "descriptor") await loadDataDescriptors()
                            else await loadSemanticGroups()
                          }
                        }}
                        open={sourceOpen}
                        disabled={isSubmitting}
                      >
                        <FormControl>
                          <SelectTrigger className="w-full">
                            <SelectValue placeholder={dataSourceType === "descriptor" ? "选择已处理好的数据源" : "选择已定义的语义组"} />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                          {dataSourceType === "descriptor" ? (
                            <>
                              {ddError ? (
                                <SelectItem value="__error__" disabled>
                                  {ddError}
                                </SelectItem>
                              ) : isLoadingDD && dataDescriptors.length === 0 ? (
                                <SelectItem value="__loading__" disabled>
                                  加载中…
                                </SelectItem>
                              ) : dataDescriptors.length === 0 ? (
                                <SelectItem value="__empty__" disabled>
                                  暂无可用数据源
                                </SelectItem>
                              ) : null}
                              {dataDescriptors.map((dd) => (
                                <SelectItem key={dd.id} value={dd.id}>
                                  {dd.name}
                                </SelectItem>
                              ))}
                            </>
                          ) : (
                            <>
                              {sgError ? (
                                <SelectItem value="__error__" disabled>
                                  {sgError}
                                </SelectItem>
                              ) : isLoadingSG && semanticGroups.length === 0 ? (
                                <SelectItem value="__loading__" disabled>
                                  加载中…
                                </SelectItem>
                              ) : semanticGroups.length === 0 ? (
                                <SelectItem value="__empty__" disabled>
                                  暂无可用语义组
                                </SelectItem>
                              ) : null}
                              {semanticGroups.map((sg) => (
                                <SelectItem key={sg.id} value={sg.id}>
                                  {sg.group_name}
                                </SelectItem>
                              ))}
                            </>
                          )}
                        </SelectContent>
                      </Select>
                      <FormDescription>
                        {dataSourceType === "descriptor"
                          ? `智能体将基于所选数据源进行知识问答（将自动关联至数据源所在的 ${namespace || "default"} 命名空间）。`
                          : "智能体将基于所选语义组（包含多个关联数据源）进行联合知识问答。"}
                      </FormDescription>
                      {fingerprintError && (
                        <div className="text-xs text-red-600 mt-1">{fingerprintError}</div>
                      )}
                      <FormMessage />
                    </FormItem>
                  )}
                />
                )}

                {dataSourceType !== "skill" ? (
                  <div className="sm:col-span-2 space-y-3 rounded-lg border border-line bg-surface p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold text-content-muted">
                          本地技能附件（可选）
                        </div>
                        <div className="mt-1 text-xs text-content-muted">
                          技能包将在智能体启动时从 Skill Hub 下载，并直接由当前 DAC 的 orchestrator 执行。
                        </div>
                      </div>
                      <Button
                        type="button"
                        variant={localAttachmentsEnabled ? "default" : "outline"}
                        size="sm"
                        disabled={isSubmitting}
                        onClick={() => {
                          const next = !localAttachmentsEnabled
                          setLocalAttachmentsEnabled(next)
                          if (!next) {
                            setSkillPolicySkills([])
                            setSkillVersionsByKey({})
                          }
                        }}
                      >
                        {localAttachmentsEnabled ? "已启用" : "启用"}
                      </Button>
                    </div>

                    {localAttachmentsEnabled ? (
                      <>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <div className="text-xs text-content-muted">技能命名空间</div>
                            <Select
                              value={skillPickerNs}
                              onValueChange={setSkillPickerNs}
                              disabled={isSubmitting || isLoadingSkillNs}
                            >
                              <SelectTrigger className="w-full">
                                <SelectValue placeholder="选择技能命名空间" />
                              </SelectTrigger>
                              <SelectContent>
                                {(skillHubNamespaces.length > 0
                                  ? skillHubNamespaces
                                  : [{ id: "default", visibility: "public" }]
                                ).map((ns) => (
                                  <SelectItem key={ns.id} value={ns.id}>
                                    {ns.id}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                          <div className="space-y-1">
                            <div className="text-xs text-content-muted">添加本地技能</div>
                            <Select
                              key={`add-local-skill-${skillPolicySkills.length}-${skillPickerNs}`}
                              onValueChange={(val) => {
                                const skill = skillCatalog.find((s) => s.name === val)
                                if (skill) addSkillRef(skill)
                              }}
                              disabled={isSubmitting || isLoadingSkillCatalog}
                            >
                              <SelectTrigger className="w-full">
                                <SelectValue
                                  placeholder={
                                    isLoadingSkillCatalog
                                      ? "加载中…"
                                      : skillCatalogError || "选择要附加的技能"
                                  }
                                />
                              </SelectTrigger>
                              <SelectContent>
                                {skillCatalog.length === 0 ? (
                                  <SelectItem value="__empty_local__" disabled>
                                    {skillCatalogError || "该命名空间暂无技能"}
                                  </SelectItem>
                                ) : (
                                  skillCatalog.map((skill) => (
                                    <SelectItem
                                      key={`${skill.namespace || skillPickerNs}/${skill.name}`}
                                      value={skill.name}
                                      disabled={selectedSkillKeySet.has(
                                        `${skill.namespace || skillPickerNs}/${skill.name}`
                                      )}
                                    >
                                      {skill.name}
                                    </SelectItem>
                                  ))
                                )}
                              </SelectContent>
                            </Select>
                          </div>
                        </div>

                        {skillPolicySkills.length === 0 ? (
                          <div className="text-sm text-content-muted">尚未附加本地技能</div>
                        ) : (
                          <div className="space-y-2">
                            {skillPolicySkills.map((ref) => {
                              const key = `${ref.namespace}/${ref.name}`
                              const versions = skillVersionsByKey[key] ?? []
                              return (
                                <div
                                  key={key}
                                  className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface-muted/30 px-3 py-2"
                                >
                                  <Badge variant="outline" className="font-mono text-xs">
                                    {ref.namespace}
                                  </Badge>
                                  <span className="text-sm font-medium">{ref.name}</span>
                                  <Select
                                    value={ref.version || "__latest__"}
                                    onValueChange={(val) =>
                                      updateSkillRefVersion(
                                        ref.name,
                                        ref.namespace,
                                        val === "__latest__" ? "" : val
                                      )
                                    }
                                    disabled={isSubmitting}
                                  >
                                    <SelectTrigger className="h-8 w-[140px]">
                                      <SelectValue placeholder="版本" />
                                    </SelectTrigger>
                                    <SelectContent>
                                      <SelectItem value="__latest__">最新</SelectItem>
                                      {versions.map((version) => (
                                        <SelectItem key={version} value={version}>
                                          {version}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    className="ml-auto h-8 w-8 text-content-muted hover:text-red-600"
                                    disabled={isSubmitting}
                                    onClick={() => removeSkillRef(ref.name, ref.namespace)}
                                    aria-label="移除本地技能"
                                  >
                                    <X className="h-4 w-4" />
                                  </Button>
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </>
                    ) : null}
                  </div>
                ) : null}

                <FormField
                  control={form.control}
                  name="name"
                  render={({ field }) => (
                    <FormItem className={dataSourceType === "descriptor" ? "sm:col-span-2" : ""}>
                      <FormLabel>智能体名称</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="例如：agent-datadescriptor-00001"
                          {...field}
                          disabled={isSubmitting}
                          onChange={(e) => {
                            setNameTouched(true)
                            field.onChange(e)
                          }}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                
                {/* Namespace: descriptor auto-managed; semantic-group / skill expose picker */}
                {dataSourceType === "descriptor" ? (
                  <div className="hidden">
                    <FormField
                      control={form.control}
                      name="namespace"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>命名空间</FormLabel>
                          <Select
                            value={field.value}
                            onValueChange={(val) => {
                              field.onChange(val)
                              // Clear data source when namespace changes to avoid mismatch
                              form.setValue("dataSourceId", "")
                            }}
                            disabled={isSubmitting || isLoadingNs}
                          >
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue placeholder="选择命名空间" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                              {namespaces.map((ns) => (
                                <SelectItem key={ns} value={ns}>
                                  {ns}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                ) : (
                  <FormField
                    control={form.control}
                    name="namespace"
                    render={({ field }) => (
                      <FormItem className="sm:col-span-1">
                        <FormLabel>部署命名空间</FormLabel>
                        <Select
                          value={field.value}
                          onValueChange={(val) => {
                            field.onChange(val)
                          }}
                          onOpenChange={() => {}}
                          disabled={isSubmitting || isLoadingNs}
                        >
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="选择命名空间" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                            {namespaces.map((ns) => (
                              <SelectItem key={ns} value={ns}>
                                {ns}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <FormDescription>智能体将被部署在此命名空间中。</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}

                <FormField
                  control={form.control}
                  name="description"
                  render={({ field }) => (
                    <FormItem className="sm:col-span-2">
                      <FormLabel>描述</FormLabel>
                      <FormControl>
                        <Textarea
                          placeholder="描述该智能体的用途..."
                          {...field}
                          disabled={isSubmitting}
                          onChange={(e) => {
                            setDescTouched(true)
                            field.onChange(e)
                          }}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              {/* Model Config */}
              <div className="rounded-lg border border-line bg-surface p-4 space-y-4">
                <div className="text-xs font-semibold text-content-muted">模型配置</div>
                {dataSourceType === "skill" ? (
                  // skill 类型：单 LLM，绑定 expertModel（运行时读 expertLLM）
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <FormField
                      control={form.control}
                      name="expertModel"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>模型</FormLabel>
                          <Select
                            onValueChange={(val) => {
                              field.onChange(val)
                              form.setValue("plannerModel", val, { shouldValidate: true })
                            }}
                            value={field.value}
                            onOpenChange={async (open) => {
                              if (open) await loadLlmConfigs(namespace || "default")
                            }}
                          >
                            <FormControl>
                              <SelectTrigger className="w-full" disabled={isSubmitting}>
                                <SelectValue placeholder="选择模型" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                              {llmError ? (
                                <SelectItem value="__error__" disabled>
                                  {llmError}
                                </SelectItem>
                              ) : isLoadingLLM && llmConfigs.length === 0 ? (
                                <SelectItem value="__loading__" disabled>
                                  加载中…
                                </SelectItem>
                              ) : llmConfigs.length === 0 ? (
                                <SelectItem value="__empty__" disabled>
                                  暂无可用模型配置（请先创建 LLM ConfigMap）
                                </SelectItem>
                              ) : null}
                              {llmConfigs.map((c) => (
                                <SelectItem key={c.name} value={c.name}>
                                  {c.name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="expertAgentMaxSteps"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>最大步数</FormLabel>
                          <FormControl>
                            <Input
                              placeholder="默认 10"
                              {...field}
                              disabled={isSubmitting}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="space-y-4">
                    <FormField
                      control={form.control}
                      name="plannerModel"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>规划模型</FormLabel>
                          <Select
                            onValueChange={field.onChange}
                            value={field.value}
                            onOpenChange={async (open) => {
                              if (open) await loadLlmConfigs(namespace || "default")
                            }}
                          >
                            <FormControl>
                              <SelectTrigger className="w-full" disabled={isSubmitting}>
                                <SelectValue placeholder="选择模型" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                              {llmError ? (
                                <SelectItem value="__error__" disabled>
                                  {llmError}
                                </SelectItem>
                              ) : isLoadingLLM && llmConfigs.length === 0 ? (
                                <SelectItem value="__loading__" disabled>
                                  加载中…
                                </SelectItem>
                              ) : llmConfigs.length === 0 ? (
                                <SelectItem value="__empty__" disabled>
                                  暂无可用模型配置（请先创建 LLM ConfigMap）
                                </SelectItem>
                              ) : null}
                              {llmConfigs.map((c) => (
                                <SelectItem key={c.name} value={c.name}>
                                  {c.name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          {selectedPlannerModel && (
                            <div className="text-xs text-content-muted truncate" title={selectedPlannerModel}>
                              {selectedPlannerModel}
                            </div>
                          )}
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="orchestratorAgentMaxLoops"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>编排最大循环数</FormLabel>
                          <FormControl>
                            <Input
                              placeholder="默认 0"
                              {...field}
                              disabled={isSubmitting}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>

                  <div className="space-y-4">
                    <FormField
                      control={form.control}
                      name="expertModel"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>专家模型</FormLabel>
                          <Select
                            onValueChange={field.onChange}
                            value={field.value}
                            onOpenChange={async (open) => {
                              if (open) await loadLlmConfigs(namespace || "default")
                            }}
                          >
                            <FormControl>
                              <SelectTrigger className="w-full" disabled={isSubmitting}>
                                <SelectValue placeholder="选择模型" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                              {llmError ? (
                                <SelectItem value="__error__" disabled>
                                  {llmError}
                                </SelectItem>
                              ) : isLoadingLLM && llmConfigs.length === 0 ? (
                                <SelectItem value="__loading__" disabled>
                                  加载中…
                                </SelectItem>
                              ) : llmConfigs.length === 0 ? (
                                <SelectItem value="__empty__" disabled>
                                  暂无可用模型配置（请先创建 LLM ConfigMap）
                                </SelectItem>
                              ) : null}
                              {llmConfigs.map((c) => (
                                <SelectItem key={c.name} value={c.name}>
                                  {c.name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          {selectedExpertModel && (
                            <div className="text-xs text-content-muted truncate" title={selectedExpertModel}>
                              {selectedExpertModel}
                            </div>
                          )}
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="expertAgentMaxSteps"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>专家最大步数</FormLabel>
                          <FormControl>
                            <Input
                              placeholder="默认 1"
                              {...field}
                              disabled={isSubmitting}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                </div>
                )}
                <div className="text-xs text-content-muted">
                  没有可选项？
                  <a
                    className="ml-1 text-cta hover:text-cta/90 hover:underline cursor-pointer"
                    href={`/configmaps?namespace=${encodeURIComponent((namespace || "default").trim() || "default")}&type=llm&create=1`}
                  >
                    去创建 LLM ConfigMap
                  </a>
                </div>
              </div>

              {/* Skills Definition — skill 类型只读展示（由 skillPolicy detail 联动） */}
              <div className="rounded-lg border border-line bg-surface p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="text-xs font-semibold text-content-muted">
                    {dataSourceType === "skill" ? "AgentCard 技能（只读）" : "技能定义"}
                  </div>
                  {dataSourceType !== "skill" ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={isSubmitting}
                    onClick={() =>
                      setSkills((prev) => [
                        ...prev,
                        {
                          id: `skill-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
                          name: "",
                          description: "",
                          tags: "",
                          examples: "",
                        },
                      ])
                    }
                  >
                    添加技能
                  </Button>
                  ) : null}
                </div>
                <div className="space-y-3">
                  {skills.length === 0 ? (
                    <div className="text-sm text-content-muted">
                      {dataSourceType === "skill" ? "选择技能后将自动填充" : "暂无技能"}
                    </div>
                  ) : (
                    skills.map((skill, idx) => (
                      <div
                        key={skill.id}
                        className="rounded-md border border-line p-3 bg-surface-muted/30"
                      >
                        <div className="flex items-center justify-between mb-3">
                          <div className="flex items-center gap-2">
                            <Zap className="w-4 h-4 text-sky-600" />
                            <span className="text-sm font-medium text-content">
                              {skill.name?.trim() ? skill.name : `技能 ${idx + 1}`}
                            </span>
                            {skill.id?.trim() && (
                              <Badge variant="outline" className="text-xs">
                                ID: {skill.id}
                              </Badge>
                            )}
                          </div>
                          {dataSourceType !== "skill" ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            disabled={isSubmitting}
                            className="text-content-muted hover:text-red-600"
                            onClick={() =>
                              setSkills((prev) => prev.filter((_, i) => i !== idx))
                            }
                          >
                            删除
                          </Button>
                          ) : null}
                        </div>
                        {dataSourceType === "skill" ? (
                          <div className="space-y-2 text-sm">
                            <div className="text-content-muted text-xs">技能描述</div>
                            <div className="text-content whitespace-pre-wrap">
                              {skill.description || "—"}
                            </div>
                          </div>
                        ) : (
                        <>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <div className="text-xs text-content-muted">技能 ID</div>
                            <Input
                              value={skill.id}
                              placeholder="例如：GeneralQA"
                              disabled={isSubmitting}
                              onChange={(e) =>
                                setSkills((prev) =>
                                  prev.map((s, i) =>
                                    i === idx ? { ...s, id: e.target.value } : s
                                  )
                                )
                              }
                            />
                          </div>
                          <div className="space-y-1">
                            <div className="text-xs text-content-muted">技能名称</div>
                            <Input
                              value={skill.name}
                              placeholder="例如：数据问答"
                              disabled={isSubmitting}
                              onChange={(e) =>
                                setSkills((prev) =>
                                  prev.map((s, i) =>
                                    i === idx ? { ...s, name: e.target.value } : s
                                  )
                                )
                              }
                            />
                          </div>
                        </div>
                        <div className="mt-3 space-y-1">
                          <div className="text-xs text-content-muted">技能描述</div>
                          <Textarea
                            value={skill.description}
                            placeholder="该技能能做什么..."
                            disabled={isSubmitting}
                            onChange={(e) =>
                              setSkills((prev) =>
                                prev.map((s, i) =>
                                  i === idx ? { ...s, description: e.target.value } : s
                                )
                              )
                            }
                          />
          </div>
                        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <div className="text-xs text-content-muted">标签（逗号分隔）</div>
                            <Input
                              value={skill.tags}
                              placeholder="例如：qa,sql"
                              disabled={isSubmitting}
                              onChange={(e) =>
                                setSkills((prev) =>
                                  prev.map((s, i) =>
                                    i === idx ? { ...s, tags: e.target.value } : s
                                  )
                                )
                              }
                            />
          </div>
                          <div className="space-y-1">
                            <div className="text-xs text-content-muted">示例问题（每行一个）</div>
                            <Textarea
                              value={skill.examples}
                              placeholder={`例如：\n帮我分析这份数据\n这个指标怎么计算？`}
                              disabled={isSubmitting}
                              onChange={(e) =>
                                setSkills((prev) =>
                                  prev.map((s, i) =>
                                    i === idx ? { ...s, examples: e.target.value } : s
                                  )
                                )
                              }
                            />
          </div>
          </div>
                        </>
                        )}
            </div>
                    ))
                  )}
            </div>
          </div>
        </div>

            <DialogFooter className="px-6 py-4 border-t border-line bg-surface-muted/50 mt-0">
              <Button
                type="button"
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={isSubmitting}
              >
            取消
          </Button>
              <Button
                type="submit"
                disabled={
                  isSubmitting ||
                  (dataSourceType === "skill"
                    ? skillDetailLoading ||
                      skillDetailFailed ||
                      skillPolicySkills.length === 0
                    : isFingerprintLoading || !!fingerprintError)
                }
              >
                {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                创建智能体
          </Button>
        </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

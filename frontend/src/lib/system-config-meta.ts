import type { SystemConfigName } from "@/lib/system-config-api"

/** Namespace where dac-configuration / dd-configuration live (matches apiserver SystemConfigNamespace). */
export const SYSTEM_CONFIG_NAMESPACE = "dac"

export const SYSTEM_CONFIG_NAMES: SystemConfigName[] = ["dac-configuration", "dd-configuration"]

/** ConfigMap names excluded from LLM picker (system templates, not LLM model configs). */
export const SYSTEM_CONFIG_EXCLUDED_LLM_CONFIGMAPS = new Set<string>(SYSTEM_CONFIG_NAMES)

export function isLlmConfigMapFieldKey(key: string): boolean {
  return (
    key === "default-planner-llm" ||
    key === "default-expert-llm" ||
    key === "llm-config"
  )
}

/** Keys that are always read-only in the UI (pre-configured by Helm, not user-editable). */
export function isReadonlySystemConfigKey(key: string): boolean {
  return key === "default-planner-llm" || key === "default-expert-llm" || key === "llm-config"
}

export type SystemConfigMeta = {
  groups: { title?: string; keys: string[] }[]
}

export const SYSTEM_CONFIG_META: Record<SystemConfigName, SystemConfigMeta> = {
  "dac-configuration": {
    groups: [
      {
        keys: [
          "orchestrator-agent-image",
          "expert-agent-image",
          "ds-data-services-image",
          "code-agent-image",
          "doc-agent-image",
          "dd-sync-observer-image",
          "skill-agent-image",
          "cross-sg-max-hop",
        ],
      },
      {
        keys: ["default-planner-llm", "default-expert-llm"],
      },
    ],
  },
  "dd-configuration": {
    groups: [
      {
        keys: ["data-sinker-job-image", "data-sinker-status-image", "dac-data-services-image"],
      },
      {
        keys: ["llm-config"],
      },
    ],
  },
}

export function emptyDataForConfig(name: SystemConfigName): Record<string, string> {
  const out: Record<string, string> = {}
  for (const group of SYSTEM_CONFIG_META[name].groups) {
    for (const key of group.keys) {
      out[key] = ""
    }
  }
  return out
}

export function mergeFormData(
  name: SystemConfigName,
  serverData: Record<string, string> | undefined
): Record<string, string> {
  const base = emptyDataForConfig(name)
  if (!serverData) return base
  for (const key of Object.keys(base)) {
    if (typeof serverData[key] === "string") {
      base[key] = serverData[key]
    }
  }
  return base
}

/**
 * Validate that LLM ConfigMaps referenced by dac/dd-configuration exist in the
 * DataDescriptor target namespace (same rule as execution-engine PreCheckLLMConfig).
 *
 * Name refs are read from system ConfigMaps in `dac`; existence is checked in
 * `targetNamespace` via GET-by-name (not type=llm list — Helm-seeded CMs often
 * lack dac.io/config-type labels and would false-negative).
 */
export async function validateSystemLlmConfigMaps(
  targetNamespace: string
): Promise<string | null> {
  const ns = (targetNamespace || "").trim() || "default"
  const { getSystemConfiguration } = await import("@/lib/system-config-api")
  const { getConfigMap } = await import("@/lib/configmaps-api")
  const axios = (await import("axios")).default

  const refs: { key: string; name: string }[] = []

  try {
    const dacCfg = await getSystemConfiguration("dac-configuration")
    const planner = (dacCfg.data?.["default-planner-llm"] ?? "").trim()
    const expert = (dacCfg.data?.["default-expert-llm"] ?? "").trim()
    if (planner) refs.push({ key: "default-planner-llm", name: planner })
    if (expert) refs.push({ key: "default-expert-llm", name: expert })
  } catch {
    // dac-configuration may not exist yet; skip
  }

  try {
    const ddCfg = await getSystemConfiguration("dd-configuration")
    const llmConfig = (ddCfg.data?.["llm-config"] ?? "").trim()
    if (llmConfig) refs.push({ key: "llm-config", name: llmConfig })
  } catch {
    // dd-configuration may not exist yet; skip
  }

  const missing: string[] = []
  const seen = new Set<string>()
  for (const ref of refs) {
    const dedupe = `${ref.key}\0${ref.name}`
    if (seen.has(dedupe)) continue
    seen.add(dedupe)
    try {
      await getConfigMap(ns, ref.name, "llm")
    } catch (e) {
      if (axios.isAxiosError(e) && e.response?.status === 404) {
        missing.push(`${ref.key} → "${ref.name}"`)
      } else {
        throw e
      }
    }
  }

  if (missing.length === 0) return null
  return `以下 LLM 配置在命名空间 ${ns} 中不存在（须与数据源同命名空间），请先在 模版中心 创建对应 ConfigMap：\n${missing.join("\n")}`
}

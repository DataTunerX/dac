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
 * Validate that the LLM ConfigMaps referenced in dac-configuration and
 * dd-configuration exist in the dac namespace. Returns human-readable
 * error messages for any missing ConfigMaps.
 */
export async function validateSystemLlmConfigMaps(): Promise<string | null> {
  const { getSystemConfiguration } = await import("@/lib/system-config-api")
  const { listAllConfigMaps } = await import("@/lib/configmaps-api")

  const allCms = await listAllConfigMaps(SYSTEM_CONFIG_NAMESPACE, { type: "llm" })
  const existingNames = new Set(allCms.map((c) => c.name))

  const missing: string[] = []

  try {
    const dacCfg = await getSystemConfiguration("dac-configuration")
    const planner = (dacCfg.data?.["default-planner-llm"] ?? "").trim()
    const expert = (dacCfg.data?.["default-expert-llm"] ?? "").trim()
    if (planner && !existingNames.has(planner)) {
      missing.push(`default-planner-llm → "${planner}"`)
    }
    if (expert && !existingNames.has(expert)) {
      missing.push(`default-expert-llm → "${expert}"`)
    }
  } catch {
    // dac-configuration may not exist yet; skip
  }

  try {
    const ddCfg = await getSystemConfiguration("dd-configuration")
    const llmConfig = (ddCfg.data?.["llm-config"] ?? "").trim()
    if (llmConfig && !existingNames.has(llmConfig)) {
      missing.push(`llm-config → "${llmConfig}"`)
    }
  } catch {
    // dd-configuration may not exist yet; skip
  }

  if (missing.length === 0) return null
  return `以下 LLM 配置在命名空间 ${SYSTEM_CONFIG_NAMESPACE} 中不存在，请先在 模版中心 创建对应 ConfigMap：\n${missing.join("\n")}`
}

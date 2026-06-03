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

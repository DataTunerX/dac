import type {
  AgentContainerResponse,
  AgentSkillResponse,
  SkillPolicy,
  UpdateAgentContainerRequest,
} from "@/lib/api-types"

/** Form skill rows (tags/examples are comma- or newline-separated text). */
export type AgentFormSkill = {
  id?: string
  name?: string
  description?: string
  tags?: string
  examples?: string
}

export type AgentUpdateForm = {
  name: string
  description?: string
  dataSourceType?: string
  skills?: AgentFormSkill[]
  skillPolicy?: SkillPolicy
  plannerModel?: string
  expertModel?: string
  expertAgentMaxSteps?: string
  orchestratorAgentMaxLoops?: string
  skillAgentMaxLoops?: string
  crossSGMaxHop?: string
  summarizeEnabled?: string
  summarizeCustomPrompt?: string
}

export function toAgentCardSkills(skills: AgentFormSkill[] | undefined): AgentSkillResponse[] {
  return (skills || [])
    .map((s) => {
      const id = (s.id || "").trim() || (s.name || "").trim()
      const name = (s.name || "").trim() || id
      const description = (s.description || "").trim()
      const tags = (s.tags || "")
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean)
      const examples = (s.examples || "")
        .split("\n")
        .map((t) => t.trim())
        .filter(Boolean)
      return { id, name, description, tags, examples }
    })
    .filter((s) => s.id && s.name)
}

/**
 * Update payload. Business (normal) and data (ds) agents keep their existing
 * dataPolicy, so the bound data source and semantic group stay unchanged.
 */
export function buildAgentUpdateRequest(
  existing: AgentContainerResponse,
  data: AgentUpdateForm,
): UpdateAgentContainerRequest {
  const dacType = (existing.dacType || "").toLowerCase()
  const skills = toAgentCardSkills(data.skills)
  const embedding = existing.model?.embedding || "embedding-config"

  if (dacType === "skill" || data.dataSourceType === "skill") {
    const llm = data.expertModel || data.plannerModel || ""
    return {
      dacType: "skill",
      agentCard: {
        name: data.name,
        description: data.description || "",
        skills,
      },
      dataPolicy: {
        dataSourceType: "",
        semanticGroupID: "",
        sourceNameSelector: [],
      },
      skillPolicy: data.skillPolicy ?? { skills: [] },
      model: {
        plannerLLM: llm,
        expertLLM: llm,
        embedding,
      },
      expertAgentMaxSteps: data.expertAgentMaxSteps || "30",
      orchestratorAgentMaxLoops: data.orchestratorAgentMaxLoops || "2",
      skillAgentMaxLoops: data.skillAgentMaxLoops || "2",
      crossSGMaxHop: data.crossSGMaxHop || "5",
      summarizeEnabled: data.summarizeEnabled || "true",
      summarizeCustomPrompt: data.summarizeCustomPrompt || "",
    }
  }

  const isSemanticGroup =
    dacType === "normal" || data.dataSourceType === "semantic-group"
  const cardName = (existing.agentCard?.name || data.name || existing.name || "").trim()

  return {
    dacType: isSemanticGroup ? "normal" : "ds",
    agentCard: {
      name: cardName,
      description: data.description || "",
      skills,
    },
    ...(isSemanticGroup
      ? { skillPolicy: data.skillPolicy ?? existing.skillPolicy ?? { skills: [] } }
      : {}),
    model: {
      plannerLLM: data.plannerModel || existing.model?.plannerLLM || "",
      expertLLM: data.expertModel || existing.model?.expertLLM || "",
      embedding,
    },
    expertAgentMaxSteps: data.expertAgentMaxSteps || (isSemanticGroup ? "1" : "2"),
    orchestratorAgentMaxLoops:
      data.orchestratorAgentMaxLoops || (isSemanticGroup ? "1" : "0"),
  }
}

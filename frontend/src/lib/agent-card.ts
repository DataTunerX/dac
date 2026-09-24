export type AgentCardSkillDraft = {
  id: string
  name: string
  description: string
  tags: string
  examples: string
}

export type AgentCardObject = Record<string, unknown> & {
  name?: string
  description?: string
  skills?: unknown
}

export function parseAgentCard(raw?: string): AgentCardObject | null {
  const s = String(raw ?? "").trim()
  if (!s) return {}
  try {
    const obj = JSON.parse(s) as unknown
    if (obj && typeof obj === "object" && !Array.isArray(obj)) {
      return obj as AgentCardObject
    }
    return null
  } catch {
    return null
  }
}

export function stringifyAgentCard(card: AgentCardObject): string {
  return JSON.stringify(card)
}

export function skillsFromCard(card: AgentCardObject | null): AgentCardSkillDraft[] {
  const raw = card?.skills
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((sk) => ({
      id: String(sk.id ?? ""),
      name: String(sk.name ?? ""),
      description: String(sk.description ?? ""),
      tags: Array.isArray(sk.tags) ? sk.tags.map((t) => String(t)).join(", ") : "",
      examples: Array.isArray(sk.examples) ? sk.examples.map((t) => String(t)).join("\n") : "",
    }))
}

export function applySkills(card: AgentCardObject, drafts: AgentCardSkillDraft[]): AgentCardObject {
  const skills = drafts.map((d) => ({
    id: d.id.trim(),
    name: d.name.trim(),
    description: d.description.trim(),
    tags: d.tags.split(/[,，]/).map((t) => t.trim()).filter(Boolean),
    examples: d.examples.split("\n").map((t) => t.trim()).filter(Boolean),
  }))
  return { ...card, skills }
}

export function emptySkillDraft(): AgentCardSkillDraft {
  return { id: "", name: "", description: "", tags: "", examples: "" }
}

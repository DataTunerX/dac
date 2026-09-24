import { describe, expect, it } from "vitest"
import {
  applySkills,
  emptySkillDraft,
  parseAgentCard,
  skillsFromCard,
  stringifyAgentCard,
} from "./agent-card"

describe("agent-card", () => {
  it("parseAgentCard returns {} for empty input", () => {
    expect(parseAgentCard("")).toEqual({})
    expect(parseAgentCard("   ")).toEqual({})
  })

  it("parseAgentCard returns null for invalid JSON", () => {
    expect(parseAgentCard("{not json")).toBeNull()
    expect(parseAgentCard("[]")).toBeNull()
  })

  it("round-trips description and skills", () => {
    const raw = stringifyAgentCard({
      name: "OrdersAgent",
      description: "订单领域",
      skills: [
        {
          id: "order-query",
          name: "订单查询",
          description: "查订单",
          tags: ["order", "订单"],
          examples: ["查一下订单"],
        },
      ],
    })
    const parsed = parseAgentCard(raw)
    const skills = skillsFromCard(parsed)
    expect(parsed?.name).toBe("OrdersAgent")
    expect(parsed?.description).toBe("订单领域")
    expect(skills).toEqual([
      {
        id: "order-query",
        name: "订单查询",
        description: "查订单",
        tags: "order, 订单",
        examples: "查一下订单",
      },
    ])

    const next = applySkills(
      { ...parsed, description: "新描述" },
      [{ ...emptySkillDraft(), id: "s2", name: "skill two", tags: "a，b", examples: "e1\ne2" }],
    )
    expect(next.description).toBe("新描述")
    expect(next.skills).toEqual([
      {
        id: "s2",
        name: "skill two",
        description: "",
        tags: ["a", "b"],
        examples: ["e1", "e2"],
      },
    ])
  })
})

import { describe, expect, it } from "vitest"
import { buildAgentUpdateRequest } from "./agent-update"
import type { AgentContainerResponse } from "./api-types"

function base(over: Partial<AgentContainerResponse>): AgentContainerResponse {
  return {
    name: "agent-a",
    namespace: "default",
    dataPolicy: { dataSourceType: "SemanticDomain", sourceNameSelector: ["orders"] },
    agentCard: { name: "订单助手", description: "原来的概览", skills: [] },
    model: { plannerLLM: "planner-a", expertLLM: "expert-a", embedding: "embed-a" },
    createdAt: "",
    updatedAt: "",
    ...over,
  }
}

describe("buildAgentUpdateRequest", () => {
  it("keeps the data source binding for a data agent and updates editable fields", () => {
    const existing = base({ dacType: "ds" })
    const req = buildAgentUpdateRequest(existing, {
      name: "订单助手",
      description: "新的概览",
      dataSourceType: "descriptor",
      plannerModel: "planner-b",
      expertModel: "expert-b",
      expertAgentMaxSteps: "4",
      orchestratorAgentMaxLoops: "3",
      skills: [
        {
          id: "qa",
          name: "问答",
          description: "回答问题",
          tags: "qa, sql",
          examples: "查订单\n查金额",
        },
      ],
    })

    expect(req.dacType).toBe("ds")
    expect(req.dataPolicy).toBeUndefined()
    expect(req.skillPolicy).toBeUndefined()
    expect(req.agentCard).toEqual({
      name: "订单助手",
      description: "新的概览",
      skills: [
        {
          id: "qa",
          name: "问答",
          description: "回答问题",
          tags: ["qa", "sql"],
          examples: ["查订单", "查金额"],
        },
      ],
    })
    expect(req.model).toEqual({
      plannerLLM: "planner-b",
      expertLLM: "expert-b",
      embedding: "embed-a",
    })
    expect(req.expertAgentMaxSteps).toBe("4")
    expect(req.orchestratorAgentMaxLoops).toBe("3")
  })

  it("keeps the semantic group binding for a business agent and sends skill bindings", () => {
    const existing = base({
      dacType: "normal",
      dataPolicy: { dataSourceType: "SemanticGroup", semanticGroupID: "sg-1" },
    })
    const req = buildAgentUpdateRequest(existing, {
      name: "业务",
      description: "概览",
      dataSourceType: "semantic-group",
      plannerModel: "p",
      expertModel: "e",
      skillPolicy: { skills: [{ namespace: "default", name: "lookup", version: "1" }] },
      skills: [],
    })

    expect(req.dacType).toBe("normal")
    expect(req.dataPolicy).toBeUndefined()
    expect(req.skillPolicy).toEqual({
      skills: [{ namespace: "default", name: "lookup", version: "1" }],
    })
  })

  it("still updates a skill agent as a skill DAC", () => {
    const existing = base({
      dacType: "skill",
      dataPolicy: { dataSourceType: "", sourceNameSelector: [] },
    })
    const req = buildAgentUpdateRequest(existing, {
      name: "通用",
      description: "描述",
      dataSourceType: "skill",
      expertModel: "llm-1",
      skills: [{ id: "s", name: "s", description: "", tags: "", examples: "" }],
      skillPolicy: { skills: [{ namespace: "default", name: "s" }] },
      expertAgentMaxSteps: "30",
      orchestratorAgentMaxLoops: "2",
      skillAgentMaxLoops: "2",
      crossSGMaxHop: "5",
      summarizeEnabled: "true",
      summarizeCustomPrompt: "自定义",
    })

    expect(req.dacType).toBe("skill")
    expect(req.dataPolicy).toEqual({
      dataSourceType: "",
      semanticGroupID: "",
      sourceNameSelector: [],
    })
    expect(req.model?.expertLLM).toBe("llm-1")
    expect(req.model?.plannerLLM).toBe("llm-1")
    expect(req.summarizeCustomPrompt).toBe("自定义")
  })
})

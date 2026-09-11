import { describe, expect, it } from "vitest"
import { DEMO_SCENARIOS, DEMO_STEPS, getDemoStepIndex, getScenarioForStep } from "@/lib/demo-scenarios"

describe("guided demo manifest", () => {
  it("covers every scenario from the supplied plan in presentation order", () => {
    expect(DEMO_SCENARIOS.map((scenario) => scenario.id)).toEqual([
      "scenario-1-1",
      "scenario-1-2",
      "scenario-2",
      "scenario-3",
      "scenario-4",
      "scenario-5",
      "scenario-6",
      "scenario-7",
    ])
    expect(DEMO_STEPS).toHaveLength(23)
  })

  it("uses unique scenario and step ids", () => {
    const scenarioIds = DEMO_SCENARIOS.map((scenario) => scenario.id)
    const stepIds = DEMO_STEPS.map((step) => step.id)
    expect(new Set(scenarioIds).size).toBe(scenarioIds.length)
    expect(new Set(stepIds).size).toBe(stepIds.length)
  })

  it("gives every executable action the data it needs", () => {
    for (const step of DEMO_STEPS) {
      expect(step.expected.length, step.id).toBeGreaterThan(0)
      expect(step.purpose.trim().length, step.id).toBeGreaterThan(0)
      if (step.kind === "chat") expect(step.prompt?.trim().length, step.id).toBeGreaterThan(0)
      if (step.kind === "navigate") expect(step.href, step.id).toMatch(/^\//)
      if (step.kind === "blocked") expect(step.blockedReason?.trim().length, step.id).toBeGreaterThan(0)
    }
  })

  it("makes the circuit question executable", () => {
    const scenario = DEMO_SCENARIOS.find((item) => item.id === "scenario-7")
    expect(scenario?.status).toBe("ready")
    expect(scenario?.steps).toHaveLength(1)
    expect(scenario?.steps[0].kind).toBe("chat")
    expect(scenario?.steps[0].prompt).toBe("电路图2号里面的最大芯片是什么？")
  })

  it("makes the two storage questions executable", () => {
    const scenario = DEMO_SCENARIOS.find((item) => item.id === "scenario-5")
    expect(scenario?.status).toBe("ready")
    expect(scenario?.steps).toHaveLength(2)
    expect(scenario?.steps.every((step) => step.kind === "chat")).toBe(true)
  })

  it("makes the three architecture questions executable", () => {
    const scenario = DEMO_SCENARIOS.find((item) => item.id === "scenario-6")
    expect(scenario?.status).toBe("ready")
    expect(scenario?.steps).toHaveLength(3)
    expect(scenario?.steps.every((step) => step.kind === "chat")).toBe(true)
  })

  it("resolves step and scenario lookups", () => {
    expect(getDemoStepIndex("3-build")).toBeGreaterThan(0)
    expect(getDemoStepIndex("missing")).toBe(-1)
    expect(getScenarioForStep(DEMO_STEPS[0])).toBe(DEMO_SCENARIOS[0])
  })
})

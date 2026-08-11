import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/system-config-api", () => ({
  getSystemConfiguration: vi.fn(),
}))

vi.mock("@/lib/configmaps-api", () => ({
  getConfigMap: vi.fn(),
  listAllConfigMaps: vi.fn(),
}))

import { getSystemConfiguration } from "@/lib/system-config-api"
import { getConfigMap } from "@/lib/configmaps-api"
import { validateSystemLlmConfigMaps } from "./system-config-meta"

describe("validateSystemLlmConfigMaps", () => {
  beforeEach(() => {
    vi.mocked(getSystemConfiguration).mockReset()
    vi.mocked(getConfigMap).mockReset()
  })

  it("checks ConfigMaps in the form-selected namespace, not hardcoded dac", async () => {
    vi.mocked(getSystemConfiguration).mockImplementation(async (name) => {
      if (name === "dac-configuration") {
        return {
          name,
          data: {
            "default-planner-llm": "llm-default",
            "default-expert-llm": "llm-default",
          },
        } as never
      }
      return { name, data: { "llm-config": "llm-default" } } as never
    })
    vi.mocked(getConfigMap).mockResolvedValue({
      name: "llm-default",
      namespace: "default",
      data: { model: "x" },
    } as never)

    await expect(validateSystemLlmConfigMaps("default")).resolves.toBeNull()
    expect(getConfigMap).toHaveBeenCalledWith("default", "llm-default")
    expect(getConfigMap).not.toHaveBeenCalledWith("dac", "llm-default")
  })

  it("reports missing ConfigMaps on 404 in the target namespace", async () => {
    vi.mocked(getSystemConfiguration).mockImplementation(async (name) => {
      if (name === "dac-configuration") {
        return {
          name,
          data: {
            "default-planner-llm": "llm-default",
            "default-expert-llm": "llm-default",
          },
        } as never
      }
      return { name, data: { "llm-config": "llm-default" } } as never
    })
    const axios = await import("axios")
    const err = new axios.AxiosError("not found")
    err.response = {
      status: 404,
      data: {},
      statusText: "Not Found",
      headers: {},
      config: { headers: {} as never },
    }
    vi.mocked(getConfigMap).mockRejectedValue(err)

    const msg = await validateSystemLlmConfigMaps("default")
    expect(msg).toContain("命名空间 default")
    expect(msg).toContain('default-planner-llm → "llm-default"')
  })
})

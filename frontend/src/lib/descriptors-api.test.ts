import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
  },
}))

import { api } from "@/lib/api"
import {
  getDescriptor,
  getDescriptorSemanticDomain,
  getDescriptorSignature,
} from "./descriptors-api"

describe("descriptors-api", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset()
  })

  it("getDescriptor hits namespaced path", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { name: "orders", namespace: "default", descriptor_type: "mysql" },
    })
    const out = await getDescriptor("default", "orders")
    expect(api.get).toHaveBeenCalledWith(
      "/namespaces/default/descriptors/orders",
    )
    expect(out.name).toBe("orders")
  })

  it("getDescriptorSignature returns null on 404", async () => {
    const axios = await import("axios")
    const err = new axios.AxiosError("not found")
    err.response = {
      status: 404,
      data: {},
      statusText: "Not Found",
      headers: {},
      config: { headers: {} as never },
    }
    vi.mocked(api.get).mockRejectedValue(err)
    await expect(getDescriptorSignature("ns", "n")).resolves.toBeNull()
  })

  it("getDescriptorSemanticDomain unwraps nested { data: SemanticDomain }", async () => {
    vi.mocked(api.get).mockResolvedValue({
      // After axios envelope unwrap, payload is still { data: domain }
      data: { data: { semantic_domain: "retail" } },
    })
    const out = await getDescriptorSemanticDomain("ns", "n")
    expect(out).toEqual({ semantic_domain: "retail" })
    expect(api.get).toHaveBeenCalledWith(
      "/namespaces/ns/descriptors/n/semantic-domain",
    )
  })

  it("getDescriptorSignature unwraps nested { data: Signature }", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { data: { metadata_content: { tables_detail: "1. x" } } },
    })
    const out = await getDescriptorSignature("ns", "n")
    expect(out).toEqual({ metadata_content: { tables_detail: "1. x" } })
  })
})

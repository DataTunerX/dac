import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    put: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}))

import { api } from "@/lib/api"
import {
  appendDescriptorSourcesAndResync,
  deleteDescriptor,
  getDescriptor,
  getDescriptorSemanticDomain,
  getDescriptorSignature,
  listAllDescriptors,
  waitUntilDescriptorGone,
} from "./descriptors-api"

describe("descriptors-api", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset()
    vi.mocked(api.put).mockReset()
    vi.mocked(api.post).mockReset()
    vi.mocked(api.delete).mockReset()
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

  it("deleteDescriptor hits namespaced path", async () => {
    vi.mocked(api.delete).mockResolvedValue({ data: undefined })
    await deleteDescriptor("default", "orders")
    expect(api.delete).toHaveBeenCalledWith(
      "/namespaces/default/descriptors/orders",
    )
  })

  it("listAllDescriptors paginates until exhausted", async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce({
        data: {
          items: Array.from({ length: 200 }, (_, i) => ({ name: `d${i}` })),
          totalCount: 201,
        },
      })
      .mockResolvedValueOnce({
        data: {
          items: [{ name: "d200" }],
          totalCount: 201,
        },
      })

    const items = await listAllDescriptors()
    expect(items).toHaveLength(201)
    expect(api.get).toHaveBeenNthCalledWith(1, "/descriptors", {
      params: { limit: 200, offset: 0 },
    })
    expect(api.get).toHaveBeenNthCalledWith(2, "/descriptors", {
      params: { limit: 200, offset: 200 },
    })
  })

  it("appendDescriptorSourcesAndResync updates then posts resync", async () => {
    vi.mocked(api.put).mockResolvedValue({
      data: { name: "orders", namespace: "default" },
    })
    vi.mocked(api.post).mockResolvedValue({ data: { status: "resync_requested" } })

    const sources = [{ name: "orders-b", type: "mysql", metadata: { database: "b" } }]
    await appendDescriptorSourcesAndResync("default", "orders", sources, {
      gpuEnabled: "no",
      descriptorType: "structured-mysql",
    })

    expect(api.put).toHaveBeenCalledWith("/namespaces/default/descriptors/orders", {
      sources,
      gpuEnabled: "no",
      descriptorType: "structured-mysql",
    })
    expect(api.post).toHaveBeenCalledWith(
      "/namespaces/default/descriptors/orders/resync",
    )
  })

  it("waitUntilDescriptorGone resolves on 404", async () => {
    const axios = await import("axios")
    const err = new axios.AxiosError("not found")
    err.response = {
      status: 404,
      data: {},
      statusText: "Not Found",
      headers: {},
      config: { headers: {} as never },
    }
    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: { name: "orders" } })
      .mockRejectedValueOnce(err)

    await expect(
      waitUntilDescriptorGone("default", "orders", {
        timeoutMs: 5_000,
        intervalMs: 1,
      }),
    ).resolves.toBeUndefined()
    expect(api.get).toHaveBeenCalledTimes(2)
  })
})

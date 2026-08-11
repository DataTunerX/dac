import { describe, expect, it } from "vitest"
import { AxiosError } from "axios"
import { isDescriptorNotFound } from "./use-data-source-detail"

describe("isDescriptorNotFound", () => {
  it("true when dd is null and no error (404 mapped to null)", () => {
    expect(isDescriptorNotFound(null, undefined)).toBe(true)
  })

  it("true when dd is null and error is 404", () => {
    const err = new AxiosError("not found")
    err.response = {
      status: 404,
      data: {},
      statusText: "Not Found",
      headers: {},
      config: { headers: {} as never },
    }
    expect(isDescriptorNotFound(null, err)).toBe(true)
  })

  it("false when dd is present", () => {
    expect(
      isDescriptorNotFound(
        { name: "x", namespace: "default", descriptor_type: "mysql", gpuEnabled: "no", sources: [], created_at: "", updated_at: "" },
        undefined,
      ),
    ).toBe(false)
  })

  it("false when dd is null and error is 500", () => {
    const err = new AxiosError("boom")
    err.response = {
      status: 500,
      data: {},
      statusText: "Error",
      headers: {},
      config: { headers: {} as never },
    }
    expect(isDescriptorNotFound(null, err)).toBe(false)
  })
})

import { AxiosError } from "axios"
import { describe, expect, it } from "vitest"
import { getApiErrorMessage } from "./api-error"

describe("getApiErrorMessage", () => {
  it("prefers axios response message", () => {
    const err = new AxiosError("Request failed")
    err.response = {
      data: { message: "forbidden" },
      status: 403,
      statusText: "Forbidden",
      headers: {},
      config: { headers: {} as never },
    }
    expect(getApiErrorMessage(err, "fallback")).toBe("forbidden")
  })

  it("falls back for unknown errors", () => {
    expect(getApiErrorMessage(new Error("boom"), "fallback")).toBe("boom")
    expect(getApiErrorMessage(null, "fallback")).toBe("fallback")
  })
})

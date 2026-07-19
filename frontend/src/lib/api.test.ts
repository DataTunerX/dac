import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/auth-session", () => ({
  getAuthToken: vi.fn(() => "test-token"),
  clearAuthToken: vi.fn(),
  redirectToLogin: vi.fn(),
}))

import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from "axios"
import { api } from "./api"
import { clearAuthToken, getAuthToken, redirectToLogin } from "@/lib/auth-session"

type InterceptorBucket<T> = {
  handlers: Array<{
    fulfilled?: (value: T) => T | Promise<T>
    rejected?: (error: unknown) => unknown
  }>
}

function requestHandlers() {
  return (api.interceptors.request as unknown as InterceptorBucket<InternalAxiosRequestConfig>)
    .handlers
}

function responseHandlers() {
  return (api.interceptors.response as unknown as InterceptorBucket<AxiosResponse>).handlers
}

describe("api interceptors", () => {
  beforeEach(() => {
    vi.mocked(getAuthToken).mockReturnValue("test-token")
    vi.mocked(clearAuthToken).mockClear()
    vi.mocked(redirectToLogin).mockClear()
  })

  it("attaches Bearer token on request", async () => {
    const fulfilled = requestHandlers()[0]?.fulfilled
    expect(fulfilled).toBeTypeOf("function")
    const cfg = await fulfilled!({ headers: {} } as InternalAxiosRequestConfig)
    expect((cfg.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    )
  })

  it("unwraps Go envelope { code, message, data }", async () => {
    const fulfilled = responseHandlers()[0]?.fulfilled
    expect(fulfilled).toBeTypeOf("function")
    const res = await fulfilled!({
      data: { code: 0, message: "ok", data: { id: "x" } },
      status: 200,
      statusText: "OK",
      headers: {},
      config: { headers: {} as never },
    })
    expect(res.data).toEqual({ id: "x" })
  })

  it("leaves non-envelope payloads alone", async () => {
    const fulfilled = responseHandlers()[0]?.fulfilled
    expect(fulfilled).toBeTypeOf("function")
    const res = await fulfilled!({
      data: { name: "plain" },
      status: 200,
      statusText: "OK",
      headers: {},
      config: { headers: {} as never },
    })
    expect(res.data).toEqual({ name: "plain" })
  })

  it("clears token and redirects on 401", async () => {
    const rejected = responseHandlers()[0]?.rejected
    expect(rejected).toBeTypeOf("function")

    const axiosErr = new AxiosError("Unauthorized")
    axiosErr.response = {
      status: 401,
      data: {},
      statusText: "Unauthorized",
      headers: {},
      config: { headers: {} as never },
    }

    const originalWindow = globalThis.window
    Object.defineProperty(globalThis, "window", {
      value: {
        location: { pathname: "/agents", search: "", hash: "" },
      },
      configurable: true,
      writable: true,
    })

    await expect(rejected!(axiosErr)).rejects.toBe(axiosErr)
    expect(clearAuthToken).toHaveBeenCalled()
    expect(redirectToLogin).toHaveBeenCalledWith("/agents")

    Object.defineProperty(globalThis, "window", {
      value: originalWindow,
      configurable: true,
      writable: true,
    })
  })
})

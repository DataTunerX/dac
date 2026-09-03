import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/auth-session", () => ({
  clearClientSession: vi.fn(),
  redirectToLogin: vi.fn(),
  refreshAuthSession: vi.fn(() => Promise.resolve(false)),
  isAuthRefreshPath: (url: string) =>
    url.includes("/auth/login") ||
    url.includes("/auth/register") ||
    url.includes("/auth/refresh") ||
    url.includes("/auth/logout"),
}))

import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from "axios"
import { api } from "./api"
import { setActiveTenantId } from "./tenant-context"
import {
  clearClientSession,
  redirectToLogin,
  refreshAuthSession,
} from "@/lib/auth-session"

type InterceptorBucket<T> = {
  handlers: Array<{
    fulfilled?: (value: T) => T | Promise<T>
    rejected?: (error: unknown) => unknown
  }>
}

function responseHandlers() {
  return (api.interceptors.response as unknown as InterceptorBucket<AxiosResponse>).handlers
}

describe("api interceptors", () => {
  beforeEach(() => {
    vi.mocked(clearClientSession).mockClear()
    vi.mocked(redirectToLogin).mockClear()
    vi.mocked(refreshAuthSession).mockReset()
    vi.mocked(refreshAuthSession).mockResolvedValue(false)
  })

  it("sends credentials for cookie auth", () => {
    expect(api.defaults.withCredentials).toBe(true)
  })

  it("does not attach a Bearer token from JS", () => {
    const requestHandlers = (
      api.interceptors.request as unknown as InterceptorBucket<InternalAxiosRequestConfig>
    ).handlers
    // The only request interceptor is the X-Tenant-Id scoping one — none inject Authorization.
    const injectsAuth = requestHandlers.filter((h) => {
      if (!h.fulfilled) return false
      return String(h.fulfilled).includes("Authorization")
    })
    expect(injectsAuth.length).toBe(0)
  })

  it("injects X-Tenant-Id header when a tenant is active", () => {
    const requestHandlers = (
      api.interceptors.request as unknown as InterceptorBucket<InternalAxiosRequestConfig>
    ).handlers
    const tenantInterceptor = requestHandlers.find((h) => h.fulfilled)
    expect(tenantInterceptor?.fulfilled).toBeTypeOf("function")

    const setHeader = vi.fn()
    const config = {
      headers: { set: setHeader },
    } as unknown as InternalAxiosRequestConfig

    setActiveTenantId("tenant-123")
    tenantInterceptor!.fulfilled!(config)
    expect(setHeader).toHaveBeenCalledWith("X-Tenant-Id", "tenant-123")
    setActiveTenantId(null)
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

  it("rejects HTTP 2xx envelopes with non-success business code", async () => {
    const fulfilled = responseHandlers()[0]?.fulfilled
    expect(fulfilled).toBeTypeOf("function")
    await expect(
      fulfilled!({
        data: { code: "FORBIDDEN", message: "无权限", data: null },
        status: 200,
        statusText: "OK",
        headers: {},
        config: { headers: {} as never },
      }),
    ).rejects.toMatchObject({ message: "无权限" })
  })

  it("accepts SUCCESS string envelope codes", async () => {
    const fulfilled = responseHandlers()[0]?.fulfilled
    expect(fulfilled).toBeTypeOf("function")
    const res = await fulfilled!({
      data: { code: "SUCCESS", message: "ok", data: { ok: true } },
      status: 200,
      statusText: "OK",
      headers: {},
      config: { headers: {} as never },
    })
    expect(res.data).toEqual({ ok: true })
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

  it("clears session and redirects on 401 when refresh fails", async () => {
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
    axiosErr.config = {
      url: "/agents",
      baseURL: "/api/v1",
      headers: {} as never,
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
    expect(refreshAuthSession).toHaveBeenCalled()
    expect(clearClientSession).toHaveBeenCalled()
    expect(redirectToLogin).toHaveBeenCalledWith("/agents")

    Object.defineProperty(globalThis, "window", {
      value: originalWindow,
      configurable: true,
      writable: true,
    })
  })

  it("skips refresh for auth login/register/refresh paths", async () => {
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
    axiosErr.config = {
      url: "/auth/login",
      baseURL: "/api/v1",
      headers: {} as never,
    }

    const originalWindow = globalThis.window
    Object.defineProperty(globalThis, "window", {
      value: {
        location: { pathname: "/login", search: "", hash: "" },
      },
      configurable: true,
      writable: true,
    })

    await expect(rejected!(axiosErr)).rejects.toBe(axiosErr)
    expect(refreshAuthSession).not.toHaveBeenCalled()
    expect(clearClientSession).toHaveBeenCalled()
    expect(redirectToLogin).not.toHaveBeenCalled()

    Object.defineProperty(globalThis, "window", {
      value: originalWindow,
      configurable: true,
      writable: true,
    })
  })
})

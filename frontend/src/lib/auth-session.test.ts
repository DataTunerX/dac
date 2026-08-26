import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  AUTH_CHANGE_EVENT,
  clearClientSession,
  establishSession,
  getClientSession,
  getSafeNextPath,
  isAuthRefreshPath,
} from "./auth-session"

describe("getSafeNextPath", () => {
  it("returns the requested relative path", () => {
    expect(getSafeNextPath("?next=%2Fagents%3Ftab%3Doverview")).toBe("/agents?tab=overview")
  })

  it("falls back to root for missing next", () => {
    expect(getSafeNextPath("")).toBe("/")
  })

  it("rejects non-relative redirects", () => {
    expect(getSafeNextPath("?next=https%3A%2F%2Fevil.example")).toBe("/")
    expect(getSafeNextPath("?next=%2F%2Fevil.example")).toBe("/")
  })
})

describe("client session snapshot", () => {
  beforeEach(() => {
    const target = new EventTarget()
    Object.defineProperty(globalThis, "window", {
      value: target,
      configurable: true,
      writable: true,
    })
    clearClientSession()
  })

  it("stores username in module memory", () => {
    establishSession({ username: "alice" })
    expect(getClientSession()).toEqual({
      username: "alice",
      isSuper: false,
      platformRoles: [],
      permissionCodes: [],
    })
    clearClientSession()
    expect(getClientSession()).toBeNull()
  })

  it("defaults username to empty string when missing", () => {
    establishSession({})
    expect(getClientSession()).toEqual({
      username: "",
      isSuper: false,
      platformRoles: [],
      permissionCodes: [],
    })
  })

  it("normalizes isSuper and permission codes from the payload", () => {
    establishSession({
      username: "carol",
      isSuper: true,
      platformRoles: ["super_admin", "ops"],
      permissionCodes: ["tenant:manage", "user:manage", 42 as never, null as never],
    })
    expect(getClientSession()).toEqual({
      username: "carol",
      isSuper: true,
      platformRoles: ["super_admin", "ops"],
      permissionCodes: ["tenant:manage", "user:manage"],
    })
  })

  it("emits AUTH_CHANGE_EVENT on establish/clear", () => {
    const spy = vi.fn()
    window.addEventListener(AUTH_CHANGE_EVENT, spy)
    establishSession({ username: "carol" })
    clearClientSession()
    window.removeEventListener(AUTH_CHANGE_EVENT, spy)
    expect(spy).toHaveBeenCalledTimes(2)
  })
})

describe("isAuthRefreshPath", () => {
  it("matches login/register/refresh/logout", () => {
    expect(isAuthRefreshPath("/api/v1/auth/login")).toBe(true)
    expect(isAuthRefreshPath("/api/v1/auth/register")).toBe(true)
    expect(isAuthRefreshPath("/api/v1/auth/refresh")).toBe(true)
    expect(isAuthRefreshPath("/api/v1/auth/logout")).toBe(true)
    expect(isAuthRefreshPath("/api/v1/agents")).toBe(false)
  })
})
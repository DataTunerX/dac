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

  it("stores role/username in module memory", () => {
    establishSession({ role: "admin", username: "alice" })
    expect(getClientSession()).toEqual({ role: "admin", username: "alice" })
    clearClientSession()
    expect(getClientSession()).toBeNull()
  })

  it("defaults role to user when missing", () => {
    establishSession({ username: "bob" })
    expect(getClientSession()).toEqual({ role: "user", username: "bob" })
  })

  it("emits AUTH_CHANGE_EVENT on establish/clear", () => {
    const spy = vi.fn()
    window.addEventListener(AUTH_CHANGE_EVENT, spy)
    establishSession({ role: "user", username: "carol" })
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

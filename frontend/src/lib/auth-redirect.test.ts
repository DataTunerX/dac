import { describe, expect, it } from "vitest"
import { buildExternalOrigin, buildLoginRedirectUrl, isPublicPath, requiresAuth } from "./auth-redirect"

function createRequestUrl(pathname: string, search = "", origin = "http://127.0.0.1:3001") {
  const url = new URL(origin)
  url.pathname = pathname
  url.search = search
  return url
}

describe("isPublicPath", () => {
  it("allows auth pages and their nested paths", () => {
    expect(isPublicPath("/login")).toBe(true)
    expect(isPublicPath("/register")).toBe(true)
    expect(isPublicPath("/login/reset")).toBe(true)
  })

  it("does not treat protected pages as public", () => {
    expect(isPublicPath("/")).toBe(false)
    expect(isPublicPath("/agents")).toBe(false)
  })
})

describe("requiresAuth", () => {
  it("protects the dashboard root and known app sections", () => {
    expect(requiresAuth("/")).toBe(true)
    expect(requiresAuth("/agents")).toBe(true)
    expect(requiresAuth("/semantic-groups/123")).toBe(true)
  })

  it("ignores unrelated paths", () => {
    expect(requiresAuth("/healthz")).toBe(false)
    expect(requiresAuth("/api/v1/auth/login")).toBe(false)
  })
})

describe("buildExternalOrigin", () => {
  it("prefers x-forwarded host and proto from the proxy", () => {
    const headers = new Headers({
      "x-forwarded-proto": "http",
      "x-forwarded-host": "10.17.0.41",
      "x-forwarded-port": "31777",
      host: "127.0.0.1:3001",
    })

    expect(buildExternalOrigin(headers, createRequestUrl("/"))).toBe("http://10.17.0.41:31777")
  })

  it("does not append default ports", () => {
    const headers = new Headers({
      "x-forwarded-proto": "https",
      "x-forwarded-host": "dac.example.com",
      "x-forwarded-port": "443",
    })

    expect(buildExternalOrigin(headers, createRequestUrl("/"))).toBe("https://dac.example.com")
  })

  it("falls back to host header when forwarded host is absent", () => {
    const headers = new Headers({
      host: "frontend.internal:3000",
    })

    expect(buildExternalOrigin(headers, createRequestUrl("/"))).toBe("http://frontend.internal:3000")
  })

  it("ignores malformed forwarded hosts and falls back safely", () => {
    const headers = new Headers({
      "x-forwarded-proto": "https",
      "x-forwarded-host": "http://evil.example/bad",
      host: "frontend.internal:3000",
    })

    expect(buildExternalOrigin(headers, createRequestUrl("/"))).toBe("https://frontend.internal:3000")
  })

  it("rejects spoofed forwarded host when Host is a public name", () => {
    const headers = new Headers({
      "x-forwarded-proto": "https",
      "x-forwarded-host": "evil.example",
      host: "dac.example.com",
    })

    expect(buildExternalOrigin(headers, createRequestUrl("/"))).toBe("https://dac.example.com")
  })
})

describe("buildLoginRedirectUrl", () => {
  it("preserves the original path and query in next", () => {
    const headers = new Headers({
      "x-forwarded-proto": "http",
      "x-forwarded-host": "10.17.0.41",
      "x-forwarded-port": "31777",
    })

    const redirectUrl = buildLoginRedirectUrl(headers, createRequestUrl("/agents", "?tab=overview"))
    expect(redirectUrl.toString()).toBe("http://10.17.0.41:31777/login?next=%2Fagents%3Ftab%3Doverview")
  })

  it("never leaks the internal upstream origin when proxy headers exist", () => {
    const headers = new Headers({
      "x-forwarded-proto": "http",
      "x-forwarded-host": "10.17.0.41",
      "x-forwarded-port": "31777",
      host: "127.0.0.1:3001",
    })

    const redirectUrl = buildLoginRedirectUrl(headers, createRequestUrl("/"))
    expect(redirectUrl.origin).toBe("http://10.17.0.41:31777")
    expect(redirectUrl.toString()).not.toContain("127.0.0.1:3001")
  })
})

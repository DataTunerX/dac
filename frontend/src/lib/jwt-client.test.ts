import { describe, expect, it } from "vitest"
import { decodeJwtPayload, isJwtUsable } from "./jwt-client"

function makeToken(payload: Record<string, unknown>): string {
  const header = Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64url")
  const body = Buffer.from(JSON.stringify(payload)).toString("base64url")
  return `${header}.${body}.sig`
}

describe("isJwtUsable", () => {
  it("rejects empty / malformed tokens", () => {
    expect(isJwtUsable("")).toBe(false)
    expect(isJwtUsable("not.a.jwt.extra")).toBe(false)
    expect(isJwtUsable("a.b")).toBe(false)
  })

  it("accepts unexpired tokens and rejects expired ones", () => {
    const ok = makeToken({ username: "admin", exp: Math.floor(Date.now() / 1000) + 3600 })
    const expired = makeToken({ username: "admin", exp: Math.floor(Date.now() / 1000) - 3600 })
    expect(isJwtUsable(ok)).toBe(true)
    expect(isJwtUsable(expired)).toBe(false)
  })
})

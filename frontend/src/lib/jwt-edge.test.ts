import { afterEach, describe, expect, it } from "vitest"
import { isPayloadRefreshable, readJwtPayload } from "./jwt-edge"

const originalDacSecret = process.env.DAC_JWT_SECRET
const originalJwtSecret = process.env.JWT_SECRET
const originalMaxRefresh = process.env.DAC_JWT_MAX_REFRESH

function unsignedToken(payload: Record<string, unknown>): string {
  const encode = (value: object) =>
    Buffer.from(JSON.stringify(value)).toString("base64url")
  return `${encode({ alg: "HS256", typ: "JWT" })}.${encode(payload)}.forged`
}

afterEach(() => {
  if (originalDacSecret === undefined) delete process.env.DAC_JWT_SECRET
  else process.env.DAC_JWT_SECRET = originalDacSecret
  if (originalJwtSecret === undefined) delete process.env.JWT_SECRET
  else process.env.JWT_SECRET = originalJwtSecret
  if (originalMaxRefresh === undefined) delete process.env.DAC_JWT_MAX_REFRESH
  else process.env.DAC_JWT_MAX_REFRESH = originalMaxRefresh
})

describe("server JWT validation", () => {
  it("fails closed when no verification secret is configured", async () => {
    delete process.env.DAC_JWT_SECRET
    delete process.env.JWT_SECRET

    const payload = await readJwtPayload(
      unsignedToken({ role: "admin", exp: Math.floor(Date.now() / 1000) + 3600 }),
    )

    expect(payload).toBeNull()
  })

  it("uses the configured server refresh window", () => {
    process.env.DAC_JWT_MAX_REFRESH = "24h"
    const now = Date.UTC(2026, 7, 5)
    const twentyFiveHoursAgo = Math.floor((now - 25 * 60 * 60 * 1000) / 1000)

    expect(isPayloadRefreshable({ orig_iat: twentyFiveHoursAgo }, now)).toBe(false)
  })
})

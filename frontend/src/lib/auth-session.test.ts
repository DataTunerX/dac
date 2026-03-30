import { describe, expect, it } from "vitest"
import { getSafeNextPath } from "./auth-session"

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

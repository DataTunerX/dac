import { describe, expect, it } from "vitest"
import { unwrapNestedData } from "./unwrap-nested-data"

describe("unwrapNestedData", () => {
  it("unwraps { data: T }", () => {
    expect(unwrapNestedData<{ a: number }>({ data: { a: 1 } })).toEqual({ a: 1 })
  })

  it("returns flat object when no nested data", () => {
    expect(unwrapNestedData<{ a: number }>({ a: 1 })).toEqual({ a: 1 })
  })

  it("returns null for non-objects", () => {
    expect(unwrapNestedData(null)).toBeNull()
    expect(unwrapNestedData("x")).toBeNull()
  })
})

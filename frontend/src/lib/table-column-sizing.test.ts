import { beforeEach, describe, expect, it } from "vitest"
import {
  clampColumnSizing,
  readStoredColumnSizing,
  resolveColumnBounds,
  writeStoredColumnSizing,
} from "./table-column-sizing"

describe("table column sizing storage", () => {
  beforeEach(() => {
    const store = new Map<string, string>()
    globalThis.localStorage = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value)
      },
      removeItem: (key: string) => {
        store.delete(key)
      },
      clear: () => store.clear(),
      key: (index: number) => Array.from(store.keys())[index] ?? null,
      get length() {
        return store.size
      },
    }
  })

  it("round-trips sizing through localStorage", () => {
    const key = "test-table"
    writeStoredColumnSizing(key, { name: 220, namespace: 140 })
    expect(readStoredColumnSizing(key)).toEqual({ name: 220, namespace: 140 })
  })

  it("returns empty object for invalid stored payload", () => {
    localStorage.setItem("table-column-sizing:bad", "not-json")
    expect(readStoredColumnSizing("bad")).toEqual({})
  })

  it("clamps stored sizing to column safe bounds", () => {
    const columns = [{ id: "name", size: 200 }] as const
    writeStoredColumnSizing("agents-list", { name: 9999 })
    expect(readStoredColumnSizing("agents-list", [...columns])).toEqual({
      name: 400,
    })
  })
})

describe("resolveColumnBounds", () => {
  it("derives min/max from default size when not provided", () => {
    expect(resolveColumnBounds({ id: "name", size: 200 })).toEqual({
      size: 200,
      minSize: 90,
      maxSize: 400,
    })
  })

  it("respects explicit min/max overrides", () => {
    expect(
      resolveColumnBounds({ id: "actions", size: 120, minSize: 96, maxSize: 160 }),
    ).toEqual({
      size: 120,
      minSize: 96,
      maxSize: 160,
    })
  })
})

describe("clampColumnSizing", () => {
  it("drops unknown columns and clamps known ones", () => {
    const columns = [
      { id: "name", size: 220 },
      { id: "actions", size: 120, minSize: 96, maxSize: 180 },
    ]
    expect(
      clampColumnSizing({ name: 10, actions: 500, unknown: 300 }, columns),
    ).toEqual({
      name: 99,
      actions: 180,
    })
  })
})

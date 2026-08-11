import { describe, expect, it } from "vitest"
import {
  buildAppendSources,
  buildCreateDescriptorPayload,
  sanitizeDBSegment,
  toUpdateSource,
} from "./descriptor-payload"

describe("sanitizeDBSegment", () => {
  it("normalizes unsafe characters", () => {
    expect(sanitizeDBSegment("My_DB.Name")).toBe("my-db-name")
  })

  it("falls back when empty after sanitize", () => {
    expect(sanitizeDBSegment("!!!")).toBe("db")
  })
})

describe("buildCreateDescriptorPayload", () => {
  it("fans out mysql databases into one source each", () => {
    const payload = buildCreateDescriptorPayload({
      name: "orders",
      namespace: "default",
      type: "mysql",
      host: "10.0.0.1",
      port: "3306",
      user: "root",
      password: "secret",
      databases: ["a", "b"],
    })
    expect(payload.descriptorType).toBe("structured-mysql")
    expect(payload.sources).toHaveLength(2)
    expect(payload.sources.map((s) => s.metadata?.database)).toEqual(["a", "b"])
    expect(payload.sources[0]?.name).toBe("orders-a")
  })

  it("requires at least one database for structured types", () => {
    expect(() =>
      buildCreateDescriptorPayload({
        name: "orders",
        type: "postgres",
        databases: [],
      }),
    ).toThrow(/请至少选择一个数据库/)
  })

  it("builds a single source for minio", () => {
    const payload = buildCreateDescriptorPayload({
      name: "files",
      type: "minio",
      host: "10.0.0.2",
      port: "9000",
      accessKey: "ak",
      secretKey: "sk",
      bucket: "dac",
      extractFiles: "a.pdf\nb.pdf",
    })
    expect(payload.descriptorType).toBe("unstructured")
    expect(payload.sources).toHaveLength(1)
    expect(payload.sources[0]?.metadata?.host).toBe("10.0.0.2:9000")
    expect(payload.sources[0]?.extract?.files).toEqual(["a.pdf", "b.pdf"])
  })
})

describe("buildAppendSources", () => {
  it("merges new databases without dropping existing sources", () => {
    const sources = buildAppendSources({
      existingSources: [
        {
          name: "orders-a",
          type: "mysql",
          metadata: {
            host: "10.0.0.1",
            port: "3306",
            user: "root",
            password: "secret",
            database: "a",
          },
        },
      ],
      descriptorName: "orders",
      type: "mysql",
      host: "10.0.0.1",
      port: "3306",
      user: "root",
      password: "secret",
      newDatabases: ["a", "b"],
    })
    expect(sources).toHaveLength(2)
    expect(sources.map((s) => s.metadata?.database)).toEqual(["a", "b"])
  })

  it("throws when every selected database already exists", () => {
    expect(() =>
      buildAppendSources({
        existingSources: [
          {
            name: "orders-a",
            type: "mysql",
            metadata: { database: "a" },
          },
        ],
        descriptorName: "orders",
        type: "mysql",
        host: "h",
        port: "3306",
        user: "u",
        password: "p",
        newDatabases: ["a"],
      }),
    ).toThrow(/尚未关联/)
  })
})

describe("toUpdateSource", () => {
  it("preserves extract and cleaning", () => {
    const out = toUpdateSource({
      name: "s1",
      type: "mysql",
      metadata: { database: "a" },
      extract: { tables: ["t1"], querys: [], files: [] },
      processing: { cleaning: [{ rule: "trim", params: { col: "x" } }] },
    })
    expect(out.extract?.tables).toEqual(["t1"])
    expect(out.processing?.cleaning).toEqual([{ rule: "trim", params: { col: "x" } }])
  })
})

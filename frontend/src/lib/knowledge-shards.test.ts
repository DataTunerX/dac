import { describe, expect, it } from "vitest"
import {
  UNKNOWN_KNOWLEDGE_FILE_GROUP_ID,
  getKnowledgeFileGroupKey,
  groupKnowledgeShards,
} from "./knowledge-shards"

describe("getKnowledgeFileGroupKey", () => {
  it("groups document shards by file_name", () => {
    expect(getKnowledgeFileGroupKey({ file_name: "book1.pdf" })).toBe("file:book1.pdf")
  })

  it("falls back to minio_path when file_name is missing", () => {
    expect(
      getKnowledgeFileGroupKey({ minio_path: "minio://bucket/docs/book1.pdf" }),
    ).toBe("path:minio://bucket/docs/book1.pdf")
  })

  it("groups database shards by module_name", () => {
    expect(getKnowledgeFileGroupKey({ module_name: "订单模块" })).toBe("module:订单模块")
  })

  it("returns unknown bucket when metadata has no file hints", () => {
    expect(getKnowledgeFileGroupKey({ summary: "only summary" })).toBe(
      UNKNOWN_KNOWLEDGE_FILE_GROUP_ID,
    )
  })
})

describe("groupKnowledgeShards", () => {
  it("aggregates shard counts per file", () => {
    const groups = groupKnowledgeShards([
      { metadata: { file_name: "a.pdf", summary: "chunk 1" } },
      { metadata: { file_name: "a.pdf", summary: "chunk 2" } },
      { metadata: { file_name: "b.pdf", summary: "chunk 3" } },
    ])

    expect(groups).toHaveLength(2)
    expect(groups.find((group) => group.label === "a.pdf")?.shards).toHaveLength(2)
    expect(groups.find((group) => group.label === "b.pdf")?.shards).toHaveLength(1)
  })

  it("keeps original shard indices for detail dialogs", () => {
    const groups = groupKnowledgeShards([
      { metadata: { file_name: "a.pdf" } },
      { metadata: { file_name: "b.pdf" } },
      { metadata: { file_name: "a.pdf" } },
    ])

    const groupA = groups.find((group) => group.label === "a.pdf")
    expect(groupA?.shards.map((shard) => shard.originalIndex)).toEqual([0, 2])
  })
})

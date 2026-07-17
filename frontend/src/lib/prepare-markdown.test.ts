import { describe, expect, it } from "vitest"
import { prepareMarkdown } from "./prepare-markdown"

describe("prepareMarkdown — GFM tables", () => {
  it("splits single-line table with colon-less separator (|---|---|)", () => {
    const input =
      "| 商品名称 | SKU | 品牌 | |---|---|---| | iPhone | SKU-001 | Apple | | Samsung | SKU-002 | Samsung |"
    const out = prepareMarkdown(input)
    expect(out.split("\n").length).toBeGreaterThanOrEqual(4)
    expect(out).toContain("| iPhone |")
    expect(out).toContain("| Samsung |")
  })

  it("splits single-line table with :--- separator", () => {
    const input = "| a | b | | :--- | :--- | | r1 | v1 | | r2 | v2 |"
    const out = prepareMarkdown(input)
    expect(out.split("\n").length).toBeGreaterThanOrEqual(4)
  })

  it("preserves prefix text before squashed table", () => {
    const input = "销售明细如下：| 名称 | 数量 | |---|---| | A | 1 |"
    const out = prepareMarkdown(input)
    expect(out.startsWith("销售明细如下：")).toBe(true)
    expect(out).toContain("\n| 名称 |")
  })

  it("does not alter valid multi-line tables", () => {
    const input = ["| H1 | H2 |", "| --- | --- |", "| a | b |"].join("\n")
    expect(prepareMarkdown(input)).toBe(input)
  })

  it("unescapes literal \\n before table repair", () => {
    const input = "| A | B |\\n|---|---|\\n| 1 | 2 |"
    const out = prepareMarkdown(input)
    expect(out.split("\n").length).toBeGreaterThanOrEqual(3)
  })
})

describe("prepareMarkdown — empty table cells", () => {
  it("does not split valid rows that contain empty cells", () => {
    const input = [
      "| Column | Type | Nullable | Key | Comment |",
      "|--------|------|----------|-----|---------|",
      "| `id` | `int4(32,0)` | NO | PRI | None |",
      "| `first_name` | `varchar(256)` | NO |  |  |",
      "| `last_name` | `varchar(256)` | NO |  |  |",
    ].join("\n")
    const out = prepareMarkdown(input)
    expect(out).toBe(input)
    // Each data row must still have 5 cells
    const firstNameLine = out.split("\n").find((l) => l.includes("first_name"))
    expect(firstNameLine).toBeDefined()
    expect(firstNameLine!.split("|").filter(Boolean).length).toBeGreaterThanOrEqual(5)
  })
})

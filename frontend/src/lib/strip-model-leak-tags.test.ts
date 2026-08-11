import { describe, expect, it } from "vitest"
import { stripModelLeakTags, stripModelLeakLines } from "./strip-model-leak-tags"

const closeThink = "</" + "think>"
const closeRedacted = "</" + "redacted_thinking>"
const openThink = "<" + "think>"
const closeThinkBlock = "</" + "think>"

describe("stripModelLeakTags", () => {
  it("removes orphan closing think tag", () => {
    expect(stripModelLeakTags(`结论如下。\n${closeThink}`)).toBe("结论如下。\n")
  })

  it("removes orphan closing redacted_thinking tag", () => {
    expect(stripModelLeakTags(`answer\n${closeRedacted}`)).toBe("answer\n")
  })

  it("removes full think blocks", () => {
    expect(stripModelLeakTags(`前缀${openThink}中间${closeThinkBlock}后缀`)).toBe("前缀后缀")
  })

  it("preserves normal markdown and code fences", () => {
    const input = "```js\nconsole.log('ok')\n```\n\n正常回答"
    expect(stripModelLeakTags(input)).toBe(input)
  })
})

describe("stripModelLeakLines", () => {
  it("removes lines starting with reason:", () => {
    expect(stripModelLeakLines("reason:some text\nreal answer")).toBe("real answer")
  })

  it("handles case-insensitive Reason:", () => {
    expect(stripModelLeakLines("Reason: thinking\nanswer")).toBe("answer")
  })

  it("handles leading whitespace before reason:", () => {
    expect(stripModelLeakLines("  reason: with space\ncontent")).toBe("content")
  })

  it("preserves normal text", () => {
    expect(stripModelLeakLines("normal\nmultiline\nanswer")).toBe("normal\nmultiline\nanswer")
  })

  it("returns empty string as-is", () => {
    expect(stripModelLeakLines("")).toBe("")
  })

  it("removes reason line with colon but no space", () => {
    expect(stripModelLeakLines("reason:The current answer addresses the question very well.\n\nHere is the answer.")).toBe("\nHere is the answer.")
  })
})

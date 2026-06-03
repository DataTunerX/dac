import { describe, expect, it } from "vitest"
import { stripModelLeakTags } from "./strip-model-leak-tags"

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

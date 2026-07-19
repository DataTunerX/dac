import { describe, expect, it } from "vitest"
import { sanitizeSvg } from "./sanitize-svg"

describe("sanitizeSvg", () => {
  it("strips script tags and event handlers", () => {
    const dirty =
      '<svg><script>alert(1)</script><g onclick="evil()"><text>ok</text></g></svg>'
    const out = sanitizeSvg(dirty)
    expect(out).not.toContain("<script")
    expect(out).not.toMatch(/onclick/i)
    expect(out).toContain("ok")
  })

  it("strips foreignObject", () => {
    const dirty =
      '<svg><foreignObject><body xmlns="http://www.w3.org/1999/xhtml"><script>x</script></body></foreignObject><text>keep</text></svg>'
    const out = sanitizeSvg(dirty)
    expect(out).not.toContain("foreignObject")
    expect(out).toContain("keep")
  })
})

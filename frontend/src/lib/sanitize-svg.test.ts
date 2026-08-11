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

  it("keeps foreignObject labels but strips active HTML inside them", () => {
    const dirty =
      '<svg><foreignObject width="100" height="40"><div xmlns="http://www.w3.org/1999/xhtml" class="nodeLabel"><span>开始</span><script>x</script><iframe src="https://evil.example"></iframe></div></foreignObject><text>keep</text></svg>'
    const out = sanitizeSvg(dirty)
    expect(out).toContain("foreignObject")
    expect(out).toContain("开始")
    expect(out).toContain("keep")
    expect(out).not.toContain("<script")
    expect(out).not.toContain("iframe")
    expect(out).not.toContain("data-dac-fo")
  })

  it("keeps Chinese Mermaid flowchart node labels in foreignObject", () => {
    const dirty = `<svg>
  <g class="node">
    <rect />
    <foreignObject width="120" height="30">
      <div xmlns="http://www.w3.org/1999/xhtml"><span class="nodeLabel">输入账号密码</span></div>
    </foreignObject>
  </g>
  <g class="edgeLabel">
    <foreignObject width="40" height="20">
      <div xmlns="http://www.w3.org/1999/xhtml"><span>是否通过?</span></div>
    </foreignObject>
  </g>
</svg>`
    const out = sanitizeSvg(dirty)
    expect(out).toContain("输入账号密码")
    expect(out).toContain("是否通过?")
    expect(out).toContain("foreignObject")
  })

  it("keeps native SVG text labels as a fallback path", () => {
    const dirty =
      '<svg><g><rect/><text class="nodeLabel">开始</text><text class="edgeLabel">是</text></g></svg>'
    const out = sanitizeSvg(dirty)
    expect(out).toContain("开始")
    expect(out).toContain("是")
  })
})

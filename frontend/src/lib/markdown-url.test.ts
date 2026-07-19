import { describe, expect, it } from "vitest"
import { isExternalMarkdownHref, sanitizeMarkdownHref } from "./markdown-url"

describe("sanitizeMarkdownHref", () => {
  it("allows relative and http(s) links", () => {
    expect(sanitizeMarkdownHref("/agents")).toBe("/agents")
    expect(sanitizeMarkdownHref("https://example.com")).toBe("https://example.com")
    expect(sanitizeMarkdownHref("mailto:a@b.com")).toBe("mailto:a@b.com")
    expect(sanitizeMarkdownHref("#section")).toBe("#section")
  })

  it("blocks javascript, data, and protocol-relative URLs", () => {
    expect(sanitizeMarkdownHref("javascript:alert(1)")).toBeUndefined()
    expect(sanitizeMarkdownHref("data:text/html,hi")).toBeUndefined()
    expect(sanitizeMarkdownHref("//evil.example/phish")).toBeUndefined()
  })
})

describe("isExternalMarkdownHref", () => {
  it("detects http(s) only", () => {
    expect(isExternalMarkdownHref("https://a.com")).toBe(true)
    expect(isExternalMarkdownHref("/local")).toBe(false)
  })
})

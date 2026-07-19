import DOMPurify from "isomorphic-dompurify"

/**
 * Sanitize SVG before dangerouslySetInnerHTML (Mermaid output).
 * Prefer Mermaid securityLevel "strict"; this is defense-in-depth.
 */
export function sanitizeSvg(svg: string): string {
  if (!svg) return ""
  return DOMPurify.sanitize(svg, {
    USE_PROFILES: { svg: true, svgFilters: true },
    // foreignObject can host HTML; keep it out of untrusted LLM diagrams
    FORBID_TAGS: ["script", "foreignObject"],
  })
}

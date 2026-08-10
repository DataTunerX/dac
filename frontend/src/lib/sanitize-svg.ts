import DOMPurify from "isomorphic-dompurify"

const FORBIDDEN_ACTIVE_TAGS = [
  "script",
  "iframe",
  "object",
  "embed",
  "form",
  "input",
  "button",
  "textarea",
  "select",
] as const

/** Marker used while SVG-sanitizing around Mermaid HTML labels. */
const FO_PLACEHOLDER_ATTR = "data-dac-fo"

/**
 * Labels Mermaid emits inside foreignObject (htmlLabels=true). Keep typography
 * tags only — no anchors/media/forms.
 */
const FO_ALLOWED_TAGS = [
  "div",
  "span",
  "p",
  "br",
  "b",
  "i",
  "strong",
  "em",
  "u",
  "code",
  "pre",
  "ul",
  "ol",
  "li",
] as const

/**
 * Sanitize Mermaid SVG before dangerouslySetInnerHTML.
 *
 * Defense-in-depth on top of Mermaid `securityLevel: "strict"`:
 * Mermaid flowchart labels default to HTML inside `<foreignObject>`. DOMPurify
 * cannot keep those HTML children in a single SVG pass, so we:
 * 1) sanitize each foreignObject island as HTML
 * 2) mask it, sanitize the SVG shell (scripts / handlers / active tags)
 * 3) restore the cleaned label HTML
 */
export function sanitizeSvg(svg: string): string {
  if (!svg) return ""

  const placeholders: string[] = []
  const masked = svg.replace(
    /<foreignObject(\b[^>]*)>([\s\S]*?)<\/foreignObject>/gi,
    (_full, attrs: string, inner: string) => {
      const cleanInner = DOMPurify.sanitize(inner, {
        ALLOWED_TAGS: [...FO_ALLOWED_TAGS],
        ALLOWED_ATTR: ["class", "style", "xmlns"],
        ALLOW_DATA_ATTR: false,
        FORBID_TAGS: [...FORBIDDEN_ACTIVE_TAGS],
      })
      const idx = placeholders.length
      placeholders.push(cleanInner)
      const cleanAttrs = String(attrs).replace(/\s*data-dac-fo="[^"]*"/gi, "")
      return `<foreignObject${cleanAttrs} ${FO_PLACEHOLDER_ATTR}="${idx}"></foreignObject>`
    }
  )

  let cleaned = DOMPurify.sanitize(masked, {
    USE_PROFILES: { svg: true, svgFilters: true },
    ADD_TAGS: ["foreignObject"],
    ADD_ATTR: [FO_PLACEHOLDER_ATTR],
    FORBID_TAGS: [...FORBIDDEN_ACTIVE_TAGS],
  })

  cleaned = cleaned.replace(
    /<foreignObject([^>]*?)(?:\/>|><\/foreignObject>)/gi,
    (full, attrs: string) => {
      const match = attrs.match(/data-dac-fo="(\d+)"/i)
      if (!match) return full
      const inner = placeholders[Number(match[1])] ?? ""
      const cleanAttrs = attrs.replace(/\s*data-dac-fo="\d+"/gi, "")
      return `<foreignObject${cleanAttrs}>${inner}</foreignObject>`
    }
  )

  return cleaned
}

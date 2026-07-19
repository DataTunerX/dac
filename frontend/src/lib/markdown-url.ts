/**
 * Safe href for react-markdown link components.
 * Allows same-origin relative paths and http(s); blocks javascript:, data:, and protocol-relative //.
 */
export function sanitizeMarkdownHref(href: string | undefined | null): string | undefined {
  if (href == null) return undefined
  const raw = String(href).trim()
  if (!raw) return undefined

  // Protocol-relative → treat as external http; still allow but force https-safe rel via isExternalMarkdownHref
  if (raw.startsWith("//")) return undefined

  const lower = raw.toLowerCase()
  if (lower.startsWith("javascript:") || lower.startsWith("data:") || lower.startsWith("vbscript:")) {
    return undefined
  }

  if (raw.startsWith("/") && !raw.startsWith("//")) return raw
  if (raw.startsWith("#") || raw.startsWith("?")) return raw
  if (lower.startsWith("http://") || lower.startsWith("https://") || lower.startsWith("mailto:")) {
    return raw
  }

  // Reject scheme-less / unknown schemes
  if (/^[a-z][a-z0-9+.-]*:/i.test(raw)) return undefined

  // Relative path without leading slash (e.g. docs/foo)
  if (!raw.includes("://")) return raw

  return undefined
}

export function isExternalMarkdownHref(href: string | undefined): boolean {
  if (!href) return false
  return href.startsWith("http://") || href.startsWith("https://")
}

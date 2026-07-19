/**
 * Client/edge JWT helpers. Does NOT verify signatures (no secret in the browser).
 * Used only to reject obviously unusable tokens (malformed / expired) for UX gates.
 */

type JwtPayload = {
  exp?: number
  role?: string
  user_id?: string
  username?: string
}

function base64UrlDecode(segment: string): string {
  const padded = segment.replace(/-/g, "+").replace(/_/g, "/")
  const pad = padded.length % 4 === 0 ? "" : "=".repeat(4 - (padded.length % 4))
  const b64 = padded + pad
  if (typeof atob === "function") {
    return atob(b64)
  }
  // Node / Vitest
  return Buffer.from(b64, "base64").toString("utf8")
}

export function decodeJwtPayload(token: string): JwtPayload | null {
  const parts = token.split(".")
  if (parts.length !== 3) return null
  try {
    const json = base64UrlDecode(parts[1])
    const payload = JSON.parse(json) as unknown
    if (!payload || typeof payload !== "object") return null
    return payload as JwtPayload
  } catch {
    return null
  }
}

/** True when token has 3 segments and exp is missing or in the future (30s skew). */
export function isJwtUsable(token: string | undefined | null, nowMs = Date.now()): boolean {
  if (!token || !token.trim()) return false
  const payload = decodeJwtPayload(token.trim())
  if (!payload) return false
  if (typeof payload.exp !== "number") return true
  return payload.exp * 1000 > nowMs - 30_000
}

export function getJwtRole(token: string | undefined | null): string {
  if (!isJwtUsable(token)) return "anonymous"
  const payload = decodeJwtPayload(token!)
  const role = payload?.role
  return typeof role === "string" && role.trim() ? role : "user"
}
